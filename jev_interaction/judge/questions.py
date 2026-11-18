"""The interaction decisions, each a plain-language multiple-choice question for Jev.

Adding a behaviour is adding a question here and a module in decisions/ that asks it; changing one is editing its
words and re-asking recorded moments (`jev-interaction replay`). Which choices are offered can depend on the pace. `name` is the
agent's short name.

    when                                   question    choices
    the user pauses while talking          turn        done (finished / continuing), wait, kind (reply / sound), pace
                                           listen      due / fits / quiet / answer_due
    both talk at once                      floor       carry_on / yield / finish_first / overrule / jump_in / aside
    the user talks, the agent leads        cut_in      cut_in / let_finish
    quiet since the agent's last line      quiet       go_on / check / wait / hang_up
    someone else can be put on the line    who         stay / one of the others (rides in the turn request)
    the view changed (video calls)         notice      remark / let_be
"""
from __future__ import annotations

WAIT_MS = {"now": 0, "half_second": 500, "two_seconds": 2000, "hold": 4000}

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
    """Only the moment is asked: whether something from the agent belongs here. What it is (a sound, a word said back,
    a count the user asked for) is the responder's to write from the same record."""
    return {"type": "choice", "instructions": (
        f"The user has the floor and {name} is listening. People on the phone let things slip in while the other talks: a "
        "sound that says go on, a reaction, a word of theirs picked up, a piece said back, something the other asked them "
        f"to say when a certain thing comes up. Is this a moment for {name} to put something in, given what the user has "
        f"just said, what they asked for earlier in the call, what {name} has already put in, and who {name} is? Or does "
        "what the user just said call for an answer, so that slipping something in would be wrong?"), "criteria": {
        "due": (f"something from {name} is expected right here and would be missed: earlier in the call they asked {name} to "
                "say something each time a certain thing comes up while they talk (count it, call it out, mark it) and it has "
                "just come up in their last words (the words that make the request are not a case of it), or they are "
                "handing something over piece by piece (items of a list, a "
                f"number in groups, an address, steps) and a piece has just landed; {name} has not put anything in for it yet"),
        "fits": (f"a spot where a listener like {name} might let a small sound or a word slip in to show they are there; "
                 "nothing is lost without it"),
        "quiet": (f"{name} stays silent here: they are in full flow, {name} has only just put something in, they asked "
                  f"{name} to say nothing else while they talk, or {name} is the kind who listens without a sound"),
        "answer_due": "they have asked something or are waiting for a reply: an answer, when they finish"}}


def who(name: str, cast: dict[str, tuple[str, str]]) -> dict:
    """`cast`: the others who can be put on this line, id -> (name, what they are for)."""
    listed = "; ".join(f"{n} ({task})" for n, task in cast.values())
    criteria = {"stay": (f"the user is talking with {name} and wants to go on with {name}; naming or talking about someone "
                         "else is not asking for them")}
    for pid, (n, _) in cast.items():
        criteria[pid] = f"the user asks for {n} to come on the line now, in {name}'s place"
    return {"type": "choice", "instructions": (
        f"{name} is on the line. Others can be put on it in {name}'s place: {listed}. In what the user has just said, are "
        f"they asking for one of them now?"), "criteria": criteria}


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


def notice(name: str) -> dict:
    return {"type": "choice", "instructions": (
        f"Something new has just come into view on the video call, and right now nobody is talking. When two people are "
        f"on a video call and something new shows up on the other's side, they usually say a word about it: what they "
        f"are holding, what they have just done, who has walked in, where they have gone. Would {name}, being who they "
        f"are, say something about this now?"), "criteria": {
        "remark": f"{name} says something about it now: it is new, and {name} has not remarked on it yet",
        "let_be": (f"{name} lets it pass: it is not really new (the same as before, a small shift in the picture), "
                   f"{name} has just remarked on the view, or the user is plainly absorbed in something on their own")}}
