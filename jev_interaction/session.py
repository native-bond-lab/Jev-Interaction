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
import difflib
import os
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

SAFE_SPLIT = re.compile(r"[,;，、]")


def configured_safe_words(cfg: Config) -> list[str]:
    """The words that stop everything with no judgement at all: JEV_SAFE_WORDS (comma-separated) when a deployment
    sets it, else the config's own. A word too long for the recognizer to close is no use, and neither is one the
    agent's own lines are full of."""
    words = [w.strip() for w in SAFE_SPLIT.split(os.getenv("JEV_SAFE_WORDS") or "") if w.strip()]
    return words or list(cfg.safe_words)


def says(text: str, word: str) -> bool:
    """Did they say that word? Chinese and Japanese have no spaces between words, so a word boundary is not asked of
    them: there the word is looked for as it is."""
    if not word:
        return False
    return re.search(rf"\b{re.escape(word)}\b", text, re.I) is not None if word.isascii() else word in text


QUIET_WORDS = ("安静点", "安静一会儿", "让我安静", "别说话", "先别说话", "别出声", "闭嘴", "别吵", "别吵我",
               "先别吵", "别打扰", "先别打扰", "别理我", "先别理我", "我在忙", "quiet", "be quiet", "shush")


def configured_quiet_words() -> list[str]:
    """The ways a user asks the agent to be quiet: JEV_QUIET_WORDS (comma-separated) when the deployment sets it."""
    words = [w.strip() for w in SAFE_SPLIT.split(os.getenv("JEV_QUIET_WORDS") or "") if w.strip()]
    return words or list(QUIET_WORDS)


def _minutes(name: str, default: float) -> float:
    """A number of minutes from the environment. A value that is not one (a typo in .env) must not stop a call."""
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return default


def detect_language(text: str) -> str | None:
    """Which language they are speaking, from the words themselves: kana, then Han characters, then Latin letters.
    None when there is too little to tell ("ok", "嗯"), so a short answer never flips the call."""
    if not text:
        return None
    kana = sum(1 for c in text if "\u3040" <= c <= "\u30ff")
    han = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if kana >= 2:
        return "ja"
    if han >= 2:
        return "zh"
    if latin >= 3:
        return "en"
    return None


HUSHED = {"zh": "好。", "en": "Okay.", "ja": "はい。", "ko": "네."}     # the one word a quiet order is always answered with
NO_WORDS = {"zh": "嗯？", "en": "Yes?", "ja": "はい？", "ko": "네?"}      # the model wrote nothing: something rather than silence
CALLED_BACK = {"zh": "在。", "en": "I'm here.", "ja": "はい。", "ko": "네."}
ACTS_SAID = {                                     # the work has started: say so, the answer comes later
    "task": {"zh": "稍等，我这就去问它。", "en": "One moment, I'm asking.", "ja": "少々お待ちを、聞いてきます。"},
    "tell": {"zh": "好，我传给它。", "en": "Right, passing that on.", "ja": "はい、伝えます。"},
    "stop": {"zh": "好，我让它停下。", "en": "Okay, stopping it.", "ja": "はい、止めます。"},
}


