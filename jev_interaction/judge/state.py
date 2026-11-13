"""The text Jev reads. Every state opens the same way (who is on the call, the agent's task profile and manner, the pace,
the recent turns) and then says what is happening on the line right now."""
from __future__ import annotations

from ..ledger import Ledger
from ..profile import Profile


def header(profile: Profile, pace: str, ledger: Ledger, turns: int, chars: int) -> str:
    recent = ledger.recent_text(profile.short, turns, chars) or "(the call just started)"
    return (f"Phone call between the user and {profile.short}.\n{profile.judge_header()}\n"
            f"Current pace of the call: {pace}.\nRecent call:\n{recent}\n")


def user_turn(name: str, segments: list[tuple[float, str]], now: float, silence_ms: int, agent_speaking: bool,
              asides: list[tuple] = ()) -> str:
    """`asides`: what the agent put in with content while the user talked (Utterance.asides), shown where it came."""
    lines = [f"{name} is {'speaking' if agent_speaking else 'silent'}."]
    if segments:
        lines.append("What the user has said so far, in the segments the recognizer closed after each short pause:")
        for i, (t, x) in list(enumerate(segments, 1))[-6:]:
            lines.append(f'  {max(0.0, now - t):.1f} s ago: "{x}"')
            lines += [f'      and {name} put in: "{said}"' for at, said, *_ in asides if at == i]
    else:
        lines.append("No words recognized yet; the user is making sound.")
    lines.append("Right now the user's voice is still going." if silence_ms == 0 else
                 f"Right now the user has been quiet for {silence_ms / 1000:.1f} s.")
    return "\n".join(lines)


def overlap(name: str, agent_line: str, heard: str, speech_ms: int) -> str:
    return f'{name} is in the middle of saying: "{agent_line}"\nOver it, for {speech_ms / 1000:.1f} s, the user is saying: "{heard}".'


def quiet(name: str, last_line: str, quiet_s: float, spoke_into_quiet: int, usual_reply_s: float | None) -> str:
    s = f'{name}\'s last line was: "{last_line}"\nIt has been quiet for {quiet_s:.0f} s since that line.\n'
    if usual_reply_s is not None:
        s += f"On this call the user has usually started answering about {usual_reply_s:.1f} s after {name}'s line.\n"
    if spoke_into_quiet:
        s += f"{name} has already spoken {spoke_into_quiet} time(s) into this quiet without the user saying anything.\n"
    return s
