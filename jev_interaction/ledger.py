"""The call as it went, on one clock: who said what and when, and what the engine judged and did along the way.

It is the one record of the call and it only grows. Both readers take it from here: the responder replays it as chat
messages, Jev reads its recent text, and every question put to Jev at one instant reads the same account of that instant
(judge/state.py: `Now`, built by `Session.now`). Nothing is kept beside it for one decision alone.

Times are seconds into the call (`Ledger.clock`). A turn has when it began and ended (`Turn.at`, `Turn.end`) and, for the
user, where their voice stopped and came back inside it (`Turn.pauses`); a silence is the gap between one entry and the
next, so it is never stored. What the engine did between the words is here too (`Ledger.notes`): each answer Jev gave,
with its probabilities, and each thing done with it. Jev is shown the words, not the times: asked the same moment with
the user's earlier pauses written into the recent call, its answers did not follow them. The times are for the engine,
which reads the user's rhythm off them (`reply_gaps`), and for tuning thresholds afterwards against a recorded call.

The turn the user is in the middle of is here as well (`open`): its words so far and what the agent put in while they
talked, a listening sound as much as a word with content. Every reader takes it from this one place (`open_text`, `Utterance.asides`), so the judge, a
listening sound and the reply that follows all know the same things about it.

More than one agent may have been on the line (`Turn.who`, Session.hand_over). The responder only speaks as the one on
it now: what another said before is shown to it as part of what it hears, "(Lyra: ...)", never as its own turn.

A line of the agent's that was cut off ends in "—" (the user heard only that much), and a note after it, in the user's
message, says what it was going to say and they never heard (`Turn.unheard`); words the user said over the agent
go in at once as their own entry, "(over you: …)": the line went on, but both readers know what was said.

Work the agent set going in the background is on the record too (tasks.py): each thing that happens to a task (started,
come back, failed, waiting on the user) is an entry of its own where it happened (`event`, role "task"), in parentheses,
heard by the responder and read by Jev like any other line. The lines the agent wrote to start or steer one are kept
with its turn (`Turn.acts`): its own, and never spoken.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .utterance import Utterance


@dataclass
class Turn:
    role: str            # "user" | "agent" | "task" (something that happened to a background task: tasks.py)
    text: str
    data_line: str = ""  # the bracketed line the responder was given with this user turn
    cut: bool = False
    unheard: str = ""            # a line cut off: the rest of what it was to say, which the user never heard (`text` is
                                 # what they did hear)
    over: bool = False   # said over a line of the agent's that carried on
    who: str = ""        # the agent on the line for this turn: who said it (agent), or who heard it (user); "" = the only one
    # a user turn the agent put something into while listening: (the user's words up to there, what the agent said, the
    # line it was given), in order, and `tail`, the user's words after the last one. Empty for an ordinary turn.
    exchanges: list[tuple[str, str, str]] = field(default_factory=list)
    tail: str = ""
    at: float | None = None      # seconds into the call when it began: the user's first sound, the agent's line going out
    end: float | None = None     # ... and when it ended: the user's last sound, the last of the agent's line played or its
                                 # being cut off. None: still going, or nobody timed it
    pauses: list[tuple[int, float]] = field(default_factory=list)   # the user's pauses inside it (Utterance.pauses)
    acts: list[str] = field(default_factory=list)   # the agent's action lines written with this turn ("/task ..."): its
                                                    # own words to the responder, never said aloud


@dataclass
class Note:
    """Something the engine judged or did, at its place on the call's clock."""
    at: float            # seconds into the call
    kind: str            # "judge" (an answer from Jev: purpose, probabilities), "decision" (what was done with one), "pace", ...
    data: dict = field(default_factory=dict)


