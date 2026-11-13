"""What the responder is told before it speaks: one bracketed line with the pace, what just happened, and the language.

Each kind of line the agent can say has an Event: the words that describe the moment, whether the line answers the
user's open utterance, and how long it may be. A new decision that makes the agent speak adds its own with `event()`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TAG = re.compile(r"\[[^\]]*\]")


def has_voice(text: str) -> bool:
    """Whether a written line has anything a voice can say. A line of audio tags alone ("[laughs]") has not: a tag
    shapes the words beside it, and the synthesizers refuse a text that is nothing else."""
    return bool(re.search(r"\w", _TAG.sub(" ", text or "")))

_UNIT = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]|[^\W_]+(?:['’-][^\W_]+)*")


def units(text: str) -> int:
    """How long a written line is to the ear: its words, with each Chinese, Japanese or Korean character counted as one
    (a Chinese sentence has no spaces to split on). Audio tags do not count."""
    return len(_UNIT.findall(_TAG.sub(" ", text or "")))


LANGUAGES = {"en": "English", "zh": "Chinese", "ja": "Japanese"}
LISTEN_EVENTS = {
    "continuer": "they are still talking; a bare listening sound that only says go on, a word at most, or nothing",
    "feeling": "they are still talking and it lands on you: a few words that show how (oh no; really?; a laugh), not an answer",
    "echo": "they are still talking; say back the one word of theirs that matters, as a question, nothing else",
    "receipt": ("they are handing this over piece by piece and will go on; say back only the piece that just landed "
                '("{piece}"), plainly, so they know you have it: no question, nothing added'),
    "cue": ('they are still talking and will go on; what they asked you to mark while they talk has just come up '
            '("{piece}"); say what they asked for, as they asked, and nothing else'),
}
LISTEN_INVITING = "they may not have finished; a questioning sound that invites them on (mm?), or nothing"


@dataclass(frozen=True)
class Event:
    text: str                   # may use {last} (the agent's last line) and {quiet_s} (seconds of quiet)
    answers_user: bool = False  # the line answers the open utterance, which then goes into the history as the user's turn
    max_tokens: int = 160       # 60 for the lines that must be a few words


EVENTS: dict[str, Event] = {
    "pickup": Event("the call was just picked up"),
    "spoke": Event("they spoke", answers_user=True),
    "cut_in": Event("they are still talking and you cut in", answers_user=True),
    "overrule": Event('they cut in while you were saying "{last}"; take the floor back', answers_user=True, max_tokens=60),
    "aside": Event("they chimed in while you were telling something; answer in a word, then the story waits",
                   answers_user=True, max_tokens=60),
    "jump_in": Event("they broke in with something that lights you up; react right now in a few words",
                     answers_user=True, max_tokens=60),
    "lead": Event("they have been quiet for {quiet_s:.0f} s since your last line"),
    "check": Event("they have been quiet for {quiet_s:.0f} s; you check on them", max_tokens=60),
    "hangup": Event("they have been quiet for {quiet_s:.0f} s and you are ending the call"),
    "safe_word": Event("the safe word: everything stops; step out in one or two calm lines and ask if they are all right"),
}
UNKNOWN = Event("")             # a kind nobody registered: its name is the event text, and it is an ordinary line


def event(kind: str, text: str, *, answers_user: bool = False, max_tokens: int = 160) -> None:
    """Register the kind of line a decision makes the agent say with `session.respond(kind)`."""
    EVENTS[kind] = Event(text, answers_user, max_tokens)


def event_text(kind: str, *, last: str = "", quiet_s: float = 0.0, listen: str = "", piece: str = "") -> str:
    if kind == "listen":
        return LISTEN_EVENTS.get(listen, LISTEN_EVENTS["continuer"]).replace("{piece}", piece)
    if kind not in EVENTS:
        return kind
    return EVENTS[kind].text.format(last=last, quiet_s=quiet_s)


def data_line(pace: str, event: str, language: str) -> str:
    return f"[pace: {pace} · event: {event} · speak: {LANGUAGES.get(language, language)}]"