class Session:
    def __init__(self, profile: Profile, *, send: Callable[[dict], Awaitable[None]], judge: JevClient, recognizer: Recognizer,
                 responder: Responder, vad: VAD, config: Config | None = None, recorder: Recorder | None = None,
                 system_template: str = SYSTEM_TEMPLATE, speech: str | None = None, cast: dict[str, Profile] | None = None,
                 embedder=None, sound=None, executors: dict[str, T.Executor] | None = None):
        self.p, self.cfg, self.send_event = profile, config or Config(), send
        self.safe_words = configured_safe_words(self.cfg)
        self.quiet_words = configured_quiet_words()
        self.quiet_minutes = _minutes("JEV_QUIET_MINUTES", 15.0)
        self.quiet_until = 0.0                   # monotonic time until which nothing is said into a silence
        self.quiet_hint = False                   # their words named a way of asking for quiet: Jev confirms or not
        self.speak_language = self.cfg.language   # the language the call is answered in: follows the one they speak
        self.user_last = time.monotonic()         # when they last said something: the silence is counted from here
        self.lang_votes = 0                       # utterances in another language so far: two in a row switch the call
        self.beat = {"frames": 0, "voiced": 0, "words": 0, "asr_frames_sent": 0, "asr_restarts": 0,
                     "at": time.monotonic()}       # microphone and recognizer health, per 10 s
        self.voice_at = self.asr_at = self.asr_final_at = time.monotonic()   # voice, any result, last finished sentence
        self._asr_in = None                       # frames on their way to the recognizer, drained by their own task
        self._asr_task = None
        self.asr_restart_at = 0.0                 # when a fresh stream was last opened
        self.asr_restarting = False
        self.voice_run_ms = 0                     # continuous voiced time, for an occasional backchannel
        self.backchannel_cooldown_ms = 0
        self.backchannel_busy = False
        self.stopping = False                     # a hard stop is already on its way: one per burst, not one per frame
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
        self.speaking_until = 0.0                # when the lines already sent must be over by, however the client reports
        self.voice_since_result = 0.0            # ms of voice heard since the recognizer last produced anything
        self.played_until = 0.0                  # when the client last stopped playing one (the echo tail, _own_words)
        self.generating = False
        self.gen = 0
        self.idle_since = time.monotonic()
        self.rest_since = self.idle_since        # since the two last exchanged anything: what the sleep clock counts from.
                                                 # A line the agent says into a quiet on its own does not move it
        self.last_kind = ""                      # the kind of the agent's latest line (speaking.EVENTS)
        self.called_response: dict | None = None # short protection from residual voice around a called reply
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
        self.rec.write("asr", what="connected")
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
        if self._asr_task is not None:
            self._asr_task.cancel()
            done, _ = await asyncio.wait({self._asr_task}, timeout=2.0)
            if not done:
                self.rec.write("asr", what="audio feeder did not stop within 2 s")
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
        self._queue_audio(pcm)
        await self._hear_frame(pcm)

    def _queue_audio(self, pcm: bytes) -> None:
        """Hand the frame to the recognizer without ever waiting on it.

        This used to `await asr.send(pcm)` right here, inside the socket's read loop: a pushy recognizer socket stalled the
        loop, the client's sends stalled behind it, and the microphone went silent in bursts (heartbeats of 50, 3, 0)."""
        if self._asr_in is None:
            self._asr_in = asyncio.Queue(maxsize=400)
            self._asr_task = asyncio.create_task(self._feed_asr())
        if self._asr_in.full():
            try:
                self._asr_in.get_nowait()             # a frame behind: losing one is better than losing the read loop
            except asyncio.QueueEmpty:
                pass
        self._asr_in.put_nowait(pcm)

    async def _feed_asr(self) -> None:
        while True:
            try:
                pcm = await asyncio.wait_for(self._asr_in.get(), self.ASR_KEEPALIVE_S)
            except asyncio.TimeoutError:
                pcm = self._silence_frame()
                self.rec.write("asr", what="keepalive silence frame")
            try:
                await asyncio.wait_for(self.asr.send(pcm), self.ASR_SEND_TIMEOUT_S)
                self.asr_send_failed = False
                self.beat["asr_frames_sent"] = self.beat.get("asr_frames_sent", 0) + 1
            except Exception as exc:  # noqa: BLE001 - the recognizer is gone: the watchdog rebuilds it
                # 45000081 is the vendor closing the session after 8 s without audio; every later frame is refused. Waiting
                # the watchdog's full 12 s for that is twelve seconds of a deaf call, so the rebuild is asked for now.
                self.asr_needs_restart = True
                if not getattr(self, "asr_send_failed", False):
                    self.asr_send_failed = True
                    self.rec.write("asr", what=f"send failed: {type(exc).__name__}: {str(exc)[:80]}")

    def _silence_frame(self) -> bytes:
        size = self.cfg.sample_rate * 2 * self.cfg.frame_ms // 1000
        return b"\x00" * size

    async def _hear_frame(self, pcm: bytes) -> None:
        step = self.cfg.frame_ms
        if self.sound is not None:
            self.audio_tail += pcm
            del self.audio_tail[:-self.SOUND_WINDOW]
        voiced, heard = self._voice(pcm)
        self.beat["frames"] += 1
        self.beat["voiced"] += 1 if voiced else 0
        if voiced and not self.speaking:          # its own line through the microphone is not the user speaking
            self.voice_at = time.monotonic()
        if voiced:
            self.voice_since_result += heard          # one cough is not a reason to rebuild the recognizer
        if voiced and not self.speaking:
            self.voice_run_ms += heard
            self.backchannel_cooldown_ms = max(0, self.backchannel_cooldown_ms - heard)
        else:
            self.voice_run_ms = 0
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
            self._maybe_backchannel()
        elif self.utt is not None:
            self.silence_ms += step
            self._hear_pause()
            if not self.utt.heard and self.silence_ms >= self.cfg.sound_close_ms:
                self.utt = None                   # a sound and nothing after it: nobody's turn
                if self.woke == "voice" and not any(t.news for t in self.tasks):   # ... and it was what woke the
                    await self.sleep("no words")                                   # session: back to sleep, nothing asked

    async def on_client(self, msg: dict):
        if msg.get("type") == "playback":
            state = self.called_response
            if state is not None and state.get("gen") == self.gen:
                if msg.get("state") == "playing" and state.get("started_at") is None:
                    state["started_at"] = time.monotonic()
            if self.speaking and msg.get("state") != "playing":
                self.played_until = time.monotonic()  # the echo of the last line can still come back for a moment
            self.speaking = msg.get("state") == "playing"
            if not self.speaking:
                self.speaking_until = 0.0          # the client says the speakers are empty: nothing is owed
            if self.speaking:
                # Even the client's own "playing" gets a deadline: a player that reports playing and then wedges must not
                # hold the call for minutes.
                self.speaking_until = time.monotonic() + 20.0
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
        while not self.closed:
            try:
                async for seg in self.asr.segments():
                    await self.on_segment(seg)
                if self.closed or getattr(self.asr, "finished", False):
                    return
                if not getattr(self.asr, "error", None):
                    return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a replaced stream keeps the same consumer
                self.rec.write("asr", what=f"segment stream failed: {type(exc).__name__}: {str(exc)[:120]}")
            if not self.closed:
                await asyncio.sleep(0.1)

    async def on_segment(self, seg: Segment):
        text = seg.text.strip()
        if not text:
            return
        self.voice_since_result = 0.0             # the recognizer is producing: it is not a dead stream
        if seg.final and any(says(text, w) for w in self.safe_words):
            await self.safe_word(text)
            return
        if seg.final:                             # quiet mode: they asked for it, and they end it by talking to us again
            self.quiet_at_open_hint = self.quiet_mode()   # remembered before their words end the quiet
            self.quiet_at_open = self.quiet_at_open_hint   # VAD may have opened this utterance before its final words
            asked = any(says(text, w) for w in self.quiet_words)
            if asked and (self.speaking or self.generating):
                self.enter_quiet()                # no turn question will be asked over a line: the words are enough
            elif asked:
                self.quiet_hint = True            # the turn question carries Jev's confirmation (decisions/turn.py)
            elif self.quiet_mode():
                self.quiet_until = 0.0
            spoken = detect_language(text)   # the language of the call follows the one they are speaking
            if spoken == self.speak_language:
                self.lang_votes = 0
            elif spoken:                          # one English phrase used to flip a whole call: two in a row do it
                self.lang_votes = getattr(self, "lang_votes", 0) + 1
                if self.lang_votes >= 2:
                    self.speak_language, self.lang_votes = spoken, 0
                    self.ledger.event(f"(they are speaking {spoken}: the call answers in it)")
        if self._own_words(text):
            if seg.final:
                self.rec.write("echo", text=text)   # the agent's own line, back through the microphone: nobody said it
            return
        if not seg.final:                         # the words so far of a piece still being said: only an overlap uses them
            self.asr_at = time.monotonic()        # a partial result is the recognizer working: not a dead stream
            if self.utt is not None:
                self.utt.hearing = text
                self._over()
            return
        if self.utt is None:
            self._open_utterance()
            self.utt.speech_ms = max(self.utt.speech_ms, 400)
        self.woke = ""                            # words: whatever woke the session, it is a turn now
        self.rest_since = time.monotonic()
        self.user_last = time.monotonic()          # their own words: the idle clock that leads to silence starts here
        self.utt.hearing = ""
        if seg.revises and self.utt.segments:
            # The recognizer's snapshot grew: the same sentence, more words. Replacing it keeps the turn finite; appending
            # it meant the user never stopped talking and the agent never answered.
            self.utt.segments[-1] = (self.utt.segments[-1][0], text)
        else:
            self.utt.segments.append((time.monotonic(), text))
        self.asr_at = self.asr_final_at = time.monotonic()   # producing again — and a finished sentence: what the call needs
        self.beat["words"] = self.beat.get("words", 0) + 1
        self.user_pending, self.user_pending_at = True, time.monotonic()   # owed a line of the agent's
        await self.send(type="user", text=self.utt.text, partial=True)
        for d in list(self.decisions.values()):
            d.on_words(self)                      # floor while the agent speaks; turn (and cut_in) while it is quiet

    def _over(self):
        """The user's voice has been going over the agent's line for a while (Config.overlap_ask_ms, and each time as
        much again) and words have been made out that the recognizer has not closed: they go to the floor question now.
        Nothing happens to the line until Jev answers; a sound without words asks nothing and the line plays on."""
        u = self.utt
        if self._called_floor_protected():
            return
        if u is not None and self.speaking and not self.stopping and u.over_ms >= self.cfg.barge_stop_ms:
            self.rec.write("barge_in", over_ms=u.over_ms, gen=self.gen)    # the judge could not say it in time, or at all
            self.stopping = True                  # one stop per burst: every voiced frame would otherwise spawn one
            self._spawn(self._stop_line())
            return
        if (u is None or not self.speaking or "floor" in self.busy
                or u.over_ms < max(u.over_ask_at, self.cfg.overlap_ask_ms)):
            return
        u.over_ask_at = u.over_ms + self.cfg.overlap_ask_ms
        self._spawn(self.ask("floor", gen=self.gen, early=True, closed=len(u.segments)))

    CALLED_PREPLAY_S = 3.0
    CALLED_PLAYBACK_GUARD_S = 0.5

    def _called_floor_protected(self) -> bool:
        """Ignore residual overlap only around a called reply; protection expires if audio never starts."""
        state = self.called_response
        if state is None or state.get("gen") != self.gen:
            return False
        now = time.monotonic()
        started = state.get("started_at")
        if started is not None:
            return now - started < self.CALLED_PLAYBACK_GUARD_S
        return now < state.get("preplay_until", 0.0)

    def _own_words(self, text: str) -> bool:
        """The recognizer heard words of the agent's own recent lines (a speaker next to the microphone): while a line
        plays, and for Config.echo_tail_s after (the recognizer closes a segment a moment after the sound), then only
        a longer piece, so a short "ok" of the user's own is not taken for an echo. Recognizers mishear an echo too: it
        is the agent's when most of what was heard runs in order through one of its lines."""
        since = time.monotonic() - self.played_until
        if not self.speaking and since >= self.cfg.echo_tail_s:
            return False
        norm = lambda s: re.sub(r"\[[^\]]*\]|[\W_]+", "", s).lower()  # noqa: E731 - audio tags are never heard
        heard = norm(text)
        if len(heard) < (2 if self.speaking else 4):
            return False
        for line in list(self.lines.values())[-6:]:
            said = norm(line)
            if heard in said:
                return True
            blocks = difflib.SequenceMatcher(None, heard, said, autojunk=False).get_matching_blocks()
            if sum(b.size for b in blocks) >= self.cfg.echo_same * len(heard):
                return True
        return False

    def _open_utterance(self):
        self.utt_seq += 1
        self.utt = Utterance(self.utt_seq, time.monotonic(), over=self.speaking)
        self.judged = None
        self.silence_ms = 0
        self.quiet_at_open = getattr(self, "quiet_at_open_hint", False)   # silent under an order: they are back

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

    ASK_PER_CALL = 16        # a judge takes this many questions in one request (Bailian: "questions: 17 exceeds 16")

    async def _ask(self, purpose: str, questions: dict, state: str | dict, now: Now | None = None) -> dict:
        """Jev's answers, or {} when the judge fails or is slow: every decision then takes its fallback (floor -> carry on,
        turn -> the pace's max wait, quiet -> nothing), so a judge error never freezes the call. The answer goes into
        the call's record with its probabilities (and into the log with the state it was given), so what was done with
        it can be worked out again later under other thresholds.

        A decision that asks more questions than the judge takes in one request has them asked in parts and put back
        together: adding a question must never cost a decision all of its answers."""
        if len(questions) > self.ASK_PER_CALL:
            out: dict = {}
            items = list(questions.items())
            for i in range(0, len(items), self.ASK_PER_CALL):
                out.update(await self._ask(purpose, dict(items[i:i + self.ASK_PER_CALL]), state, now))
            return out
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

    ASR_KEEPALIVE_S = 2.0                   # send a quiet frame before Doubao closes a stream after an audio gap
    ASR_SEND_TIMEOUT_S = 2.0                 # a stuck send must not hold the independent audio feeder
    ASR_DEAD_S = 12.0                        # no result for 12 s while the user was recently heard: no progress at all
    ASR_NO_FINAL_S = 60.0                    # partials but no final for 60 s while recently heard: no closed turn
    ASR_VOICE_MS = 2000.0                    # voice that must pile up before "no result" means a dead stream
    ASR_COOLDOWN_S = 20.0                    # ordinary restarts are 20 s apart; a refused frame uses 2 s

    def _asr_watch(self, now: float) -> None:
        """The streaming recognizer can stop returning results with the socket open and no error; the call then hears
        nothing at all. It restarts after 12 s without any result or 60 s without a final, only when voice was heard in
        the last 10 s; ordinary restarts are separated by 20 s, while a refused frame uses a 2 s cooldown."""
        starved = now - self.asr_at >= self.ASR_DEAD_S
        no_final = now - getattr(self, "asr_final_at", 0.0) >= self.ASR_NO_FINAL_S
        # Silence is not a stall: while nobody talks the recognizer rightly says nothing. Only a stream that stays
        # silent through two seconds of real voice is dead — one cough used to be enough, and that rebuilt the
        # recognizer seven times in one call, throwing away whatever was being said each time.
        speaking_well = getattr(self, "voice_since_result", 0.0) >= self.ASR_VOICE_MS
        # A frame the recognizer refused means its session is closed (the vendor ends it after 8 s without audio):
        # waiting the full dead time for that is a deaf call, so a refusal asks for the rebuild at once.
        refused = getattr(self, "asr_needs_restart", False)
        if (self.closed or self.asr_restarting or not hasattr(self.asr, "restart")
                or not ((starved and speaking_well) or no_final or refused)
                or (not refused and now - self.voice_at > 10.0)
                or now - self.asr_restart_at < (2.0 if refused else self.ASR_COOLDOWN_S)):
            return
        self.asr_needs_restart = False
        self.asr_restarting = True
        self.asr_restart_at = now
        self.beat["asr_restarts"] = self.beat.get("asr_restarts", 0) + 1
        why = ("the recognizer refused the audio" if refused
               else f"no finished sentence for {self.ASR_NO_FINAL_S:.0f} s" if no_final
               else f"no result for {self.ASR_DEAD_S:.0f} s")
        dropped = getattr(getattr(self.asr, "utterances", None), "dropped", 0)
        self.rec.write("asr", what=f"{why} while a voice was heard (watermark drops: {dropped}): opening a fresh stream")

        async def rebuild():
            try:
                await self.asr.restart()
                # connect() swallows its own failure into .error, so "open" alone would be a lie
                error = getattr(self.asr, "error", None)
                if error is not None:
                    self.rec.write("asr", what=f"the fresh stream did not connect: {error}")
                else:
                    self.rec.write("asr", what="fresh stream open")
            except Exception as exc:  # noqa: BLE001 - the call goes on; the cooldown keeps it from spinning
                self.rec.write("asr", what=f"the fresh stream failed: {type(exc).__name__}: {exc}")
            finally:
                self.asr_restarting = False

        self._spawn(rebuild())

    async def tick(self):
        now = time.monotonic()
        self._asr_watch(now)
        if self.speaking and now > getattr(self, "speaking_until", 0.0):
            # The client never reported the line finished. Its own length said it must be over by now, so it is: this is
            # what kept the call believing it was talking for minutes (no answers, no initiative, until a restart).
            self.speaking = False
            self.rec.write("playback", what="no report from the client: the line is taken as finished")
        if now - self.beat["at"] >= 10.0:          # what the microphone gave the call, for whoever reads the log later
            self.rec.write("audio", frames=self.beat["frames"], voiced=self.beat["voiced"],
                           asr_words=self.beat.get("words", 0),   # segments closed in this window, not the open one
                           asr_frames_sent=self.beat.get("asr_frames_sent", 0),
                           asr_restarts=self.beat.get("asr_restarts", 0),
                           user_silent_s=round(now - self.user_last, 1),
                           speaking=self.speaking, generating=self.generating)   # so a stuck call is visible in the log
            self.beat = {"frames": 0, "voiced": 0, "words": 0, "asr_frames_sent": 0, "asr_restarts": 0, "at": now}
        if await self._tasks_tick(now):           # a task's news is being told, or the session is asleep
            return
        for d in list(self.decisions.values()):
            if await d.on_tick(self, now):        # it answered or dropped the words: the rest look again next tick
                break

    def _reset_quiet(self):
        j = self.cfg.quiet_jitter
        self.quiet_marks = [m * random.uniform(1 - j, 1 + j) for m in self.cfg.quiet_marks_s]

    def user_idle_s(self, now: float | None = None) -> float:
        """Seconds since they last said anything: the clock that turns a companion into a silent one."""
        return (now if now is not None else time.monotonic()) - self.user_last

    def quiet_mode(self) -> bool:
        """They asked for quiet a moment ago: nothing is said into a silence until they speak to us again."""
        return time.monotonic() < self.quiet_until

    def enter_quiet(self) -> None:
        """The silence is theirs from now on: said in so many words (`JEV_QUIET_WORDS`), or read from what they said by
        Jev (decisions/turn.py, JEV_QUIET_ASK_MIN). With JEV_QUIET_MINUTES=0 there is no clock on it at all."""
        self.quiet_until = float("inf") if self.quiet_minutes <= 0 else time.monotonic() + self.quiet_minutes * 60
        self.ledger.event("(they asked for quiet: nothing is said into the silence until they speak again)")

    # ------------------------------------------------------------------ background tasks (tasks.py)
    def open_tasks(self) -> list[T.Task]:
        """The tasks not finished yet: running, or waiting on the user."""
        return [t for t in self.tasks if t.open]

    def tasks_line(self, news: bool = True) -> str:
        """`news`: whether the tasks whose result is not told yet are listed. An ordinary reply leaves them out: only the
        report line (`task_back`) carries the result, and only it clears the news."""
        return T.line(self.tasks, self.ledger.clock(), news=news)

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
        elif verb == "reported":
            turn = self.replies.get(self.gen)
            if turn is None or not speaking.has_voice(turn.text):
                self.rec.write("task", what="result report ignored without spoken line", id=int(head))
                return
            task = next((t for t in self.tasks if t.id == int(head) and t.news and t.status != T.RUNNING), None)
            if task is not None:
                task.news = False
                self.rec.write("task", what="result reported aloud", id=task.id)
        else:
            await self.stop_task(int(head))

    async def _tasks_tick(self, now: float) -> bool:
        """Each tick, before any question is put to Jev. A task with news and nobody making a sound: the agent tells
        it. Asleep: nothing is asked. A task unfinished and the line quiet for Config.sleep_after_s: it goes to sleep."""
        if self.utt is not None or self.speaking or self.generating:
            return False                          # someone has the floor: the news rides with the next line, or waits
        # the silence is the longer of: since the last exchange, and since their own last words (a line of its own
        # into the quiet does not reset the second one — that is what keeps a monologue from going on forever)
        quiet_s, rest_s = now - self.idle_since, max(now - self.rest_since, self.user_idle_s(now))
        waiting = (getattr(self, "user_pending", False)
                   and now - getattr(self, "user_pending_at", 0.0) < 15.0)   # an answer is owed, but not forever
        if (any(t.news for t in self.tasks) and not self.quiet_mode() and not waiting
                and (self.woke == "task" or quiet_s >= self.cfg.task_report_after_s)):
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
        self._queue_audio(pcm)                    # the recognizer ends a session after 8 s without audio: keep feeding it
        self.preroll += pcm                        # even asleep, or the wake-up replay finds it dead
        del self.preroll[:-(self.cfg.sample_rate * 2 * self.cfg.sleep_preroll_ms // 1000)]
        voiced, heard = self._voice(pcm)
        self.wake_ms = self.wake_ms + heard if voiced else 0
        if self.wake_ms < self.cfg.wake_voice_ms:
            return
        self.preroll.clear()
        await self.wake("voice")                  # the audio already went to the recognizer as it arrived, so the words
        if self.utt is None:                      # of the wake-up arrive by themselves; their turn starts here
            self._open_utterance()

    # ------------------------------------------------------------------ speaking
    def data_line(self, kind: str, quiet_s: float = 0.0, listen: str = "", who: str = "", news: bool = False) -> str:
        """The bracketed line the responder reads before it speaks (speaking.py has the wording for each kind)."""
        pace = self.pace + (f" (just changed from {self.transition[0]})" if self.transition else "")
        if kind != "listen":
            self.transition = None
        last = self.ledger.last_agent()
        event = speaking.event_text(kind, last=last.text if last else "", quiet_s=quiet_s, listen=listen, who=who)
        return speaking.data_line(pace, event, self.speak_language, self.tasks_line(news=news))

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
        self.called_response = ({"gen": gen, "started_at": None,
                                 "preplay_until": time.monotonic() + self.CALLED_PREPLAY_S}
                                if kind == "called" else None)
        if self.asleep:
            await self.wake("speak")              # it never talks in its sleep
        news = [t for t in self.tasks if t.news]  # the tasks whose news this line is shown as not told yet
        line = self.data_line(kind, quiet_s, who=who, news=(kind == "task_back"))
        event = speaking.EVENTS.get(kind, speaking.UNKNOWN)
        if self.utt is not None and event.answers_user:
            if self.utt.level is not None:
                self.caller_levels = (self.caller_levels + [self.utt.level])[-20:]
            self._spawn(self._enroll(self.utt))
            text = self.utt.text
            self.ledger.close_open(self.p.short, line)
            await self.send(type="user", text=text, partial=False)
            self.user_turns += 1
            self.user_pending = False             # this line is the answer to what they said
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
            for attempt, ev in ((1, event), (2, speaking.EVENTS["spoke"])):   # a reply that comes back with nothing is
                error = ""                            # asked for once more with room to speak: a 24-token `hushed`
                try:                                  # line can genuinely be empty, and silence is worse
                    async for text in self.llm.lines(messages, max_tokens=ev.max_tokens):
                        if gen != self.gen:
                            break
                        if T.action(text):                # a line that starts or steers a task: done, kept, not said
                            act = T.written(text)
                            if act not in turn.acts:      # (written twice in one reply, it is still one thing to do)
                                turn.acts.append(act)
                                await self._act(act)
                            continue
                        text = speaking.unmarked(text)    # markup is never spoken
                        if not speaking.has_voice(text):  # a tag with no word or sound beside it cannot be voiced: not said
                            self.rec.write("unvoiced", gen=gen, text=text)
                            continue
                        line_id = uuid.uuid4().hex
                        self.lines[line_id] = text
                        turn.text = (turn.text + "\n" + text).strip()
                        # On its way to the client: counts as speaking until it reports idle — or until the line's own
                        # length says it must be over. Without the deadline one missed report left the call believing it
                        # was talking for minutes: no answers, no initiative, until a restart.
                        self.speaking = True
                        # What is still to be played counts too: a reply of three lines sent at once used to be given
                        # only the last line's time, so the fallback ended "speaking" while the audio was still going
                        # and the user's ordinary reply was taken for an interruption.
                        self.speaking_until = (max(self.speaking_until, time.monotonic())
                                               + max(4.0, len(text) * 0.3) + 2.5)
                        if kind == "called" and self.called_response and self.called_response["gen"] == gen:
                            self.called_response["preplay_until"] = time.monotonic() + self.CALLED_PREPLAY_S
                        await self.send(type="line", gen=gen, id=line_id, text=text, audio=f"/tts/{line_id}")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - the provider refused, timed out or dropped the stream
                    error = f"{type(exc).__name__}: {str(exc)[:160]}"
                if turn.text or turn.acts or gen != self.gen:
                    break
                self.rec.write("no_reply", gen=gen, kind=kind, attempt=attempt, error=error)
                if attempt == 2:                      # twice nothing: the page is told, the quiet question takes it from here
                    if kind in ("hushed", "spoke", "called", "check", "listen"):
                        # being told to be quiet, or simply being spoken to, is answered even if the model writes nothing:
                        # silence is worse than one word
                        table = HUSHED if kind == "hushed" else CALLED_BACK if kind == "called" else NO_WORDS
                        await self._say(table, gen, turn)
                        break
                    # a report that wrote nothing keeps its news: the next quiet brings it up again, result and all
                    await self.send(type="error", what="responder", text=error or "the model wrote nothing")
        finally:
            self.user_pending = False                 # whatever they were owed, this reply settles it
            actions = [act for act in turn.acts if not act.startswith("/reported ")]
            if not turn.text and actions:             # only a work action came back (`/task …`): explain that it started
                verb = actions[0].split(" ", 1)[0].lstrip("/")     # the answer is not going to come for a while
                await self._say(ACTS_SAID.get(verb, ACTS_SAID["task"]), gen, turn)
            if turn.text and kind == "task_back":     # the report line is the one that carries their news; any other
                for t in news:                        # reply would only mention it, and the result would be lost
                    t.news = False
            if gen == self.gen:
                self.generating = False
                if not turn.text:
                    self.speaking = False
                    self.idle_since = time.monotonic()
                    turn.end = self.ledger.clock()

    async def _say(self, table: dict, gen: int, turn) -> None:
        """Put one short canned line on the wire, in the language of the call, and count it as the turn's line."""
        if gen != self.gen:                      # the line was stopped while this was being written: nothing to say
            return
        text = table.get((self.speak_language or "en")[:2], table["en"])
        line_id = uuid.uuid4().hex
        self.lines[line_id] = text
        turn.text, self.speaking = text, True
        self.speaking_until = (max(self.speaking_until, time.monotonic())
                               + max(4.0, len(text) * 0.3) + 2.5)
        if self.last_kind == "called" and self.called_response and self.called_response["gen"] == gen:
            self.called_response["preplay_until"] = time.monotonic() + self.CALLED_PREPLAY_S
        await self.send(type="line", gen=gen, id=line_id, text=text, audio=f"/tts/{line_id}")

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
        text = speaking.unmarked(text)
        if (T.action(text) or not speaking.has_voice(text) or speaking.units(text) > self.cfg.listen_max_words or self.speaking
                or self.generating or self.utt is not utt):
            return
        line_id = uuid.uuid4().hex
        self.lines[line_id] = text
        utt.asides.append((at, text, line))
        j = self.cfg.listen_gap_jitter
        self.listen_gap = self.cfg.listen_gap_s * random.uniform(1 - j, 1 + j)
        await self.send(type="listen", id=line_id, text=text, kind=why, audio=f"/tts/{line_id}")

    def _maybe_backchannel(self) -> None:
        """Let one brief reaction in after two continuous seconds of voice, no more often than every five seconds."""
        if (self.voice_run_ms < 2000 or self.speaking or self.generating or self.asleep or self.backchannel_busy
                or self._someone_else() or (self.embedder is not None and self.utt and self.utt.who is None)
                or self.backchannel_cooldown_ms > 0):
            return
        self.backchannel_cooldown_ms = 5000
        self.backchannel_busy = True
        self._spawn(self._backchannel())

    async def _backchannel(self) -> None:
        try:
            await asyncio.wait_for(self.listen_in("fits"), 3.0)
        except asyncio.TimeoutError:
            self.rec.write("listen", what="long-speech backchannel timed out")
        except Exception as exc:  # noqa: BLE001 - a failed aside must not interrupt the caller
            self.rec.write("listen", what=f"long-speech backchannel failed: {type(exc).__name__}: {str(exc)[:120]}")
        finally:
            self.backchannel_busy = False

    async def _stop_line(self):
        self.gen += 1
        self.generating = self.speaking = False
        last = self.ledger.last_agent()
        if last:
            last.cut = True
        self.ledger.agent_ended()
        await self.send(type="stop", gen=self.gen)
        self.stopping = False                     # ready for the next burst

    async def safe_word(self, text: str):
        await self._stop_line()
        self.utt = None
        self.pace = self.cfg.start_pace
        await self.respond("safe_word")
