"""The text Jev reads. Every state opens the same way (who is on the call, the agent's task profile and manner, the pace,
the recent turns) and then says what is happening on the line right now.

"Right now" is one account, the same for every question asked at that instant (`Now`, built by `Session.now` from the
call's record; `now` writes it out). No decision writes its own: a question is put to the call as it stands, so two
questions asked together cannot have read two different calls, and a recorded state can be asked a new question later.

There are two on the line and each is making sound or not, which gives the four moments a call can be in:

    the agent     the user        what `now` says
    quiet         talking         their words so far, segment by segment, and how long since the last sound (`user_turn`)
    talking       talking         the line the agent is on and the words said over it (`overlap`)
    quiet         quiet           the agent's last line and how long it has been quiet since (`quiet`)
    talking       quiet           the line the agent is on, and that the user is listening
"""
from __future__ import annotations

from dataclasses import dataclass

from ..ledger import Ledger
from ..profile import Profile


@dataclass(frozen=True)
class Now:
    """The call at one instant. Times are seconds into the call (Ledger.clock)."""
    name: str                          # the agent on the line
    at: float
    agent_sounding: bool               # a line of the agent's is playing or on its way
    agent_line: str                    # the line it is on, or its last one
    user_open: bool = False            # the user has a turn in progress (ledger.open)
    segments: tuple = ()               # its words so far: (when the recognizer closed them, the words)
    heard: str = ""                    # everything made out of it, the piece not closed yet included
    asides: tuple = ()                 # what the agent put in while they talked (Utterance.asides)
    speech_ms: int = 0                 # how much voice the turn has had
    silence_ms: int = 0                # how long since their last sound; 0 while the voice is going
    quiet_s: float = 0.0               # nobody talking: how long since the agent's last line ended
    spoke_into_quiet: int = 0          # how many times the agent has spoken into this quiet with nothing back
    usual_reply_s: float | None = None  # how soon this user has usually started answering on this call (Ledger.reply_gaps)


def now(m: Now) -> str:
    if m.user_open:
        if m.agent_sounding and m.heard:
            return overlap(m.name, m.agent_line, m.heard, m.speech_ms)
        return user_turn(m.name, list(m.segments), m.at, m.silence_ms, m.agent_sounding, list(m.asides))
    if m.agent_sounding:               # no decision asks about this moment yet
        return f'{m.name} is in the middle of saying: "{m.agent_line}"\nThe user is listening and has made no sound.'
    return quiet(m.name, m.agent_line, m.quiet_s, m.spoke_into_quiet, m.usual_reply_s)


def header(profile: Profile, pace: str, ledger: Ledger, turns: int, chars: int, tasks: str = "") -> str:
    """`tasks`: what the agent has going in the background right now (tasks.line); a line of its own when there is any."""
    recent = ledger.recent_text(profile.short, turns, chars) or "(the call just started)"
    work = f"Work {profile.short} has going in the background: {tasks}.\n" if tasks else ""
    return (f"Phone call between the user and {profile.short}.\n{profile.judge_header()}\n"
            f"Current pace of the call: {pace}.\n{work}Recent call:\n{recent}\n")


def user_turn(name: str, segments: list[tuple[float, str]], now: float, silence_ms: int, agent_speaking: bool,
              asides: list[tuple] = ()) -> str:
    """`asides`: what the agent put in while the user talked (Utterance.asides), shown where it came."""
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


def with_last_words(state: str, words: str, quiet_ms: int) -> dict:
    """The same state as an object: the text every other question reads under `call`, and the user's words of this
    turn in a field of their own for the question that is only about them (questions.last_words)."""
    return {"call": state, "user_latest_words": words, "user_quiet_seconds": round(quiet_ms / 1000, 1)}


def overlap(name: str, agent_line: str, heard: str, speech_ms: int) -> str:
    return f'{name} is in the middle of saying: "{agent_line}"\nOver it, for {speech_ms / 1000:.1f} s, the user is saying: "{heard}".'


def quiet(name: str, last_line: str, quiet_s: float, spoke_into_quiet: int, usual_reply_s: float | None) -> str:
    s = f'{name}\'s last line was: "{last_line}"\nIt has been quiet for {quiet_s:.0f} s since that line.\n'
    if usual_reply_s is not None:
        s += f"On this call the user has usually started answering about {usual_reply_s:.1f} s after {name}'s line.\n"
    if spoke_into_quiet:
        s += f"{name} has already spoken {spoke_into_quiet} time(s) into this quiet without the user saying anything.\n"
    return s
