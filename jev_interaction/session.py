"""One call: audio in, decisions by Jev, lines out.

The session is transport-agnostic. Feed it 200 ms PCM16 frames (`on_audio`) and client messages (`on_client`); it sends
events through `send` and keeps the call's history in a Ledger. Every interaction decision is a question in
judge/questions.py whose answer goes through the policy configured for it (policy.py):

    the user pauses        turn questions  -> answer now? (drawn against p(finished) after Jev's suggested wait)
                           listen question -> a listening sound of some kind, or none
    both talk at once      floor question  -> carry on / yield / finish the sentence / take the floor back / react
    the agent leads        cut_in question -> talk over the user now?
    quiet on the line      quiet question  -> go on / check on them / wait / hang up

Events to the client: line {id, text, audio}, listen {id, text, audio}, hold, unhold, stop, finish_line, hangup,
user {text}, pace {pace, probs}, decision {...}. Client messages: playback {state: playing | idle}, heard {text}.
"""
from __future__ import annotations

import asyncio
import math
import random
import re
import statistics
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import numpy as np

from .adapters.base import VAD, Recognizer, Responder, Segment
from .config import Config, Pace
from .judge import JevClient, questions as Q
from .judge.client import probs as P
from .judge import state as S
from .ledger import Ledger
from .profile import Profile
from .policy import ThresholdPolicy
from .recorder import Recorder

def frame_db(pcm: bytes) -> float:
    """Loudness of one PCM16 frame in dB (0 dB = full scale)."""
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    return 20 * math.log10(float(np.sqrt(np.mean(x ** 2))) + 1e-6) if len(x) else -120.0


