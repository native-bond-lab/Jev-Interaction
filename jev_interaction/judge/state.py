"""The text Jev reads. Every state opens the same way (who is on the call, the agent's task profile and manner, the pace,
the recent turns) and then says what is happening on the line right now."""
from __future__ import annotations

from ..ledger import Ledger
from ..profile import Profile


def header(profile: Profile, pace: str, ledger: Ledger, turns: int, chars: int, video: bool = False) -> str:
    recent = ledger.recent_text(profile.short, turns, chars) or "(the call just started)"
    call = (f"Video call between the user and {profile.short}: {profile.short} can see the user." if video
            else f"Phone call between the user and {profile.short}.")
    return (f"{call}\n{profile.judge_header()}\n"
            f"Current pace of the call: {pace}.\nRecent call:\n{recent}\n")


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


def overlap(name: str, agent_line: str, heard: str, speech_ms: int) -> str:
    return f'{name} is in the middle of saying: "{agent_line}"\nOver it, for {speech_ms / 1000:.1f} s, the user is saying: "{heard}".'


def quiet(name: str, last_line: str, quiet_s: float, spoke_into_quiet: int, usual_reply_s: float | None) -> str:
    s = f'{name}\'s last line was: "{last_line}"\nIt has been quiet for {quiet_s:.0f} s since that line.\n'
    if usual_reply_s is not None:
        s += f"On this call the user has usually started answering about {usual_reply_s:.1f} s after {name}'s line.\n"
    if spoke_into_quiet:
        s += f"{name} has already spoken {spoke_into_quiet} time(s) into this quiet without the user saying anything.\n"
    return s


def notice(name: str, seen: str, remarks: int) -> str:
    s = f"What has just changed in view: {seen}\nNobody is talking right now.\n"
    if remarks:
        s += f"{name} has remarked on the view {remarks} time(s) on this call, unasked.\n"
    return s


def notice_pictures(name: str, before: str, now: str, remarks: int, talking: bool = False, moving_s: float = 0.0) -> str:
    """`moving_s`: how long the camera has seen the user keep moving (waving, walking about), which two stills cannot show."""
    s = (f"What {name} saw when something last changed: {before}\nWhat {name} sees now: {now}\n"
         + ("The user is talking right now.\n" if talking else "Nobody is talking right now.\n"))
    if moving_s >= 1:
        s += (f"Between the two pictures the camera has seen the user moving without a stop for {moving_s:.0f} s: a wave, "
              "a gesture or something being shown is going on, which two still pictures cannot show.\n")
    if remarks:
        s += f"{name} has remarked on the view {remarks} time(s) on this call, unasked.\n"
    return s
