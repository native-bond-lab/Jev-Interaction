"""The call as it went, for both readers: the responder replays it as chat messages, Jev reads its recent text.

A line of the agent's that was cut off ends in "—" (the user heard only that much); words the user said over the agent
are kept as "(over you: …)" on the next user turn.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Turn:
    role: str            # "user" | "agent"
    text: str
    data_line: str = ""  # the bracketed line the responder was given with this user turn
    cut: bool = False


@dataclass
class Ledger:
    turns: list[Turn] = field(default_factory=list)

    def user(self, text: str, data_line: str = "") -> Turn:
        t = Turn("user", text, data_line)
        self.turns.append(t)
        return t

    def agent(self, text: str) -> Turn:
        t = Turn("agent", text)
        self.turns.append(t)
        return t

    def last_agent(self) -> Turn | None:
        return next((t for t in reversed(self.turns) if t.role == "agent"), None)

    def last_is_agent(self) -> bool:
        return bool(self.turns) and self.turns[-1].role == "agent"

    def messages(self, max_turns: int = 24) -> list[dict]:
        out = []
        for t in self.turns[-max_turns:]:
            if t.role == "user":
                out.append({"role": "user", "content": (t.data_line + "\n" + t.text).strip()})
            else:
                out.append({"role": "assistant", "content": t.text + ("—" if t.cut else "")})
        return out

    def recent_text(self, name: str, n: int, width: int) -> str:
        rows = []
        for t in self.turns[-n:]:
            text = (t.text + ("—" if t.cut else "")).strip()
            if text:
                rows.append(f"{'User' if t.role == 'user' else name}: {text[:width]}")
        return "\n".join(rows)
