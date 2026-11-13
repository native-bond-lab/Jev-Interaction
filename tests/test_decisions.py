import asyncio
import json
import pathlib

from test_core import make

from jev_interaction import ArgmaxPolicy, Config, speaking
from jev_interaction.adapters.base import Segment
from jev_interaction.decisions import DECISIONS, Decision, register
from jev_interaction.judge import questions as Q
from jev_interaction.judge.client import probs as P
from jev_interaction.recorder import Recorder

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_every_built_in_decision_has_a_policy():
    assert list(DECISIONS) == ["turn", "trail", "listen", "floor", "cut_in", "quiet"]      # the order they are offered in
    assert all(d.policy in Config().policies for d in DECISIONS.values())


class Laugh(Decision):
    """A toy decision, whole in one class: asked on new words while the agent is quiet."""
    name = "laugh"
    policy = "laugh"

    def on_words(self, s):
        if not s.speaking and not s.generating:
            s._spawn(self.ask(s))

    def questions(self, s, ctx):
        return {"laugh": {"type": "choice", "instructions": f"The user just made a joke. Would {s.p.short} laugh?",
                          "criteria": {"laugh": "finds it funny and laughs", "smile": "a warm word", "none": "lets it pass"}}}

    def allowed(self, s, ctx):
        return ["laugh", "none"]

    async def apply(self, s, answers, ctx):
        choice = self.choose(s, answers, "laugh", ctx)
        await s.send(type="decision", what="laugh", action=choice, probs=P(answers, "laugh"))
        if choice == "laugh":
            await s.respond("laugh")


async def test_a_new_decision_is_one_module_registered_with_a_policy():
    register(Laugh())
    speaking.event("laugh", "they made a joke and you laugh", answers_user=True, max_tokens=60)
    try:
        s, events, judge = make({"laugh": {"laugh": 0.3, "smile": 0.6, "none": 0.1}}, {"laugh": ArgmaxPolicy()})
        await s.on_segment(Segment("Why did the chicken cross the road?"))
        await asyncio.sleep(0.05)
        state = next(state for asked, state in judge.asked if asked == {"laugh"})         # its own request to Jev
        assert "Chatty listener." in state and "Current pace of the call: normal." in state
        assert any(e.get("what") == "laugh" and e["action"] == "laugh" for e in events)   # smile was not allowed now
        assert any(e["type"] == "line" for e in events)
        assert "event: they made a joke and you laugh" in s.ledger.turns[0].data_line
        assert s.ledger.turns[0].text == "Why did the chicken cross the road?" and s.llm.seen
    finally:
        DECISIONS.pop("laugh")
        speaking.EVENTS.pop("laugh")
    s2, _, _ = make({})
    assert "laugh" not in s2.decisions


async def test_a_failing_judge_leaves_a_new_decision_with_no_choice():
    class BrokenJudge:
        async def ask(self, questions, state):
            raise RuntimeError("judge down")
    s, events, _ = make({}, {"laugh": ArgmaxPolicy()})
    s.judge = BrokenJudge()
    s.decisions["laugh"] = Laugh()                       # this session only
    await s.ask("laugh")
    assert any(e.get("what") == "laugh" and e["action"] is None for e in events)
    assert not any(e["type"] == "line" for e in events) and "laugh" not in s.busy


def load_replay():
    from jev_interaction import replay
    return replay


class RecordingJudge:
    def __init__(self, choice):
        self.choice, self.asked = choice, []

    async def ask(self, questions, state):
        self.asked.append((questions, state))
        return {k: {"choice": self.choice, "probabilities": {self.choice: 1.0}} for k in questions}


async def test_replay_re_asks_the_recorded_questions(tmp_path):
    log = tmp_path / "call.jsonl"
    s, _, _ = make({"floor": {"carry_on": 0.1, "yield": 0.8, "finish_first": 0.1, "jump_in": 0.0}})
    s.rec = Recorder(log)
    s.speaking = True
    s.ledger.agent("So the thing about my morning is")
    await s.on_segment(Segment("Wait, can I ask something?"))
    await asyncio.sleep(0.05)
    s.rec.close()
    replay = load_replay()
    entries = list(replay.records([log], "floor"))
    assert len(entries) == 1 and set(entries[0]["questions"]["floor"]["criteria"]) == {"carry_on", "yield", "finish_first", "jump_in"}
    assert not list(replay.records([log], "quiet"))

    same = RecordingJudge("yield")
    assert await replay.replay(same, entries, out=lambda _: None) == (1, 0)
    assert same.asked == [(entries[0]["questions"], entries[0]["state"])]       # exactly what Jev was asked on the call

    seen, flips = [], []

    def edit(purpose, questions):
        seen.append(purpose)
        return {"floor": {**questions["floor"], "instructions": "Both are talking. What now?"}}
    changed = RecordingJudge("carry_on")
    assert await replay.replay(changed, entries, edit, out=flips.append) == (1, 1)
    assert seen == ["floor"] and changed.asked[0][0]["floor"]["instructions"] == "Both are talking. What now?"
    assert flips[0].startswith("FLIP floor: yield -> carry_on")


async def test_replay_rebuilds_the_questions_of_an_old_log(tmp_path):
    replay = load_replay()
    old = {"event": "judge", "purpose": "quiet", "answers": {"quiet": {"go_on": 0.2, "wait": 0.8}},
           "state": "Phone call between the user and Mara.\nA companion.\nCurrent pace of the call: patient.\nRecent call:\n"}
    log = tmp_path / "old.jsonl"
    log.write_text(json.dumps(old) + "\n", encoding="utf-8")
    judge = RecordingJudge("wait")
    assert await replay.replay(judge, replay.records([log], "quiet"), out=lambda _: None) == (1, 0)
    assert judge.asked[0][0] == {"quiet": Q.quiet("Mara", "patient")}
