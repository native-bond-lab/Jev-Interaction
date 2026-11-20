"""One call: audio in, decisions by Jev, lines out.

The session is transport-agnostic. Feed it 200 ms PCM16 frames (`on_audio`) and client messages (`on_client`); it sends
events through `send` and keeps the call's history in a Ledger. It holds the call's state and its loop; every
interaction decision is a module in decisions/ that the session offers each new segment of words and each tick, whose
question is in judge/questions.py and whose answer goes through the policy configured for it (policy.py):

    the user pauses        turn     -> answer now? (drawn against p(finished) after Jev's suggested wait)
                           listen   -> a listening sound of some kind, or none
    both talk at once      floor    -> carry on / yield / finish the sentence / take the floor back / react
    the agent leads        cut_in   -> talk over the user now?
    quiet on the line      quiet    -> go on / check on them / wait / hang up

Work that takes longer than a breath runs in the background as a task (tasks.py) while the call carries on: the
responder starts it with a line of its own, what happens to it goes on the record, and its news is told in a quiet.
While a task is unfinished and nobody makes a sound the session sleeps: nothing is asked of Jev and nothing goes to the
recognizer until the user's voice, the task, or the client wakes it (`sleep`, `wake`).

Events to the client: line {id, text, audio}, listen {id, text, audio}, stop, finish_line, hangup,
user {text}, pace {pace, probs}, persona {id, name, gen}, decision {...}, task {id, kind, about, status, ...},
sleep {why}, wake {why}. Client messages: playback {state: playing | idle}, heard {gen, text}, sleep, wake.
"""
from __future__ import annotations

import asyncio
import random
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict

from . import speaking
from . import tasks as T
from .adapters.base import VAD, Recognizer, Responder, Segment
from .config import Config, Pace
from .decisions import DECISIONS, Decision
from .judge import JevClient
from .judge.client import probs as P
from .judge.state import Now
from .ledger import Ledger, Turn
from .profile import Profile
from .recorder import Recorder
from .utterance import Utterance, frame_db, is_far
from .voiceprint import Voiceprint

