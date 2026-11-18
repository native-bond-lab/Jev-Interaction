"""The questions for Alibaba Cloud Bailian's decision model (Config.judge_provider = "bailian", JEV_PROVIDER=bailian).

Jev reads the engine's own questions (judge/questions.py) well and keeps them. Bailian's `decision-model-preview`
speaks the same protocol but reads them differently, so for it some decisions are put another way. Everything here
follows what made "have they finished" work on it (questions.last_words):

- the words a question is about go into the state object in a field of their own, and the question points at that
  field ("Look only at `user_words_over_it`"); the engine's text state rides along under `call`;
- every choice is asked twice in the one request, the options in both orders, and the two answers are averaged
  (`merge`): this judge leans to whichever option comes first;
- a question has two options where it can, and one thing to look at: a long question that needs the whole call read
  (did they ask for this earlier, and has it come up now?) is split into small ones whose answers are combined here.

Only the decisions this judge got wrong are reworded: both talking (floor), quiet since the agent's line (quiet) and
"something is due" while listening. The others go out as the engine words them. The wordings are measured, not tidied:
a few changed words moved results by twenty points. `python tools/judge_bench.py --decisions --held-out` before and
after any edit.
"""
from __future__ import annotations

from .client import probs as P

AGAIN = "__r"     # the twin of a question, asked with its options in reverse order


def both(name: str, question: dict) -> dict:
    """The question under `name` and again under `name__r` with its options reversed."""
    return {name: question, name + AGAIN: {**question, "criteria": dict(reversed(list(question["criteria"].items())))}}


def merge(answers: dict) -> dict:
    """Each question asked both ways round, as one answer with the two orders averaged; the twins are dropped."""
    out = {k: v for k, v in answers.items() if not k.endswith(AGAIN)}
    for k, v in answers.items():
        if k.endswith(AGAIN) and k[:-len(AGAIN)] in out:
            a, b = P(answers, k[:-len(AGAIN)]), (v or {}).get("probabilities") or {}
            if a and b:
                mean = {c: (a.get(c, 0.0) + b.get(c, 0.0)) / 2 for c in a.keys() | b.keys()}
                out[k[:-len(AGAIN)]] = {**out[k[:-len(AGAIN)]], "probabilities": mean, "choice": max(mean, key=mean.get)}
    return out


def _p(answers: dict, name: str, choice: str) -> float:
    return P(answers, name).get(choice, 0.0)


# ---------------------------------------------------------------- both talk at once
FLOOR = "Look only at `user_words_over_it`, which the user said while the agent was talking. What is it?"
REACTION = "a listening sound or a short reaction that needs no answer: mm, yes, right, I see, a laugh, really"
STOP = "the user asks the agent to stop, to wait or to change the subject"
OWN = "a question or a remark of the user's own that wants an answer"


def floor(criteria: dict) -> dict:
    """What the user said over the line: a reaction, a "stop", or something of their own that wants an answer. The
    third becomes the pace's own way of answering (`criteria` is the engine's floor_criteria for this pace): finish the
    sentence first, a word in passing while telling (aside), or taking the floor back (overrule). Reacting at once
    (jump_in) is not offered: it is the engine's question's alone."""
    own = next((k for k in ("finish_first", "aside", "overrule") if k in criteria), "yield")
    options = {"carry_on": REACTION, "yield": STOP}
    if own != "yield":
        options[own] = OWN
    if "elsewhere" in criteria:
        options["elsewhere"] = criteria["elsewhere"]
    return both("floor", {"type": "choice", "instructions": FLOOR, "criteria": options})


def floor_state(call: str, agent_line: str, heard: str) -> dict:
    return {"call": call, "agent_line": agent_line, "user_words_over_it": heard}


# ---------------------------------------------------------------- quiet since the agent's last line
TURN = {"type": "choice", "instructions": "Look only at `agent_last_line`. Does it leave the user something to answer or do, "
        "or is it a statement the agent could go on from?", "criteria": {
            "theirs": "it asks the user something, or tells them to take their time: the next move is the user's",
            "ours": "a statement, a piece of a story or an explanation: nothing is asked of the user"}}
BUSY = {"type": "choice", "instructions": "Look only at `user_last_words`. Did the user say they need a moment, or are off to "
        "do or find something?", "criteria": {
            "busy": "yes: wait, one moment, let me look, let me think, I'll go and get it",
            "not_busy": "no: they said something else"}}
BYE = {"type": "choice", "instructions": "Look at `user_last_words` and `agent_last_line`. Have the two of them said goodbye?",
       "criteria": {"goodbye": "yes: goodbye, good night, talk later: the call has been closed",
                    "going": "no: nobody has said goodbye"}}
