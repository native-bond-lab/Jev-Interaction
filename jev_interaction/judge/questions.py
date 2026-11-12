"""The interaction decisions, each a plain-language multiple-choice question for Jev.

Adding a behaviour is adding a question here and a module in decisions/ that asks it; changing one is editing its
words and re-asking recorded moments (tools/replay.py). Which choices are offered can depend on the pace. `name` is the
agent's short name.

    when                                   question    choices
    the user pauses while talking          turn        done (finished / continuing), wait, kind (reply / sound), pace
                                           listen      continuer / feeling / echo / quiet / answer_due
    both talk at once                      floor       carry_on / yield / finish_first / overrule / jump_in / aside
    the user talks, the agent leads        cut_in      cut_in / let_finish
    quiet since the agent's last line      quiet       go_on / check / wait / hang_up
"""
from __future__ import annotations

WAIT_MS = {"now": 0, "half_second": 500, "two_seconds": 2000, "hold": 4000}
LISTEN_KINDS = ("continuer", "feeling", "echo")

# what a real "no" is: about what the user wants to happen, never about tone or swearing
REAL_NO = ("they want what is happening to end: they tell the agent to stop, quit or leave them alone, or say they do not "
           "want this; anger, swearing, arguing, refusing a request or venting are the user still in the conversation")


def turn(name: str, pace: str, paces: dict[str, str], opening: bool = False) -> dict:
    lead = (f"The call is in the {pace} pace now. A pace is who holds the floor and how turns go, not the topic. Which pace "
            f"fits what is happening now? Keep {pace} if the last lines still fit it; one line's mood alone does not change it.")
    if opening:
        lead += " The call has only just begun: it stays as it is unless the user plainly asks for something else."
    return {
        "done": {"type": "choice", "instructions": "Has the user finished speaking for now?", "criteria": {
            "finished": f"the user has said their piece for now and is waiting for {name}",
            "continuing": "the user is mid-thought: pausing to breathe or think, and will go on"}},
        "wait": {"type": "choice", "instructions": f"How long should {name} wait before answering what the user has said so far?",
                 "criteria": {"now": "answer now: they have finished", "half_second": "a short beat more: they may add a word",
                              "two_seconds": "a couple of seconds: they are likely to go on",
                              "hold": "do not answer yet: they are clearly mid-thought"}},
        "kind": {"type": "choice", "instructions": f"What does the user's latest sound or words ask of {name}?", "criteria": {
            "reply": f"it is addressed to {name} and asks for words back",
            "sound": "a sound or filler along the way; a voice response or none is enough"}},
        "pace": {"type": "choice", "instructions": lead, "criteria": dict(paces)},
    }


def listen(name: str) -> dict:
    return {"type": "choice", "instructions": (
        f"The user is talking and {name} is listening. If {name} lets something slip in right now, the way people on the phone "
        f"show they are there, what kind of thing would it be, given what the user is saying and who {name} is? Or does what "
        "the user just said call for an answer, so that a listening sound would be wrong?"), "criteria": {
        "continuer": "a bare continuer that only says 'go on': mm, mm-hm, uh-huh, yeah, a breath",
        "feeling": "a short reaction to what they are telling: sympathy, surprise, a laugh, warmth",
        "echo": "picking up the one word that matters as a question, so they say more about it",
        "quiet": f"{name} stays silent here: they are in full flow, or {name} is the kind who listens without a sound",
        "answer_due": "they have asked something or are waiting for a reply: an answer, when they finish"}}


def floor_criteria(name: str, *, finish: bool, overrule: bool, aside: bool, jump: bool) -> dict:
    c = {"carry_on": f"the user is reacting, agreeing, laughing or playing along with {name}; {name} carries on",
         "yield": (f"the user needs the floor now: asking {name} to stop or wait ({REAL_NO}), or asking for something else, "
                   f"a real question, a change of subject; {name} stops mid-sentence and listens")}
    if finish:
        c["finish_first"] = f"the user is answering or asking something ordinary; {name} finishes the sentence it is on, then answers"
    if overrule:
        c["overrule"] = (f"the user talks back inside the scene, not asking for anything different and not a real no; {name}, "
                         "who holds the floor here, takes it back, then goes on")
    if jump:
        c["jump_in"] = (f"what they broke in with lights {name} up and cannot wait: a thing they turn out to share, news, a laugh "
                        f"at the same thing; {name} drops the line and reacts at once in a few excited words")
    if aside:
        c["carry_on"] = f"the user only makes listening sounds or one-word reactions; {name} carries on telling"
        c["aside"] = f"the user comments or asks about what {name} is telling; {name} answers in a word or two, then goes on"
    return c


def elsewhere(name: str) -> str:
    """The "not said to me" choice (Config.not_for_me), offered in the turn and floor questions."""
    return (f"the words are not meant for {name}: the user is talking to someone else in the room (often by name), or it is "
            f"another voice in the background; {name} carries on as if nothing was said to them")


def floor(name: str, criteria: dict) -> dict:
    return {"type": "choice", "instructions": f"Both are talking at once. What is the user doing, and what does {name} do?",
            "criteria": criteria}


def cut_in(name: str) -> dict:
    return {"type": "choice", "instructions": f"The user is still talking and {name} is quiet. Does {name} cut in now?", "criteria": {
        "cut_in": f"{name}, who holds the floor here, cuts in over them now: they are rambling, provoking, or it is the moment to take over",
        "let_finish": f"{name} lets them finish: they are telling something, asking something, or saying a real no ({REAL_NO})"}}


def quiet(name: str, pace: str) -> dict:
    return {"type": "choice", "instructions": (
        f"It has been quiet on the line since {name}'s last line. The call is in the {pace} pace. Would {name}, being who they "
        f"are, say something now, or let the quiet be? If the last line asked the user something, the quiet is theirs; if it was "
        "a statement or a story, a pause is where people pick their own thread up. After a long quiet a person on the phone "
        "checks whether the other is still there, and after checking with no answer, or when the call has plainly ended, hangs up."),
        "criteria": {
            "go_on": f"{name} picks the thread up now: adds to what they said or brings up something new",
            "check": f"{name} checks on them: are you there, are you all right, in a few words",
            "wait": f"{name} lets the quiet be: the user is answering in their own time, thinking or busy, or it is too soon",
            "hang_up": f"{name} says goodbye and ends the call: the user has gone, or the call has reached its end"}}