SYSTEM_TEMPLATE = (__import__("pathlib").Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")


class Session:
    def __init__(self, profile: Profile, *, send: Callable[[dict], Awaitable[None]], judge: JevClient, recognizer: Recognizer,
                 responder: Responder, vad: VAD, config: Config | None = None, recorder: Recorder | None = None,
                 system_template: str = SYSTEM_TEMPLATE, speech: str | None = None, cast: dict[str, Profile] | None = None,
                 embedder=None, sound=None, executors: dict[str, T.Executor] | None = None):
        self.p, self.cfg, self.send_event = profile, config or Config(), send
        self.judge, self.asr, self.llm, self.vad = judge, recognizer, responder, vad
        self.ledger = Ledger()                   # the call's one record, on one clock (ledger.py)
        self.rec = recorder or Recorder(None)
        if speech is None:                       # how to write for the voice in use: the synthesizer's speaking style
            from .adapters import registry
            speech = registry.speech_prompt()
        self.executors = dict(executors or {})   # kind -> who does that kind of background task (tasks.py)
        work = "\n\n" + T.prompt(self.executors) if self.executors else ""     # a call with no tasks reads the prompt as before
        self._system = lambda p: system_template.format(name=p.name, profile=p.prompt or p.task, speech=speech) + work
        self.system = self._system(profile)
        self.policies = {**Config().policies, **self.cfg.policies, **profile.policies}   # a task type may bring its own;
        # a Config(policies=...) written before a decision existed keeps that decision's default
        self.cast = dict(cast or {})             # id -> profile: everyone who can be on this line (Session.hand_over)
        self.decisions: dict[str, Decision] = dict(DECISIONS)       # asked in this order on new words and on each tick
        self.lines: dict[str, str] = {}          # line id -> text, fetched by the client from the TTS route
        self.replies: dict[int, Turn] = {}       # gen -> the agent's turn in the record, for the client's `heard`
        self.pace, self.pace_probs, self.transition = self.cfg.start_pace, {}, None
        self.user_turns = 0
        self.utt_seq = 0
        self.silence_ms = 0
        self.judged: dict | None = None          # the latest turn answer for the open utterance
        self.speaking = False                    # the client is playing a line of the agent's
        self.generating = False
        self.gen = 0
        self.idle_since = time.monotonic()
        self.rest_since = self.idle_since        # since the two last exchanged anything: what the sleep clock counts from.
                                                 # A line the agent says into a quiet on its own does not move it
        self.last_kind = ""                      # the kind of the agent's latest line (speaking.EVENTS)
        self.quiet_marks: list[float] = []
        self.spoke_into_quiet = 0
        self.listen_last = 0.0
        self.listen_gap = self.cfg.listen_gap_s  # to the next sound that could be left out; moved after each one
        self.caller_levels: list[float] = []   # loudness of the utterances answered as the caller's (Config.far_db)
        self.embedder = embedder                # speaker embeddings for the caller's voiceprint; None: no voiceprint
        self.voiceprint = Voiceprint(self.cfg.voice_same, self.cfg.voice_other, self.cfg.far_db or 10.0, self.cfg.voice_verdict_ms)
        self.sound = sound                       # "have they finished" from the voice (adapters/smart_turn.py); None: words alone
        self.audio_tail = bytearray()            # the last 8 s of the line from the user, pauses included, for the sound model
        self.heard_sound: tuple[int, int, float] | None = None   # (utterance id, ms of quiet it was scored at, p(finished))
        self._sound_busy = False
        self.hanging_up = False
        self.tasks: list[T.Task] = []            # every background task of the call, in the order they were started
        self._work: dict[int, tuple[asyncio.Task, T.Tell]] = {}   # the ones still going: what runs them, their line back
        self.asleep = False                      # a task is unfinished and the line has gone quiet: see `sleep`
        self.preroll = bytearray()               # asleep: the last of the audio, heard on waking
        self.wake_ms = 0                         # asleep: voice in a row so far
        self.woke = ""                           # what last woke it ("voice", "task", "client", "speak"); "" once words came
        self.busy: set[str] = set()              # decisions with a question out to Jev right now
        self._tasks: set[asyncio.Task] = set()
        self.closed = False

    # ------------------------------------------------------------------ lifecycle
    async def start(self, greet: bool = True):
        await self.asr.connect()
        self.ledger.started = time.monotonic()   # the call's clock starts when the line is up
        self._spawn(self._segments_loop())
        self._spawn(self._tick_loop())
        self._reset_quiet()
        if greet:
            await self.respond("pickup")

    async def close(self):
        self.closed = True
        self.gen += 1
        tasks = list(self._tasks)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.asr.close()
        if self.embedder is not None:
            self.voiceprint.clear()               # the caller's voice is kept for this call only
            self.rec.write("voice_cleared")
        self.rec.write("end", ledger=[t.__dict__ for t in self.ledger.turns], timeline=self.ledger.timeline())
        self.rec.close()

    def _spawn(self, coro):
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._task_done)
        return t

    def _task_done(self, t: asyncio.Task):
        self._tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            exc = t.exception()
            self.rec.write("task_error", error=f"{type(exc).__name__}: {str(exc)[:200]}")

    NOTED = ("decision", "pace", "persona", "stop", "finish_line", "hangup", "listen", "task", "sleep", "wake")   # what the engine did, as it is
                                                                                        # told to the client: kept in the record
    async def send(self, **event):
        self.rec.write("send", **event)
        if event.get("type") in self.NOTED:
            self.ledger.note(event["type"], **{k: v for k, v in event.items() if k not in ("type", "audio")})
        await self.send_event(event)

    # ------------------------------------------------------------------ inputs
    def _voice(self, pcm: bytes) -> tuple[bool, int]:
        """Is there voice in this frame, and how many ms of it."""
        if hasattr(self.vad, "voiced_ms"):       # how much of the frame is voice, the bar raised while the agent's line plays
            heard = self.vad.voiced_ms(pcm, self.speaking)
            return heard >= self.cfg.voice_min_ms, heard
        return self.vad.is_voice(pcm), self.cfg.frame_ms

    async def on_audio(self, pcm: bytes):
        if self.asleep:
            await self._doze(pcm)
            return
        await self.asr.send(pcm)
        step = self.cfg.frame_ms
        if self.sound is not None:
            self.audio_tail += pcm
            del self.audio_tail[:-self.SOUND_WINDOW]
        voiced, heard = self._voice(pcm)
        if voiced:
            if self.utt is None:
                self._open_utterance()
            elif self.silence_ms >= self.cfg.pause_mark_ms:     # their voice is back after a pause inside the turn
                self.utt.pauses.append((len(self.utt.segments), self.silence_ms / 1000))
            self.utt.ended = time.monotonic()
            self.utt.speech_ms += heard
            self.utt.levels.append(frame_db(pcm))
            self._hear_voice(pcm, heard)
            self.silence_ms = 0
            self.heard_sound = None               # the voice is back: the last reading of the pause no longer holds
            if self.speaking:
                self.utt.over_ms += heard         # only voice over the line counts, not what came before it
                self._over()
        elif self.utt is not None:
            self.silence_ms += step
            self._hear_pause()
            if not self.utt.heard and self.silence_ms >= self.cfg.sound_close_ms:
                self.utt = None                   # a sound and nothing after it: nobody's turn
                if self.woke == "voice" and not any(t.news for t in self.tasks):   # ... and it was what woke the
                    await self.sleep("no words")                                   # session: back to sleep, nothing asked

    async def on_client(self, msg: dict):
        if msg.get("type") == "playback":
            self.speaking = msg.get("state") == "playing"
            if not self.speaking:
                self.ledger.agent_ended(but=self.replies.get(self.gen) if self.generating else None)
            if not self.speaking and not self.generating:
                self.idle_since = time.monotonic()
                if self.last_kind not in self.UNPROMPTED:
                    self.rest_since = self.idle_since
                self._reset_quiet()
                if self.hanging_up:
                    await self.send(type="hangup")
        elif msg.get("type") == "sleep":          # the client puts it to sleep (a key, a click on the pet) ...
            await self.sleep("client")
        elif msg.get("type") == "wake":           # ... or wakes it
            await self.wake("client")
        elif msg.get("type") == "heard":
            heard = (msg.get("text") or "").strip()
            turn = self.replies.get(msg.get("gen"))
            if turn is not None:                  # the client names the reply: all of it that was played, "" for none
                self._cut(turn, heard)
            else:                                 # a client that sends no gen: the last reply, and only what it heard
                last = self.ledger.last_agent()
                if last and heard:
                    self._cut(last, heard)

    @staticmethod
    def _cut(turn, heard: str) -> None:
        """A reply the user heard only part of: the record keeps what they heard as its words and the rest as unheard.
        The client shows and measures the words without audio tags, so that is what is compared."""
        whole = speaking.plain(turn.text)
        if heard in (turn.text, whole):
            return
        turn.unheard = whole[len(heard):].strip() if whole.startswith(heard) else ""
        turn.text, turn.cut = heard, True

    async def _segments_loop(self):
        async for seg in self.asr.segments():
            await self.on_segment(seg)

    async def on_segment(self, seg: Segment):
        text = seg.text.strip()
        if not text:
            return
        if seg.final and any(re.search(rf"\b{re.escape(w)}\b", text, re.I) for w in self.cfg.safe_words):
            await self.safe_word(text)
            return
        if self.speaking and self._own_words(text):
            if seg.final:
                self.rec.write("echo", text=text)   # the agent's own line, back through the microphone: nobody said it
            return
        if not seg.final:                         # the words so far of a piece still being said: only an overlap uses them
            if self.utt is not None:
                self.utt.hearing = text
                self._over()
            return
        if self.utt is None:
            self._open_utterance()
            self.utt.speech_ms = max(self.utt.speech_ms, 400)
        self.woke = ""                            # words: whatever woke the session, it is a turn now
        self.rest_since = time.monotonic()
        self.utt.hearing = ""
        self.utt.segments.append((time.monotonic(), text))
        await self.send(type="user", text=self.utt.text, partial=True)
        for d in list(self.decisions.values()):
            d.on_words(self)                      # floor while the agent speaks; turn (and cut_in) while it is quiet

    def _over(self):
        """The user's voice has been going over the agent's line for a while (Config.overlap_ask_ms, and each time as
        much again) and words have been made out that the recognizer has not closed: they go to the floor question now.
        Nothing happens to the line until Jev answers; a sound without words asks nothing and the line plays on."""
        u = self.utt
        if (u is None or not self.speaking or not u.hearing or "floor" in self.busy
                or u.over_ms < max(u.over_ask_at, self.cfg.overlap_ask_ms)):
            return
        u.over_ask_at = u.over_ms + self.cfg.overlap_ask_ms
        self._spawn(self.ask("floor", gen=self.gen, early=True, closed=len(u.segments)))

    def _own_words(self, text: str) -> bool:
        """The recognizer heard words of the agent's own recent lines (a speaker next to the microphone)."""
        norm = lambda s: re.sub(r"[\W_]+", "", s).lower()  # noqa: E731
        heard = norm(text)
        return len(heard) >= 2 and any(heard in norm(line) for line in list(self.lines.values())[-6:])

    def _open_utterance(self):
        self.utt_seq += 1
        self.utt = Utterance(self.utt_seq, time.monotonic(), over=self.speaking)
        self.judged = None
        self.silence_ms = 0

    # ------------------------------------------------------------------ pace
    def params(self) -> Pace:
        """The current pace, with its timing blended across paces by Jev's probabilities (no jump at the argmax), as the
        persona on the line takes it (Profile.turn_taking: a persona handed the line brings its own)."""
        base = self.cfg.pace(self.pace)
        probs = {k: v for k, v in self.pace_probs.items() if v > 0 and any(p.name == k for p in self.cfg.paces)}
        if not probs or self.user_turns < self.cfg.opening_turns:
            return self.p.turn_taking.apply(base)
        tot = sum(probs.values())
        mix = lambda attr: sum(v / tot * getattr(self.cfg.pace(k), attr) for k, v in probs.items())  # noqa: E731
        return self.p.turn_taking.apply(Pace(base.name, base.description, max_wait_ms=int(mix("max_wait_ms")),
                                             yield_p=mix("yield_p"), leads=base.leads, cut_in=base.cut_in,
                                             lead_after_s=mix("lead_after_s")))

    async def _update_pace(self, probs: dict):
        self.pace_probs = probs
        if not probs:
            return
        choice = max(probs, key=probs.get)
        if choice != self.pace and self.user_turns >= self.cfg.opening_turns:
            self.transition = (self.pace, choice)
            self.pace = choice
            self.rec.write("pace", pace=choice, probs=probs)
            await self.send(type="pace", pace=choice, probs=probs)

    # ------------------------------------------------------------------ not said to me (tested knobs, off by default)
    def _offer_elsewhere(self) -> bool:
        return self.cfg.not_for_me and self.user_turns >= 1      # the call's first words are the caller's

    def _far(self) -> bool:
        """This voice is Config.far_db or more under the caller's answered words: someone farther from the phone."""
        return is_far(self.utt, self.caller_levels, self.cfg.far_db)

    def _someone_else(self) -> str | None:
        """Why this voice is not the caller's, or None: "far" (Config.far_db) or "voice" (the voiceprint says so)."""
        if self._far():
            return "far"
        if self.utt is not None and (self.utt.who or {}).get("label") == "other":
            return "voice"
        return None

    # ------------------------------------------------------------------ voiceprint
    VOICE_WINDOW = 4000 * 32                 # bytes of 16 kHz PCM16 kept per utterance: the last 4 s are embedded
    VOICE_EVERY_MS = 1000                    # judged again each time this much more voice has come

    def _hear_voice(self, pcm: bytes, heard: int) -> None:
        """Keep the utterance's voice and, once there is enough of it, ask the voiceprint who it is (off the loop)."""
        if self.embedder is None:
            return
        u = self.utt
        u.audio += pcm
        del u.audio[:-self.VOICE_WINDOW]
        before = u.speech_ms - heard
        mark = self.cfg.voice_verdict_ms
        if before < mark <= u.speech_ms or (u.speech_ms > mark and before // self.VOICE_EVERY_MS != u.speech_ms // self.VOICE_EVERY_MS):
            self._spawn(self._judge_voice(u))

    SOUND_WINDOW = 8 * 16000 * 2         # 8 s of 16 kHz PCM16: all the sound model hears

    def sound_ready(self) -> bool:
        return self.sound is not None and self.cfg.sound_rule != "off" and getattr(self.sound, "ready", True)

    def _hear_pause(self) -> None:
        """A frame of quiet after the user's words: the sound model reads the last 8 s (one reading at a time; a frame
        that comes while one is running is skipped, the next one is read). Each reading goes on the call's record."""
        u = self.utt
        if not self.sound_ready() or self._sound_busy or u is None or not u.segments or self.speaking:
            return
        self._sound_busy = True
        self._spawn(self._read_sound(u.id, self.silence_ms, bytes(self.audio_tail)))

    async def _read_sound(self, utt_id: int, quiet_ms: int, pcm: bytes) -> None:
        try:
            p = await asyncio.to_thread(self.sound.score, pcm)
        finally:
            self._sound_busy = False
        if p is None or self.utt is None or self.utt.id != utt_id or self.silence_ms < quiet_ms:
            return                                # the model is not ready, or the voice came back meanwhile
        self.heard_sound = (utt_id, quiet_ms, p)
        self.ledger.note("judge", purpose="sound", p=round(p, 3), quiet_ms=quiet_ms)

    def sound_p(self) -> float | None:
        """The latest reading of this pause, None when there is none yet."""
        h = self.heard_sound
        return h[2] if h and self.utt is not None and h[0] == self.utt.id else None

    async def _embed(self, u: Utterance):
        if self.embedder is None or not self.embedder.ready:
            return None
        return await asyncio.to_thread(self.embedder.embed, bytes(u.audio))

    async def _judge_voice(self, u: Utterance) -> None:
        emb = await self._embed(u)
        if emb is None:
            return
        who = self.voiceprint.judge(emb, u.level, u.speech_ms)
        u.who = {**who, "emb": emb}
        self.rec.write("voice", utt=u.id, **who)

    ENROLL_SECONDS_PER_PART = 4          # the voiced part of a sample is cut into pieces of about this long, 2 to 4 of them:
                                         # at least two, so a stranger can be told from the first words (voiceprint.MIN_ENROLL)

    async def enroll_sample(self, pcm: bytes, wait_s: float = 5.0) -> int:
        """A few seconds the caller says before the call (16 kHz PCM16, lines read aloud): the print starts from it. Only
        the frames with voice in them count (reading starts late and stops to breathe). Waits up to `wait_s` for a model
        still loading; without one the print is learned from the call as before. Returns the entries made. The audio is
        not kept: only the embeddings, in memory, until the call ends."""
        if self.embedder is None or not pcm:
            return 0
        waited = 0.0
        while not self.embedder.ready and waited < wait_s:
            await asyncio.sleep(0.2)
            waited += 0.2
        if not self.embedder.ready:
            return 0
        frame = self.cfg.sample_rate * 2 * self.cfg.frame_ms // 1000
        frames = [pcm[i:i + frame] for i in range(0, len(pcm) - frame + 1, frame)]
        if not frames:
            return 0
        dbs = [frame_db(f) for f in frames]
        loud = sorted(dbs)[len(dbs) // 2:]
        level = sum(loud) / len(loud)
        voiced = b"".join(f for f, d in zip(frames, dbs) if d >= max(level - 20.0, -55.0))
        seconds = len(voiced) / (self.cfg.sample_rate * 2)
        parts = max(2, min(4, int(seconds // self.ENROLL_SECONDS_PER_PART)))
        step = len(voiced) // parts // 2 * 2
        n = 0
        for k in range(parts):
            emb = await asyncio.to_thread(self.embedder.embed, voiced[k * step:(k + 1) * step])
            if emb is not None:
                self.voiceprint.add(-1 - k, emb, level)
                n += 1
        self.rec.write("voice_enroll", source="sample", n=len(self.voiceprint.entries), voiced_s=round(seconds, 1))
        return n

    async def _enroll(self, u: Utterance) -> None:
        """An answered utterance teaches the caller's print, unless it was judged someone else's."""
        if self.embedder is None or u.speech_ms < self.cfg.voice_enroll_ms or (u.who or {}).get("label") == "other":
            return
        emb = (u.who or {}).get("emb")
        if emb is None:
            emb = await self._embed(u)
        if emb is not None:
            self.voiceprint.add(u.id, emb, u.level)
            self.rec.write("voice_enroll", utt=u.id, n=len(self.voiceprint.entries))

    async def _not_for_me(self, why: str):
        """The words were someone else's: not answered, not added to the history; the line goes on."""
        text = self.utt.text if self.utt else ""
        self.rec.write("not_for_me", why=why, text=text, level=self.utt.level if self.utt else None)
        await self.send(type="decision", what="not_for_me", why=why, text=text)
        self.utt, self.judged = None, None

    # ------------------------------------------------------------------ judgements
    def now(self, quiet_s: float | None = None) -> Now:
        """The call at this instant, read off its record: the one account every question asked now is put to
        (judge/state.py). `quiet_s`: the quiet as the caller measured it, when it asks about a quiet of its own."""
        t = time.monotonic()
        u, last = self.utt, self.ledger.last_agent()
        gaps = sorted(self.ledger.reply_gaps())
        return Now(name=self.p.short, at=self.ledger.clock(t), agent_sounding=self.speaking or self.generating,
                   agent_line=last.text if last else "", user_open=u is not None,
                   segments=tuple((self.ledger.clock(at), words) for at, words in u.segments) if u else (),
                   heard=u.heard if u else "", asides=tuple(u.asides) if u else (), speech_ms=u.speech_ms if u else 0,
                   silence_ms=self.silence_ms if u else 0, quiet_s=t - self.idle_since if quiet_s is None else quiet_s,
                   spoke_into_quiet=self.spoke_into_quiet, usual_reply_s=gaps[len(gaps) // 2] if len(gaps) >= 2 else None)

    async def _ask(self, purpose: str, questions: dict, state: str | dict, now: Now | None = None) -> dict:
        """Jev's answers, or {} when the judge fails or is slow: every decision then takes its fallback (floor -> carry on,
        turn -> the pace's max wait, quiet -> nothing), so a judge error never freezes the call. The answer goes into
        the call's record with its probabilities (and into the log with the state it was given), so what was done with
        it can be worked out again later under other thresholds."""
        t = time.monotonic()
        try:
            answers = await asyncio.wait_for(self.judge.ask(questions, state), self.cfg.judge_timeout_s)
        except Exception as exc:  # noqa: BLE001
            self.rec.write("judge_error", purpose=purpose, error=f"{type(exc).__name__}: {str(exc)[:200]}")
            await self.send(type="error", what="judge", purpose=purpose, text=f"{type(exc).__name__}: {str(exc)[:120]}")
            return {}
        ms, given = int((time.monotonic() - t) * 1000), {k: P(answers, k) for k in questions}
        self.ledger.note("judge", purpose=purpose, asked=self.ledger.clock(t), ms=ms, answers=given)
        self.rec.write("judge", purpose=purpose, ms=ms, state=state, questions=questions, answers=given,
                       now=asdict(now) if now else None)
        return answers

    async def ask(self, name: str, **ctx):
        """Put one decision to Jev now and apply its answer (decisions/base.py: Decision.ask)."""
        await self.decisions[name].ask(self, **ctx)

    async def ask_turn(self, utt_id: int):
        await self.ask("turn", utt_id=utt_id)

    async def ask_floor(self, gen: int):
        await self.ask("floor", gen=gen)

    async def ask_cut_in(self, gen: int):
        await self.ask("cut_in", gen=gen)

    async def ask_quiet(self, quiet_s: float):
        await self.ask("quiet", quiet_s=quiet_s)

    # ------------------------------------------------------------------ the clock
    async def _tick_loop(self):
        while not self.closed:
            await asyncio.sleep(0.1)
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001 - one bad tick must not end the call
                self.rec.write("tick_error", error=f"{type(exc).__name__}: {exc}")

    async def tick(self):
        now = time.monotonic()
        if await self._tasks_tick(now):           # a task's news is being told, or the session is asleep
            return
        for d in list(self.decisions.values()):
            if await d.on_tick(self, now):        # it answered or dropped the words: the rest look again next tick
                break

    def _reset_quiet(self):
        j = self.cfg.quiet_jitter
        self.quiet_marks = [m * random.uniform(1 - j, 1 + j) for m in self.cfg.quiet_marks_s]

    # ------------------------------------------------------------------ background tasks (tasks.py)
    def open_tasks(self) -> list[T.Task]:
        """The tasks not finished yet: running, or waiting on the user."""
        return [t for t in self.tasks if t.open]

    def tasks_line(self) -> str:
        return T.line(self.tasks, self.ledger.clock())

    async def _task_event(self, task: T.Task, entry: bool = True) -> None:
        """Something happened to a task: on the record where it happened, in the log, and told to the client."""
        if entry:
            self.ledger.event(T.entry(task, self.cfg.task_result_chars))
        self.rec.write("task", **task.public(), result=task.result)
        await self.send(type="task", **task.public())

    async def start_task(self, kind: str, about: str, **given) -> T.Task | None:
        """Set a task going with the executor of that kind; the call carries on. None when there is no such kind (the
        record says so, and the responder reads it). `given` is for the executor (Task.given)."""
        executor = self.executors.get(kind)
        if executor is None or not about:
            kinds = ", ".join(self.executors) or "none"
            self.ledger.event(f"(no task was started: {kind or '?'} is not a kind of task on this call; the kinds: {kinds})"
                              if executor is None else "(no task was started: the /task line did not say what to do)")
            return None
        task = T.Task(len(self.tasks) + 1, kind, about, started=self.ledger.clock(), given=given)
        self.tasks.append(task)
        tell = T.Tell(self, task)
        self._work[task.id] = (self._spawn(self._run_task(task, executor, tell)), tell)
        await self._task_event(task)
        return task

    async def _run_task(self, task: T.Task, executor: T.Executor, tell: T.Tell) -> None:
        try:
            result = (await executor.run(task, tell) or "").strip()
            status = T.DONE if result else T.EMPTY
        except asyncio.CancelledError:
            raise                                 # stopped (stop_task), or the call ended
        except Exception as exc:  # noqa: BLE001 - whatever it was, the call is told the task failed
            result, status = f"{type(exc).__name__}: {str(exc)[:200]}", T.FAILED
        finally:
            self._work.pop(task.id, None)
        task.status, task.result, task.ended, task.question, task.news = status, result, self.ledger.clock(), "", True
        await self._task_event(task)
        await self.wake("task")

    async def _task_progress(self, task: T.Task, text: str) -> None:
        task.progress = " ".join((text or "").split())
        await self._task_event(task, entry=False)     # shown with the agent's next line; not an entry, nothing is said

    async def _task_asks(self, task: T.Task, question: str) -> None:
        task.status, task.question, task.news = T.WAITING, " ".join((question or "").split()), True
        await self._task_event(task)
        await self.wake("task")

    def _task_resumed(self, task: T.Task) -> None:
        """What a task asked the user is over: they answered, or it was answered elsewhere (on their own screen)."""
        if task.status != T.WAITING:
            return
        task.status, task.question, task.news = T.RUNNING, "", False
        if not self.closed:
            self._spawn(self._task_event(task, entry=False))

    async def tell_task(self, task_id: int, text: str) -> bool:
        """Words for a task that is going: the user's answer to what it asked, or more for it to work with (an executor
        that can take that has `steer`). False when it could not be passed on; the record says why."""
        task = next((t for t in self.tasks if t.id == task_id and t.open), None)
        work = self._work.get(task_id)
        if task is None or work is None:
            self.ledger.event(f"(nothing was passed on: no background task {task_id} is going)")
            return False
        if task.status == T.WAITING and work[1].answer(text):
            self._task_resumed(task)
            return True
        steer = getattr(self.executors.get(task.kind), "steer", None)
        if steer is None:
            self.ledger.event(f"(nothing was passed on: background task {task_id} takes no more words while it runs)")
            return False
        await steer(task, text)
        return True

    async def stop_task(self, task_id: int) -> bool:
        task = next((t for t in self.tasks if t.id == task_id and t.open), None)
        work = self._work.pop(task_id, None)
        if task is None or work is None:
            self.ledger.event(f"(nothing was stopped: no background task {task_id} is going)")
            return False
        work[0].cancel()
        task.status, task.ended, task.question, task.news = T.STOPPED, self.ledger.clock(), "", False
        await self._task_event(task)
        return True

    async def _act(self, text: str) -> None:
        """A line the responder wrote to start, steer or stop a task (tasks.action)."""
        verb, head, tail = T.action(text)
        self.rec.write("act", text=text)
        if verb == "task":
            await self.start_task(head, tail)
        elif not head.isdigit():
            self.ledger.event(f"(nothing was done: /{verb} needs the task's number)")
        elif verb == "tell":
            await self.tell_task(int(head), tail)
        else:
            await self.stop_task(int(head))

    async def _tasks_tick(self, now: float) -> bool:
        """Each tick, before any question is put to Jev. A task with news and nobody making a sound: the agent tells
        it. Asleep: nothing is asked. A task unfinished and the line quiet for Config.sleep_after_s: it goes to sleep."""
        if self.utt is not None or self.speaking or self.generating:
            return False                          # someone has the floor: the news rides with the next line, or waits
        quiet_s, rest_s = now - self.idle_since, now - self.rest_since
        if any(t.news for t in self.tasks) and (self.woke == "task" or quiet_s >= self.cfg.task_report_after_s):
            self.woke = ""
            self.generating = True                # taken now, so no question is asked about this quiet meanwhile
            self._spawn(self.respond("task_back"))
            return True
        if self.asleep:
            return True
        if self.cfg.sleep_after_s is not None and rest_s >= self.cfg.sleep_after_s and (self.open_tasks() or self.cfg.sleep_when_idle):
            await self.sleep("task" if self.open_tasks() else "quiet")
            return True
        return False

    # ------------------------------------------------------------------ sleep
    async def sleep(self, why: str = "task") -> bool:
        """Nothing to do but wait: no question goes to Jev and no audio to the recognizer until the user's voice
        (Config.wake_voice_ms of it), a task's news, or the client wakes the session. Not while anyone has the floor."""
        if self.asleep or self.closed or self.utt is not None or self.speaking or self.generating:
            return False
        self.asleep, self.wake_ms, self.woke = True, 0, ""
        self.preroll.clear()
        await self.send(type="sleep", why=why)
        return True

    async def wake(self, why: str) -> bool:
        if not self.asleep:
            return False
        self.asleep, self.woke = False, why
        if why != "task":                         # the quiet starts over from here; a task's news is told at once
            self.idle_since = self.rest_since = time.monotonic()
        self._reset_quiet()
        await self.send(type="wake", why=why)
        return True

    async def _doze(self, pcm: bytes) -> None:
        """A frame while asleep: kept for a moment, and listened to only for a voice. Enough of it in a row wakes the
        session, which then hears the kept audio as if it had been awake, so the first words are not lost."""
        self.preroll += pcm
        del self.preroll[:-(self.cfg.sample_rate * 2 * self.cfg.sleep_preroll_ms // 1000)]
        voiced, heard = self._voice(pcm)
        self.wake_ms = self.wake_ms + heard if voiced else 0
        if self.wake_ms < self.cfg.wake_voice_ms:
            return
        held, frame = bytes(self.preroll), self.cfg.sample_rate * 2 * self.cfg.frame_ms // 1000
        self.preroll.clear()
        await self.wake("voice")
        for i in range(0, len(held), frame):
            await self.on_audio(held[i:i + frame])

    # ------------------------------------------------------------------ speaking
    def data_line(self, kind: str, quiet_s: float = 0.0, listen: str = "", who: str = "") -> str:
        """The bracketed line the responder reads before it speaks (speaking.py has the wording for each kind)."""
        pace = self.pace + (f" (just changed from {self.transition[0]})" if self.transition else "")
        if kind != "listen":
            self.transition = None
        last = self.ledger.last_agent()
        event = speaking.event_text(kind, last=last.text if last else "", quiet_s=quiet_s, listen=listen, who=who)
        return speaking.data_line(pace, event, self.cfg.language, self.tasks_line())

    @property
    def rec(self) -> Recorder:
        return self._rec

    @rec.setter
    def rec(self, recorder: Recorder):
        """The call log, every line of it stamped with the call's clock."""
        self._rec = recorder
        recorder.clock = self.ledger.clock

    @property
    def utt(self) -> Utterance | None:
        """The user's turn in progress. It lives in the ledger, with the rest of the call (Ledger.open)."""
        return self.ledger.open

    @utt.setter
    def utt(self, value: Utterance | None):
        self.ledger.open = value

    def others(self) -> dict[str, Profile]:
        """Who else can be put on the line right now: the cast without the one on it."""
        return {pid: p for pid, p in self.cast.items() if p is not self.p}

    async def hand_over(self, pid: str):
        """The user asked for someone else in the cast. The one on the line says so in a few words; then the other is
        on it: their prompt for the responder, their manner for Jev, their policies, and (the transport's part, told by
        the `persona` event) their voice. The record stays one record and says who said what (ledger.py)."""
        new, old, gen = self.cast[pid], self.p, self.gen + 1
        await self.respond("hand_over", who=new.short)
        if self.gen != gen or self.closed:        # the user spoke over the goodbye: they are still talking to this one
            return
        self.p, self.system = new, self._system(new)
        self.policies = {**self.cfg.policies, **new.policies}
        self.pace, self.pace_probs, self.transition = self.cfg.start_pace, {}, None
        self.rec.write("persona", id=pid, name=new.name)
        await self.send(type="persona", id=pid, name=new.name, gen=self.gen + 1,
                        accent=(new.extra.get("display") or {}).get("accent"))
        await self.respond("take_over", who=old.short)

    UNPROMPTED = ("lead", "check", "hangup")      # lines the agent says into a quiet on its own

    async def respond(self, kind: str, quiet_s: float = 0.0, who: str = ""):
        self.gen += 1
        gen = self.gen
        self.generating = True
        self.last_kind = kind
        if self.asleep:
            await self.wake("speak")              # it never talks in its sleep
        news = [t for t in self.tasks if t.news]  # the tasks whose news this line is shown as not told yet
        line = self.data_line(kind, quiet_s, who=who)
        event = speaking.EVENTS.get(kind, speaking.UNKNOWN)
        if self.utt is not None and event.answers_user:
            if self.utt.level is not None:
                self.caller_levels = (self.caller_levels + [self.utt.level])[-20:]
            self._spawn(self._enroll(self.utt))
            text = self.utt.text
            self.ledger.close_open(self.p.short, line)
            await self.send(type="user", text=text, partial=False)
            self.user_turns += 1
            self.spoke_into_quiet = 0
            self.utt = None
            self.judged = None
        else:
            self.ledger.user("", line, who=self.p.short).at = self.ledger.clock()   # no words of theirs: the line she was given
        messages = [{"role": "system", "content": self.system}, *self.ledger.messages(self.p.short)]
        turn = self.ledger.agent("", who=self.p.short)
        self.replies[gen] = turn
        self.rec.write("respond", gen=gen, kind=kind, data_line=line)
        try:
            for attempt in (1, 2):                    # a reply that fails or comes back with nothing to say is asked for
                error = ""                            # once more: the user spoke and must not be met with silence
                try:
                    async for text in self.llm.lines(messages, max_tokens=event.max_tokens):
                        if gen != self.gen:
                            break
                        if T.action(text):                # a line that starts or steers a task: done, kept, not said
                            turn.acts.append(text)
                            await self._act(text)
                            continue
                        if not speaking.has_voice(text):  # a tag with no word or sound beside it cannot be voiced: not said
                            self.rec.write("unvoiced", gen=gen, text=text)
                            continue
                        line_id = uuid.uuid4().hex
                        self.lines[line_id] = text
                        turn.text = (turn.text + "\n" + text).strip()
                        self.speaking = True          # on its way to the client: counts as speaking until it reports idle
                        await self.send(type="line", gen=gen, id=line_id, text=text, audio=f"/tts/{line_id}")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - the provider refused, timed out or dropped the stream
                    error = f"{type(exc).__name__}: {str(exc)[:160]}"
                if turn.text or turn.acts or gen != self.gen:
                    break
                self.rec.write("no_reply", gen=gen, kind=kind, attempt=attempt, error=error)
                if attempt == 2:                      # twice nothing: the page is told, the quiet question takes it from here
                    await self.send(type="error", what="responder", text=error or "the model wrote nothing")
        finally:
            if turn.text:                             # a line went out with their news in front of it: told (a line
                for t in news:                        # cut off keeps what was not heard, as any line does)
                    t.news = False
            if gen == self.gen:
                self.generating = False
                if not turn.text:
                    self.speaking = False
                    self.idle_since = time.monotonic()
                    turn.end = self.ledger.clock()

    async def listen_in(self, why: str = "fits"):
        """What the agent lets slip in while the user talks on. Jev chose the moment (`why`: "due", the user is waiting
        for it, or "fits", it could as well be left out) and the event line says which; the words are the responder's,
        from the same record as every line, and may be none. Voiced beside the line queue and kept in the turn's record
        where it came, as the agent's own words."""
        utt = self.utt
        if utt is None or self.speaking or self.generating or time.monotonic() - self.listen_last < self.cfg.listen_min_gap_s:
            return                                # one at a time, never run together
        self.listen_last = time.monotonic()
        at, line = len(utt.segments), self.data_line("listen", listen=why)
        # the turn so far as it went: what was put in before is the agent's own turn, then the user's words since
        before, heard = self.ledger.open_messages()
        messages = [{"role": "system", "content": self.system}, *self.ledger.messages(self.p.short), *before,
                    {"role": "user", "content": (line + "\n" + heard).strip()}]
        text = ""
        async for said in self.llm.lines(messages, max_tokens=14):
            text = said
            break
        if (T.action(text) or not speaking.has_voice(text) or speaking.units(text) > self.cfg.listen_max_words or self.speaking
                or self.generating or self.utt is not utt):
            return
        line_id = uuid.uuid4().hex
        self.lines[line_id] = text
        utt.asides.append((at, text, line))
        j = self.cfg.listen_gap_jitter
        self.listen_gap = self.cfg.listen_gap_s * random.uniform(1 - j, 1 + j)
        await self.send(type="listen", id=line_id, text=text, kind=why, audio=f"/tts/{line_id}")

    async def _stop_line(self):
        self.gen += 1
        self.generating = self.speaking = False
        last = self.ledger.last_agent()
        if last:
            last.cut = True
        self.ledger.agent_ended()
        await self.send(type="stop", gen=self.gen)

    async def safe_word(self, text: str):
        await self._stop_line()
        self.utt = None
        self.pace = self.cfg.start_pace
        await self.respond("safe_word")