GONE = {"type": "choice", "instructions": "Look at `agent_last_line` and `times_agent_spoke_into_this_quiet`. Has the agent "
        "already been calling out to the user and getting no answer?", "criteria": {
            "unanswered": "yes: the agent has already spoken into this quiet, asking if the user is there, and nothing came back",
            "not_yet": "no: the agent has not called out into this quiet yet"}}
LONG = {"type": "choice", "instructions": "Look only at `seconds_of_quiet`, the seconds since the agent's last line. Is that "
        "a pause before an answer, or long enough that a person on the phone would wonder whether the other is still there?",
        "criteria": {"pause": "a pause: a few seconds, the time it takes to think or start answering",
                     "long": "long: well over ten seconds of nothing"}}


def quiet() -> dict:
    """Five small questions in place of the engine's one: whose move it is (the agent's line, the user's last words),
    whether the call has ended (goodbyes, or calling out with no answer) and whether the quiet is long."""
    return {**both("turn", TURN), **both("busy", BUSY), **both("bye", BYE), **both("gone", GONE), **both("long", LONG)}


def quiet_state(call: str, agent_last_line: str, user_last_words: str, quiet_s: float, spoke_into_quiet: int,
                pace: str) -> dict:
    return {"call": call, "agent_last_line": agent_last_line, "user_last_words": user_last_words,
            "seconds_of_quiet": round(quiet_s), "times_agent_spoke_into_this_quiet": spoke_into_quiet, "pace": pace}


def quiet_probs(answers: dict) -> dict[str, float]:
    """The engine's quiet choices from the five answers (merged): an ended call hangs up; otherwise the agent goes on
    when the move is its own, and when it is the user's, waits through a pause and checks on them after a long quiet.
    Which choices are open at all is still the engine's (Quiet.allowed: check and hang-up need enough quiet)."""
    if "turn" not in answers:
        return {}
    theirs = 1 - (1 - _p(answers, "turn", "theirs")) * (1 - _p(answers, "busy", "busy"))
    ended = 1 - (1 - _p(answers, "bye", "goodbye")) * (1 - _p(answers, "gone", "unanswered"))
    long = _p(answers, "long", "long")
    return {"go_on": (1 - ended) * (1 - theirs), "wait": (1 - ended) * theirs * (1 - long),
            "check": (1 - ended) * theirs * long, "hang_up": ended}


# ---------------------------------------------------------------- while listening: is something due
TASK = {"type": "choice", "instructions": "Look only at `user_earlier_lines`. Did the user give the agent a rule of the form "
        "'every time X, you do Y' or 'after each one, you do Y'?", "criteria": {
            "task": "yes, a rule like that", "no_task": "no rule like that"}}
HIT = {"type": "choice", "instructions": "The user asked for something each time a certain thing comes up, or after each piece "
       "they give (see `user_earlier_lines`). Does `user_latest_words` bring that thing up, or give such a piece?", "criteria": {
           "hit": "yes: that thing, or a piece, is in these words", "miss": "no: these words do not bring it up"}}
ASKS = {"type": "choice", "instructions": "Look only at `user_latest_words`. Is it a question or a request to the agent, or is "
        "the user telling something?", "criteria": {
            "asks": "a question or a request to the agent: it wants an answer",
            "tells": "the user telling something: a statement, a story, a piece of a list"}}


def listen() -> dict:
    """Asked beside the engine's listen question, in the turn request: was a standing task set earlier, do the latest
    words bring it up, and do they ask for an answer. The engine's question still says how often a sound fits."""
    return {**both("rule", TASK), **both("hit", HIT), **both("ask", ASKS)}


def listen_probs(answers: dict) -> dict[str, float]:
    """The engine's listen choices: due when a task was set and has just come up (both answers, multiplied, so that a
    judge leaning to "yes" on either alone does not make it due); otherwise an answer is due when they ask something,
    and the rest is shared between a sound and silence as the engine's own question shares it."""
    if "rule" not in answers:
        return P(answers, "listen")
    due = _p(answers, "rule", "task") * _p(answers, "hit", "hit")
    asks = _p(answers, "ask", "asks")
    own = P(answers, "listen")
    total = sum(own.values())
    fits = own.get("fits", 0.0) / total if total else 0.3
    rest = 1 - due
    return {"due": due, "answer_due": rest * asks, "fits": rest * (1 - asks) * fits, "quiet": rest * (1 - asks) * (1 - fits)}


def earlier_user_lines(ledger, turns: int) -> list[str]:
    """What the user said in the recent turns (not the turn in progress), oldest first."""
    return [t.text for t in ledger.turns[-turns:] if t.role == "user" and t.text]