@dataclass
class Ledger:
    turns: list[Turn] = field(default_factory=list)
    open: Utterance | None = None    # the user's turn in progress; closed into `turns` by `close_open`
    notes: list[Note] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)   # the call's zero on the monotonic clock

    def clock(self, at: float | None = None) -> float:
        """Seconds into the call: of a time.monotonic() reading, or of now."""
        return round((time.monotonic() if at is None else at) - self.started, 3)

    def note(self, kind: str, /, **data) -> Note:
        n = Note(self.clock(), kind, data)
        self.notes.append(n)
        return n

    def _timed(self, t: Turn, utt: Utterance | None) -> Turn:
        if utt is not None:
            t.at, t.end, t.pauses = self.clock(utt.started), self.clock(utt.last_sound), list(utt.pauses)
        return t

    def user(self, text: str, data_line: str = "", who: str = "") -> Turn:
        t = Turn("user", text, data_line, who=who)
        self.turns.append(t)
        return t

    def said_over(self, text: str, utt: Utterance | None = None) -> Turn:
        t = self._timed(Turn("user", text, over=True), utt)
        self.turns.append(t)
        return t

    def open_text(self, name: str) -> str:
        return self.open.with_asides(name) if self.open else ""

    def close_open(self, name: str, data_line: str = "") -> Turn:
        """The user's turn is taken: its words, with what the agent put in where it came, become a turn of the record."""
        t = self._timed(self.user(self.open_text(name), data_line, who=name), self.open)
        if self.open and self.open.asides:
            t.exchanges, t.tail = self.open.exchanges()
        self.open = None
        return t

    @staticmethod
    def _exchanges(exchanges) -> list[dict]:
        """What the agent said while the user talked is the agent's own: its turn, between the user's words."""
        out = []
        for words, said, line in exchanges:
            out += [{"role": "user", "content": (line + "\n" + words).strip()}, {"role": "assistant", "content": said}]
        return out

    def open_messages(self) -> tuple[list[dict], str]:
        """The turn in progress for the responder: the exchanges so far, and the user's words since the last one."""
        if not self.open:
            return [], ""
        exchanges, tail = self.open.exchanges()
        return self._exchanges(exchanges), tail

    def agent(self, text: str, who: str = "") -> Turn:
        t = Turn("agent", text, who=who, at=self.clock())
        self.turns.append(t)
        return t

    def event(self, text: str) -> Turn:
        """Something that happened on the call that nobody said: a background task started, came back, asked."""
        t = Turn("task", text, at=self.clock())
        self.turns.append(t)
        return t

    def agent_ended(self, but: Turn | None = None) -> None:
        """Nothing of the agent's is playing any more: every line of its that had not ended has, now (`but`: the one
        still being written)."""
        now = self.clock()
        for t in reversed(self.turns):
            if t.role == "agent" and t is not but:
                if t.end is not None:
                    break
                t.end = now

    def last_agent(self) -> Turn | None:
        return next((t for t in reversed(self.turns) if t.role == "agent"), None)

    def last_is_agent(self) -> bool:
        last = next((t for t in reversed(self.turns) if not t.over and t.role != "task"), None)   # words over a line
        # are not a turn, and neither is what happened to a task
        return last is not None and last.role == "agent"

    def reply_gaps(self, n: int = 20) -> list[float]:
        """How long the user took to start answering each line of the agent's, read off the record: from the end of the
        line to their first sound (the turn in progress counts). Words begun over a line are not an answer to it."""
        gaps, ended = [], None
        heard = [(t.role, t.over, bool(t.text), t.at, t.end) for t in self.turns if t.role != "task"]
        if self.open is not None:
            heard.append(("user", self.open.over, True, self.clock(self.open.started), None))
        for role, over, said, at, end in heard:
            if role == "agent":
                ended = end
            elif said and not over:
                if at is not None and ended is not None and 0 < at - ended < 60:
                    gaps.append(at - ended)
                ended = None
        return gaps[-n:]

    def timeline(self) -> list[dict]:
        """The whole record in the order it happened, turns and notes together: what a call log keeps at the end."""
        rows, last = [], 0.0
        for i, t in enumerate(self.turns):             # a turn nobody timed sits where it was appended
            last = t.at if t.at is not None else last
            rows.append((last, 0 if t.role == "user" else 2, i, {"turn": t.__dict__}))
        # in the same millisecond: the user's words, then what was judged and decided about them, then the agent's line
        rows += [(n.at, 1, i, {"note": n.kind, "at": n.at, **n.data}) for i, n in enumerate(self.notes)]
        return [row for *_, row in sorted(rows, key=lambda r: r[:3])]

    def messages(self, me: str = "", max_turns: int = 24) -> list[dict]:
        """The call as chat messages for the agent on the line now (`me`; "" when there has only ever been one)."""
        out: list[dict] = []

        def heard(content: str):                            # consecutive things heard are one message
            if out and out[-1]["role"] == "user":
                out[-1]["content"] += "\n" + content
            else:
                out.append({"role": "user", "content": content})

        for t in self.turns[-max_turns:]:
            mine = not me or t.who in ("", me)
            if t.role == "task":
                heard(t.text)                               # what happened to a task: known to whoever is on the line
            elif t.role == "agent":
                said = t.text + ("—" if t.cut else "")
                if mine:
                    out.append({"role": "assistant", "content": "\n".join([said, *t.acts]).strip()})
                    if t.cut and t.unheard:                 # what it was going to say: never said, so not its own words
                        heard(f'(you were cut off there; they did not hear: "{t.unheard}")')
                elif said:
                    heard(f"({t.who}: {said})")             # another's line: heard, not said
            elif t.exchanges and mine:
                out += self._exchanges(t.exchanges)
                out.append({"role": "user", "content": (t.data_line + "\n" + t.tail).strip()})
            elif t.over:
                heard(f"(over you: {t.text})" if mine else f"(over {t.who}: {t.text})")
            elif mine:
                heard((t.data_line + "\n" + t.text).strip())
            elif t.text:
                heard(t.text)                               # said to another: the words, without the line it was given
        return out

    def recent_text(self, name: str, n: int, width: int) -> str:
        rows = []
        for t in self.turns[-n:]:
            text = (t.text + ("—" if t.cut else "")).strip()
            if text and t.role == "task":
                rows.append(text[:width])
            elif text:
                on = t.who or name
                who = on if t.role == "agent" else f"User (over {on}, who went on)" if t.over else "User"
                rows.append(f"{who}: {text[:width]}")
        return "\n".join(rows)