SYSTEM_TEMPLATE = (__import__("pathlib").Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")
LANGUAGES = {"en": "English", "zh": "Chinese", "ja": "Japanese"}
LISTEN_EVENTS = {
    "continuer": "they are still talking; a bare listening sound that only says go on, a word at most, or nothing",
    "feeling": "they are still talking and it lands on you: a few words that show how (oh no; really?; a laugh), not an answer",
    "echo": "they are still talking; say back the one word of theirs that matters, as a question, nothing else",
}


@dataclass
class Utterance:
    id: int
    started: float
    segments: list[tuple[float, str]] = field(default_factory=list)
    speech_ms: int = 0
    over: bool = False               # began while the agent was speaking
    levels: list[float] = field(default_factory=list)   # dB of each voiced frame

    @property
    def level(self) -> float | None:
        """How loud the voice was: the louder half of its voiced frames, in dB (pauses do not count)."""
        if not self.levels:
            return None
        top = sorted(self.levels)[len(self.levels) // 2:]
        return sum(top) / len(top)

    @property
    def text(self) -> str:
        return " ".join(x for _, x in self.segments)


class Session:
    def __init__(self, profile: Profile, *, send: Callable[[dict], Awaitable[None]], judge: JevClient, recognizer: Recognizer,
                 responder: Responder, vad: VAD, config: Config | None = None, recorder: Recorder | None = None,
                 system_template: str = SYSTEM_TEMPLATE):
        self.p, self.cfg, self.send_event = profile, config or Config(), send
        self.judge, self.asr, self.llm, self.vad = judge, recognizer, responder, vad
        self.rec = recorder or Recorder(None)
        self.system = system_template.format(name=profile.name, profile=profile.prompt or profile.task)
        self.policies = {**self.cfg.policies, **profile.policies}   # a task type may bring its own policies
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
        self.busy: set[str] = set()
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
        for t in list(self._tasks):
            t.cancel()
        await self.asr.close()
        self.rec.write("end", ledger=[t.__dict__ for t in self.ledger.turns])
        self.rec.close()

    def _spawn(self, coro):
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

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
        if self.speaking or self.generating:
            self._spawn(self.ask_floor(self.gen))
        else:
            self._spawn(self.ask_turn(self.utt.id))
            if self.params().cut_in:
                self._spawn(self.ask_cut_in(self.gen))

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
        if self.cfg.far_db is None or self.utt is None or self.utt.level is None or not self.caller_levels:
            return False
        return statistics.median(self.caller_levels) - self.utt.level >= self.cfg.far_db

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
    def _header(self) -> str:
        return S.header(self.p, self.pace, self.ledger, self.cfg.judge_turns, self.cfg.judge_turn_chars)

    async def _ask(self, purpose: str, questions: dict, state: str) -> dict:
        t = time.monotonic()
        answers = await self.judge.ask(questions, state)
        self.rec.write("judge", purpose=purpose, ms=int((time.monotonic() - t) * 1000), state=state,
                       answers={k: P(answers, k) for k in questions})
        return answers

    async def ask_turn(self, utt_id: int):
        if "turn" in self.busy or self.utt is None:
            return
        self.busy.add("turn")
        try:
            paces = {p.name: p.description for p in self.cfg.paces}
            qs = Q.turn(self.p.short, self.pace, paces, opening=self.user_turns < self.cfg.opening_turns)
            may_listen = not self.speaking and not self.generating and time.monotonic() - self.listen_last >= self.cfg.listen_gap_s
            if may_listen:
                qs["listen"] = Q.listen(self.p.short)
            if self._offer_elsewhere():
                qs["kind"]["criteria"]["elsewhere"] = Q.elsewhere(self.p.short)
            state = self._header() + S.user_turn(self.p.short, self.utt.segments, time.monotonic(), self.silence_ms, self.speaking)
            a = await self._ask("turn", qs, state)
            if self.utt is None or self.utt.id != utt_id:
                return
            kind = P(a, "kind")
            if self._far() or (self._offer_elsewhere() and kind and max(kind, key=kind.get) == "elsewhere"):
                await self._not_for_me("far" if self._far() else "jev")
                return
            await self._update_pace(P(a, "pace"))
            wait = P(a, "wait")
            self.judged = {"finished": P(a, "done").get("finished", 0.0), "wait_ms": int(sum(Q.WAIT_MS[k] * v for k, v in wait.items())),
                           "reply": P(a, "kind").get("reply", 1.0), "drawn": False}
            lp = P(a, "listen")
            kinds = {k: lp.get(k, 0.0) for k in Q.LISTEN_KINDS}
            policy = self.policies["listen"]
            if may_listen and kinds and self.judged["finished"] < self.cfg.listen_finished_max and policy.draw(sum(kinds.values())):
                kind = policy.choose(kinds) or "continuer"
                self._spawn(self.listen_in(kind))
        finally:
            self.busy.discard("turn")

    async def ask_floor(self, gen: int):
        if "floor" in self.busy or self.utt is None or not self.utt.segments:
            return
        self.busy.add("floor")
        try:
            pace = self.params()
            line = (self.ledger.last_agent().text if self.ledger.last_agent() else "")
            criteria = Q.floor_criteria(self.p.short, finish=not pace.leads, overrule=pace.cut_in, aside=pace.leads and not pace.cut_in, jump=True)
            if self._offer_elsewhere():
                criteria["elsewhere"] = Q.elsewhere(self.p.short)
            state = self._header() + S.overlap(self.p.short, line, self.utt.text, self.utt.speech_ms)
            a = await self._ask("floor", {"floor": Q.floor(self.p.short, criteria)}, state)
            if gen != self.gen:
                return
            fp = P(a, "floor")
            if self._far() or (self._offer_elsewhere() and fp and max(fp, key=fp.get) == "elsewhere"):
                await self.send(type="decision", what="floor", action="carry_on", probs=fp)
                await self._not_for_me("far" if self._far() else "jev")
                return
            policy = self.policies["floor"]
            if isinstance(policy, ThresholdPolicy):
                policy = ThresholdPolicy({**policy.thresholds, "yield": pace.yield_p}, policy.default, policy.fallback or "carry_on")
            action = policy.choose(P(a, "floor"), criteria) or "carry_on"
            await self.send(type="decision", what="floor", action=action, probs=P(a, "floor"))
            if action == "carry_on":
                self.held = False
                await self.send(type="unhold", gen=self.gen)
            elif action == "finish_first":
                self.held = False
                await self.send(type="unhold", gen=self.gen)
                await self.send(type="finish_line", gen=self.gen)     # the queued lines are dropped; their turn comes after
            elif action == "yield":
                await self._stop_line()                                # the utterance goes on and is answered when it ends
            else:                                                      # overrule / aside / jump_in: a word now
                await self._stop_line()
                await self.respond(action)
        finally:
            self.busy.discard("floor")

    async def ask_cut_in(self, gen: int):
        if "cut" in self.busy or self.utt is None or self.utt.speech_ms < 1500:
            return
        self.busy.add("cut")
        try:
            state = self._header() + S.user_turn(self.p.short, self.utt.segments, time.monotonic(), self.silence_ms, False)
            a = await self._ask("cut_in", {"cut": Q.cut_in(self.p.short)}, state)
            if gen == self.gen and not self.speaking and not self.generating and self.policies["cut_in"].draw(P(a, "cut").get("cut_in", 0.0)):
                await self.respond("cut_in")
        finally:
            self.busy.discard("cut")

    async def ask_quiet(self, quiet_s: float):
        if "quiet" in self.busy:
            return
        self.busy.add("quiet")
        try:
            last = self.ledger.last_agent()
            gaps = sorted(self.reply_gaps)
            usual = gaps[len(gaps) // 2] if len(gaps) >= 2 else None
            state = self._header() + S.quiet(self.p.short, last.text if last else "", quiet_s, self.spoke_into_quiet, usual)
            gen = self.gen
            a = await self._ask("quiet", {"quiet": Q.quiet(self.p.short, self.pace)}, state)
            if gen != self.gen or self.speaking or self.generating or self.utt is not None:
                return
            allowed = ["go_on", "wait"]
            if quiet_s >= self.cfg.check_min_quiet_s:
                allowed.append("check")
            if quiet_s >= self.cfg.hangup_min_quiet_s and self.spoke_into_quiet:
                allowed.append("hang_up")
            choice = self.policies["quiet"].choose(P(a, "quiet"), allowed)
            await self.send(type="decision", what="quiet", action=choice, quiet_s=round(quiet_s, 1), probs=P(a, "quiet"))
            if choice in ("go_on", "check", "hang_up"):
                self.spoke_into_quiet += 1
                self.hanging_up = choice == "hang_up"
                await self.respond({"go_on": "lead", "check": "check", "hang_up": "hangup"}[choice], quiet_s=quiet_s)
        finally:
            self.busy.discard("quiet")

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
        if self.utt is not None and self.utt.segments and self.silence_ms > 0 and not self.speaking and not self.generating:
            pace = self.params()
            j = self.judged
            if j and not j["drawn"] and self.silence_ms >= min(j["wait_ms"], pace.max_wait_ms):
                j["drawn"] = True                 # one draw per Jev answer; new words or more quiet bring a new answer
                go = self.policies["end_of_turn"].draw(j["finished"])
                await self.send(type="decision", what="end_of_turn", finished=round(j["finished"], 2), go=go)
                if go:
                    if self._far():
                        await self._not_for_me("far")
                        return
                    await self.respond("spoke")
                    return
                if self.policies["listen"].draw(0.5):
                    self._spawn(self.listen_in("continuer", inviting=True))
            if self.silence_ms >= pace.max_wait_ms + 1000:
                if self._far():
                    await self._not_for_me("far")
                    return
                await self.respond("spoke")       # the user has stopped: the turn is theirs no longer
            elif j and j["drawn"] and self.silence_ms in (1000, 2000):
                self._spawn(self.ask_turn(self.utt.id))
        elif self.utt is None and not self.speaking and not self.generating and self.quiet_marks:
            quiet = now - self.idle_since
            if quiet >= self.quiet_marks[0]:
                self.quiet_marks.pop(0)
                self._spawn(self.ask_quiet(quiet))

    def _reset_quiet(self):
        j = self.cfg.quiet_jitter
        self.quiet_marks = [m * random.uniform(1 - j, 1 + j) for m in self.cfg.quiet_marks_s]

    # ------------------------------------------------------------------ speaking
    def data_line(self, kind: str, quiet_s: float = 0.0, listen: str = "") -> str:
        pace = self.pace + (f" (just changed from {self.transition[0]})" if self.transition else "")
        if kind != "listen":
            self.transition = None
        last = self.ledger.last_agent()
        event = {
            "pickup": "the call was just picked up",
            "spoke": "they spoke",
            "cut_in": "they are still talking and you cut in",
            "overrule": f'they cut in while you were saying "{last.text if last else ""}"; take the floor back',
            "aside": "they chimed in while you were telling something; answer in a word, then the story waits",
            "jump_in": "they broke in with something that lights you up; react right now in a few words",
            "lead": f"they have been quiet for {quiet_s:.0f} s since your last line",
            "check": f"they have been quiet for {quiet_s:.0f} s; you check on them",
            "hangup": f"they have been quiet for {quiet_s:.0f} s and you are ending the call",
            "listen": LISTEN_EVENTS.get(listen, LISTEN_EVENTS["continuer"]),
            "safe_word": "the safe word: everything stops; step out in one or two calm lines and ask if they are all right",
        }.get(kind, kind)
        return f"[pace: {pace} · event: {event} · speak: {LANGUAGES.get(self.cfg.language, self.cfg.language)}]"

    async def respond(self, kind: str, quiet_s: float = 0.0):
        self.gen += 1
        gen = self.gen
        self.generating = True
        line = self.data_line(kind, quiet_s)
        if self.utt is not None and kind in ("spoke", "cut_in", "overrule", "aside", "jump_in"):
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
            async for text in self.llm.lines(messages, max_tokens=60 if kind in ("check", "aside", "jump_in", "overrule") else 160):
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
        event = "they may not have finished; a questioning sound that invites them on (mm?), or nothing" if inviting else None
        turn = self.data_line("listen", listen=kind)
        if event:
            turn = turn.replace(LISTEN_EVENTS.get(kind, ""), event)
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
