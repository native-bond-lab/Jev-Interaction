"""The call as it went, for both readers: the responder replays it as chat messages, Jev reads its recent text.

The turn the user is in the middle of is here as well (`open`): its words so far and what the agent put in while they
talked, a listening sound as much as a word with content. Every reader takes it from this one place (`open_text`, `Utterance.asides`), so the judge, a
listening sound and the reply that follows all know the same things about it.

More than one agent may have been on the line (`Turn.who`, Session.hand_over). The responder only speaks as the one on
it now: what another said before is shown to it as part of what it hears, "(Lyra: ...)", never as its own turn.

A line of the agent's that was cut off ends in "—" (the user heard only that much); words the user said over the agent
go in at once as their own entry, "(over you: …)": the line went on, but both readers know what was said.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .utterance import Utterance


@dataclass
class Turn:
    role: str            # "user" | "agent"
    text: str
    data_line: str = ""  # the bracketed line the responder was given with this user turn
    cut: bool = False
    over: bool = False   # said over a line of the agent's that carried on
    who: str = ""        # the agent on the line for this turn: who said it (agent), or who heard it (user); "" = the only one
    # a user turn the agent put something into while listening: (the user's words up to there, what the agent said, the
    # line it was given), in order, and `tail`, the user's words after the last one. Empty for an ordinary turn.
    exchanges: list[tuple[str, str, str]] = field(default_factory=list)
    tail: str = ""


@dataclass
class Ledger:
    turns: list[Turn] = field(default_factory=list)
    open: Utterance | None = None    # the user's turn in progress; closed into `turns` by `close_open`

    def user(self, text: str, data_line: str = "", who: str = "") -> Turn:
        t = Turn("user", text, data_line, who=who)
        self.turns.append(t)
        return t

    def said_over(self, text: str) -> Turn:
        t = Turn("user", text, over=True)
        self.turns.append(t)
        return t

    def open_text(self, name: str) -> str:
        return self.open.with_asides(name) if self.open else ""

    def close_open(self, name: str, data_line: str = "") -> Turn:
        """The user's turn is taken: its words, with what the agent put in where it came, become a turn of the record."""
        t = self.user(self.open_text(name), data_line, who=name)
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
        t = Turn("agent", text, who=who)
        self.turns.append(t)
        return t

    def last_agent(self) -> Turn | None:
        return next((t for t in reversed(self.turns) if t.role == "agent"), None)

    def last_is_agent(self) -> bool:
        last = next((t for t in reversed(self.turns) if not t.over), None)     # words over a line are not a turn
        return last is not None and last.role == "agent"

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
            if t.role == "agent":
                said = t.text + ("—" if t.cut else "")
                if mine:
                    out.append({"role": "assistant", "content": said})
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
            if text:
                on = t.who or name
                who = on if t.role == "agent" else f"User (over {on}, who went on)" if t.over else "User"
                rows.append(f"{who}: {text[:width]}")
        return "\n".join(rows)
