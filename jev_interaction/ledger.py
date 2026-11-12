"""The call as it went, for both readers: the responder replays it as chat messages, Jev reads its recent text.

A line of the agent's that was cut off ends in "—" (the user heard only that much); words the user said over the agent
go in at once as their own entry, "(over you: …)": the line went on, but both readers know what was said.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Turn:
    role: str            # "user" | "agent"
    text: str
    data_line: str = ""  # the bracketed line the responder was given with this user turn
    cut: bool = False
    over: bool = False   # said over a line of the agent's that carried on


@dataclass
class Ledger:
    turns: list[Turn] = field(default_factory=list)

    def user(self, text: str, data_line: str = "") -> Turn:
        t = Turn("user", text, data_line)
        self.turns.append(t)
        return t

    def said_over(self, text: str) -> Turn:
        t = Turn("user", text, over=True)
        self.turns.append(t)
        return t

    def agent(self, text: str) -> Turn:
        t = Turn("agent", text)
        self.turns.append(t)
        return t

    def last_agent(self) -> Turn | None:
        return next((t for t in reversed(self.turns) if t.role == "agent"), None)

    def last_is_agent(self) -> bool:
        last = next((t for t in reversed(self.turns) if not t.over), None)     # words over a line are not a turn
        return last is not None and last.role == "agent"

    def messages(self, max_turns: int = 24) -> list[dict]:
        out = []
        for t in self.turns[-max_turns:]:
            if t.role == "user":
                content = f"(over you: {t.text})" if t.over else (t.data_line + "\n" + t.text).strip()
                if out and out[-1]["role"] == "user":       # said over the line, then their turn: one message
                    out[-1]["content"] += "\n" + content
                else:
                    out.append({"role": "user", "content": content})
            else:
                out.append({"role": "assistant", "content": t.text + ("—" if t.cut else "")})
        return out

    def recent_text(self, name: str, n: int, width: int) -> str:
        rows = []
        for t in self.turns[-n:]:
            text = (t.text + ("—" if t.cut else "")).strip()
            if text:
                who = name if t.role == "agent" else f"User (over {name}, who went on)" if t.over else "User"
                rows.append(f"{who}: {text[:width]}")
        return "\n".join(rows)
