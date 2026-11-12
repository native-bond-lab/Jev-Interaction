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

Events to the client: line {id, text, audio}, listen {id, text, audio}, hold, unhold, stop, finish_line, hangup,
user {text}, pace {pace, probs}, decision {...}. Client messages: playback {state: playing | idle}, heard {text}.
"""
from __future__ import annotations

import asyncio
import random
import re
import time
import uuid
from typing import Awaitable, Callable

from . import speaking
from .adapters.base import VAD, Recognizer, Responder, Segment
from .config import Config, Pace
from .decisions import DECISIONS, Decision
from .judge import JevClient
from .judge.client import probs as P
from .ledger import Ledger
from .profile import Profile
from .recorder import Recorder
from .utterance import Utterance, frame_db, is_far

SYSTEM_TEMPLATE = (__import__("pathlib").Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")


class Session:
    def __init__(self, profile: Profile, *, send: Callable[[dict], Awaitable[None]], judge: JevClient, recognizer: Recognizer,
                 responder: Responder, vad: VAD, config: Config | None = None, recorder: Recorder | None = None,
                 system_template: str = SYSTEM_TEMPLATE):
        self.p, self.cfg, self.send_event = profile, config or Config(), send
        self.judge, self.asr, self.llm, self.vad = judge, recognizer, responder, vad
        self.rec = recorder or Recorder(None)
        self.system = system_template.format(name=profile.name, profile=profile.prompt or profile.task)
        self.policies = {**self.cfg.policies, **profile.policies}   # a task type may bring its own policies
        self.decisions: dict[str, Decision] = dict(DECISIONS)       # asked in this order on new words and on each tick
        self.ledger = Ledger()
        self.lines: dict[str, str] = {}          # line id -> text, fetched by the client from the TTS route
        self.pace, self.pace_probs, self.transition = self.cfg.start_pace, {}, None
        self.user_turns = 0
        self.utt: Utterance | None = None
        self.utt_seq = 0
        self.silence_ms = 0
        self.judged: dict | None = None          # the latest turn answer for the open utterance
        self.speaking = False                    # the client is playing a line of the agent's
        self.generating = False
        self.gen = 0
        self.held = False
        self.idle_since = time.monotonic()
        self.quiet_marks: list[float] = []
        self.spoke_into_quiet = 0
        self.listen_last = 0.0
        self.reply_gaps: list[float] = []
        self.caller_levels: list[float] = []   # loudness of the utterances answered as the caller's (Config.far_db)
        self.hanging_up = False
        self.busy: set[str] = set()              # decisions with a question out to Jev right now
        self._tasks: set[asyncio.Task] = set()
        self.closed = False

    # ------------------------------------------------------------------ lifecycle
    async def start(self, greet: bool = True):
        await self.asr.connect()
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
        self.rec.write("end", ledger=[t.__dict__ for t in self.ledger.turns])
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

    async def send(self, **event):
        self.rec.write("send", **event)
        await self.send_event(event)

    # ------------------------------------------------------------------ inputs
    async def on_audio(self, pcm: bytes):
        await self.asr.send(pcm)
        voiced = self.vad.is_voice(pcm)
        step = self.cfg.frame_ms
        if voiced:
            if self.utt is None:
                self._open_utterance()
            self.utt.speech_ms += step
            self.utt.levels.append(frame_db(pcm))
            self.silence_ms = 0
            if self.speaking and not self.held and self.utt.speech_ms >= self.cfg.hold_after_ms:
                self.held = True                  # the user comes first: the agent's audio pauses until the words decide
                await self.send(type="hold", gen=self.gen)
        elif self.utt is not None:
            self.silence_ms += step
            if self.held and not self.utt.segments and self.silence_ms >= self.cfg.hold_release_ms:
                self.held = False                 # a breath or a laugh over the line, no words: the line goes on
                await self.send(type="unhold", gen=self.gen)
                self.utt = None

    async def on_client(self, msg: dict):
        if msg.get("type") == "playback":
            self.speaking = msg.get("state") == "playing"
            if not self.speaking and not self.generating:
                self.idle_since = time.monotonic()
                self._reset_quiet()
                if self.hanging_up:
                    await self.send(type="hangup")
        elif msg.get("type") == "heard":
            last = self.ledger.last_agent()
            heard = (msg.get("text") or "").strip()
            if last and heard and heard != last.text:
                last.text, last.cut = heard, True

    async def _segments_loop(self):
        async for seg in self.asr.segments():
            await self.on_segment(seg)

    async def on_segment(self, seg: Segment):
        text = seg.text.strip()
        if not text:
            return
        if any(re.search(rf"\b{re.escape(w)}\b", text, re.I) for w in self.cfg.safe_words):
            await self.safe_word(text)
            return
        if self.utt is None:
            self._open_utterance()
            self.utt.speech_ms = max(self.utt.speech_ms, 400)
        self.utt.segments.append((time.monotonic(), text))
        await self.send(type="user", text=self.utt.text, partial=True)
        for d in list(self.decisions.values()):
            d.on_words(self)                      # floor while the agent speaks; turn (and cut_in) while it is quiet

    def _open_utterance(self):
        now = time.monotonic()
        if not self.speaking and not self.generating and self.ledger.last_is_agent() and 0 < now - self.idle_since < 60:
            self.reply_gaps = (self.reply_gaps + [now - self.idle_since])[-20:]
        self.utt_seq += 1
        self.utt = Utterance(self.utt_seq, now, over=self.speaking)
        self.judged = None
        self.silence_ms = 0

    # ------------------------------------------------------------------ pace
    def params(self) -> Pace:
        """The current pace, with its timing blended across paces by Jev's probabilities (no jump at the argmax)."""
        base = self.cfg.pace(self.pace)
        probs = {k: v for k, v in self.pace_probs.items() if v > 0 and any(p.name == k for p in self.cfg.paces)}
        if not probs or self.user_turns < self.cfg.opening_turns:
            return base
        tot = sum(probs.values())
        mix = lambda attr: sum(v / tot * getattr(self.cfg.pace(k), attr) for k, v in probs.items())  # noqa: E731
        return Pace(base.name, base.description, max_wait_ms=int(mix("max_wait_ms")), yield_p=mix("yield_p"),
                    leads=base.leads, cut_in=base.cut_in)

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

    async def _not_for_me(self, why: str):
        """The words were someone else's: not answered, not added to the history; the line goes on."""
        text = self.utt.text if self.utt else ""
        self.rec.write("not_for_me", why=why, text=text, level=self.utt.level if self.utt else None)
        await self.send(type="decision", what="not_for_me", why=why, text=text)
        if self.held:
            self.held = False
            await self.send(type="unhold", gen=self.gen)
        self.utt, self.judged = None, None

    # ------------------------------------------------------------------ judgements
    async def _ask(self, purpose: str, questions: dict, state: str) -> dict:
        """Jev's answers, or {} when the judge fails or is slow: every decision then takes its fallback (floor -> carry on,
        turn -> the pace's max wait, quiet -> nothing), so a judge error never freezes the call."""
        t = time.monotonic()
        try:
            answers = await asyncio.wait_for(self.judge.ask(questions, state), self.cfg.judge_timeout_s)
        except Exception as exc:  # noqa: BLE001
            self.rec.write("judge_error", purpose=purpose, error=f"{type(exc).__name__}: {str(exc)[:200]}")
            await self.send(type="error", what="judge", purpose=purpose, text=f"{type(exc).__name__}: {str(exc)[:120]}")
            return {}
        self.rec.write("judge", purpose=purpose, ms=int((time.monotonic() - t) * 1000), state=state, questions=questions,
                       answers={k: P(answers, k) for k in questions})
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
        for d in list(self.decisions.values()):
            if await d.on_tick(self, now):        # it answered or dropped the words: the rest look again next tick
                break

    def _reset_quiet(self):
        j = self.cfg.quiet_jitter
        self.quiet_marks = [m * random.uniform(1 - j, 1 + j) for m in self.cfg.quiet_marks_s]

    # ------------------------------------------------------------------ speaking
    def data_line(self, kind: str, quiet_s: float = 0.0, listen: str = "", event: str | None = None) -> str:
        """The bracketed line the responder reads before it speaks (speaking.py has the wording for each kind)."""
        pace = self.pace + (f" (just changed from {self.transition[0]})" if self.transition else "")
        if kind != "listen":
            self.transition = None
        last = self.ledger.last_agent()
        event = event or speaking.event_text(kind, last=last.text if last else "", quiet_s=quiet_s, listen=listen)
        return speaking.data_line(pace, event, self.cfg.language)

    async def respond(self, kind: str, quiet_s: float = 0.0):
        self.gen += 1
        gen = self.gen
        self.generating = True
        line = self.data_line(kind, quiet_s)
        event = speaking.EVENTS.get(kind, speaking.UNKNOWN)
        if self.utt is not None and event.answers_user:
            if self.utt.level is not None:
                self.caller_levels = (self.caller_levels + [self.utt.level])[-20:]
            self.ledger.user(self.utt.text, line)
            await self.send(type="user", text=self.utt.text, partial=False)
            self.user_turns += 1
            self.spoke_into_quiet = 0
            self.utt = None
            self.judged = None
        else:
            self.ledger.user("", line)
        messages = [{"role": "system", "content": self.system}, *self.ledger.messages()]
        turn = self.ledger.agent("")
        self.rec.write("respond", gen=gen, kind=kind, data_line=line)
        try:
            async for text in self.llm.lines(messages, max_tokens=event.max_tokens):
                if gen != self.gen:
                    break
                line_id = uuid.uuid4().hex
                self.lines[line_id] = text
                turn.text = (turn.text + "\n" + text).strip()
                self.speaking = True              # on its way to the client: counts as speaking until it reports idle
                await self.send(type="line", gen=gen, id=line_id, text=text, audio=f"/tts/{line_id}")
        finally:
            if gen == self.gen:
                self.generating = False
                if not turn.text:
                    self.speaking = False
                    self.idle_since = time.monotonic()

    async def listen_in(self, kind: str, inviting: bool = False):
        """A listening sound while the user talks on. Voiced beside the line queue and never added to the history."""
        if self.speaking or self.generating:
            return
        self.listen_last = time.monotonic()
        turn = self.data_line("listen", listen=kind, event=speaking.LISTEN_INVITING if inviting else None)
        messages = [{"role": "system", "content": self.system}, *self.ledger.messages(),
                    {"role": "user", "content": turn + "\n" + (self.utt.text if self.utt else "")}]
        text = ""
        async for line in self.llm.lines(messages, max_tokens=14):
            text = line
            break
        if not text or len(text.split()) > self.cfg.listen_max_words or self.speaking or self.generating:
            return
        line_id = uuid.uuid4().hex
        self.lines[line_id] = text
        await self.send(type="listen", id=line_id, text=text, kind=kind, audio=f"/tts/{line_id}")

    async def _stop_line(self):
        self.gen += 1
        self.generating = self.held = False
        self.speaking = False
        last = self.ledger.last_agent()
        if last:
            last.cut = True
        await self.send(type="stop", gen=self.gen)

    async def safe_word(self, text: str):
        await self._stop_line()
        self.utt = None
        self.pace = self.cfg.start_pace
        await self.respond("safe_word")
