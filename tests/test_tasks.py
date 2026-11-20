"""Background tasks and sleep (jev_interaction/tasks.py, Session.sleep)."""
import asyncio
import time

from jev_interaction import FunctionExecutor
from jev_interaction import tasks as T
from jev_interaction.adapters.base import Segment
from jev_interaction.decisions.quiet import QUIET
from jev_interaction.testing import FakeExecutor, scripted_session

FRAME = b"\x00" * 6400


def make(answers=None, **config):
    ex = FakeExecutor()
    s, events, judge = scripted_session(answers, executors={"agent": ex}, **config)
    return s, events, judge, ex


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def idle(s, ago: float = 0.0):
    """The client finished playing; `ago`: that long ago."""
    await s.on_client({"type": "playback", "state": "idle"})
    s.idle_since = time.monotonic() - ago


def lines(events) -> list[str]:
    return [e["text"] for e in events if e["type"] == "line"]


def test_the_lines_that_are_actions():
    assert T.action("/task agent: fix the login test: the one in auth") == ("task", "agent", "fix the login test: the one in auth")
    assert T.action("/tell 2: yes, go ahead") == ("tell", "2", "yes, go ahead")
    assert T.action("  /stop 2") == ("stop", "2", "")
    assert T.action("On it.") is None and T.action("and/or task") is None and T.action("/tasks are fun") is None


async def test_a_call_without_executors_reads_as_before():
    s, _, _ = scripted_session()
    assert "/task" not in s.system and "tasks:" not in s.data_line("spoke")
    assert "background" not in QUIET.state(s, {"quiet_s": 3.0})["call"]


async def test_the_responder_starts_a_task_with_a_line_that_is_never_spoken():
    s, events, _, ex = make()
    assert "/task <kind>" in s.system and "- agent: anything that takes a while" in s.system
    s.llm.out = ("On it.", "/task agent: fix the login test")
    await s.on_segment(Segment("Can you fix the login test?"))
    await s.respond("spoke")
    await settle()
    assert lines(events) == ["On it."]                                   # the action is acted on, not said
    task = s.tasks[0]
    assert (task.id, task.kind, task.about, task.status) == (1, "agent", "fix the login test", "running")
    assert ex.started == [task] and [e["status"] for e in events if e["type"] == "task"] == ["running"]
    msgs = s.ledger.messages()
    assert msgs[-2] == {"role": "assistant", "content": "On it.\n/task agent: fix the login test"}   # its own, kept
    assert msgs[-1]["content"] == "(background task 1 started · agent: fix the login test)"
    assert s.ledger.last_agent().text == "On it."                        # what the user heard has no action in it


async def test_a_reply_that_is_only_an_action_is_not_asked_for_twice():
    s, events, _, ex = make()
    s.llm.out = ("/task agent: look it up",)
    await s.on_segment(Segment("Look it up."))
    await s.respond("spoke")
    await settle()
    assert len(ex.started) == 1 and len(s.llm.seen) == 1 and not lines(events)


async def test_a_running_task_is_in_front_of_the_responder_and_of_jev_until_it_comes_back():
    s, events, judge, ex = make()
    await s.start_task("agent", "fix the login test")
    await settle()
    await ex.tells[1].progress("running the suite")
    line = s.data_line("spoke")
    assert 'tasks: 1 agent "fix the login test" running' in line and 'so far: "running the suite"' in line
    assert "has going in the background: 1 agent" in QUIET.state(s, {"quiet_s": 3.0})["call"]
    assert "hang_up" not in QUIET.allowed(s, {"quiet_s": 60.0})          # something to wait for: the call is not ended
    assert not any("so far" in t.text for t in s.ledger.turns)           # how far it has got is no entry of the record


async def test_what_came_back_is_on_the_record_and_told_in_a_quiet():
    s, events, judge, ex = make()
    await s.start_task("agent", "fix the login test")
    await settle()
    await idle(s)
    ex.finish(1, "The test passes now: the token expiry was off by one.")
    await settle()
    assert s.tasks[0].status == "done" and s.tasks[0].news
    assert "has come back" in s.ledger.turns[-1].text and "off by one" in s.ledger.turns[-1].text
    await s.tick()                                                       # the line has only just gone quiet: not yet
    assert not lines(events)
    s.idle_since = time.monotonic() - 2.0
    await s.tick()
    await settle()
    assert lines(events) == ["Hey.", "What's up?"] and not s.tasks[0].news
    told = next(t for t in s.ledger.turns if "event: a background task of yours has news" in t.data_line)
    assert "has come back, not told yet" in told.data_line
    assert "off by one" in s.llm.seen[-1][-1]["content"]                 # the responder reads the result where it landed
    assert not judge.asked                                               # telling it asked nothing of Jev
    assert "tasks:" not in s.data_line("spoke")                          # told: no longer in the line


async def test_news_that_lands_while_the_user_talks_rides_with_the_reply_to_them():
    s, events, _, ex = make()
    await s.start_task("agent", "fix the login test")
    await settle()
    await s.on_segment(Segment("By the way, how is the weather"))
    ex.finish(1, "Fixed.")
    await settle()
    s.idle_since = time.monotonic() - 30.0
    await s.tick()                                                       # they have the floor: nothing is said over them
    await settle()
    assert not lines(events) and s.tasks[0].news and not s.asleep
    await s.respond("spoke")
    assert "has come back, not told yet" in s.ledger.turns[-2].data_line and not s.tasks[0].news


async def test_a_task_that_fails_or_finds_nothing_says_so():
    s, _, _, ex = make()
    await s.start_task("agent", "one")
    await s.start_task("agent", "two")
    await settle()
    ex.fail(1, "no such repo")
    ex.finish(2, "")
    await settle()
    assert [t.status for t in s.tasks] == ["failed", "empty"]
    text = "\n".join(t.text for t in s.ledger.turns)
    assert "background task 1 failed · agent: one · RuntimeError: no such repo" in text
    assert "background task 2 came back with nothing" in text
    assert "1 agent \"one\" failed, not told yet" in s.tasks_line()


async def test_a_kind_nobody_does_is_said_on_the_record_and_starts_nothing():
    s, _, _, ex = make()
    s.llm.out = ("Sure.", "/task search: flights to Lisbon")
    await s.on_segment(Segment("Find me flights to Lisbon."))
    await s.respond("spoke")
    assert not s.tasks and "search is not a kind of task on this call; the kinds: agent" in s.ledger.turns[-1].text


async def test_a_task_asks_the_user_and_the_agent_passes_the_answer_on():
    answers = []

    async def work(about, tell):
        answers.append(await tell.ask("May I delete the build folder?"))
        return "Deleted and rebuilt."
    s, events, _ = scripted_session(executors={"agent": FunctionExecutor(work, "work on the code")})
    await s.start_task("agent", "clean build")
    await settle()
    task = s.tasks[0]
    assert task.status == "waiting" and task.news and "it asks: May I delete the build folder?" in s.ledger.turns[-1].text
    assert 'waits on their answer: "May I delete the build folder?", not asked yet' in s.tasks_line()
    s.llm.out = ("It wants to delete the build folder. Okay?",)
    await idle(s, ago=2.0)
    await s.tick()
    await settle()
    assert lines(events) == ["It wants to delete the build folder. Okay?"] and not task.news and task.status == "waiting"
    await idle(s)
    s.llm.out = ("Okay.", "/tell 1: yes, go ahead")
    await s.on_segment(Segment("Yes, go ahead."))
    await s.respond("spoke")
    await settle()
    assert answers == ["yes, go ahead"] and task.status == "done" and task.result == "Deleted and rebuilt."


async def test_more_words_for_a_running_task_and_stopping_it():
    s, events, _, ex = make()
    await s.start_task("agent", "fix the login test")
    await settle()
    assert await s.tell_task(1, "use pnpm, not npm") and ex.steered == [(1, "use pnpm, not npm")]
    assert not await s.tell_task(7, "hello") and "no background task 7 is going" in s.ledger.turns[-1].text
    s.llm.out = ("Stopping it.", "/stop 1")
    await s.on_segment(Segment("Never mind, stop."))
    await s.respond("spoke")
    await settle()
    assert s.tasks[0].status == "stopped" and not s.open_tasks() and not s.tasks[0].news
    assert "background task 1 was stopped" in s.ledger.turns[-1].text


# ---------------------------------------------------------------------- sleep
async def asleep_with_a_task(**config):
    s, events, judge, ex = make(**config)
    heard = []

    async def send(pcm):
        heard.append(len(pcm))
    s.asr.send = send
    await s.start_task("agent", "fix the login test")
    await settle()
    await idle(s, ago=21.0)
    await s.tick()
    return s, events, judge, ex, heard


async def test_with_a_task_going_and_the_line_quiet_the_session_sleeps_and_asks_nothing():
    s, events, judge, ex, heard = await asleep_with_a_task()
    assert s.asleep and events[-1] == {"type": "sleep", "why": "task"}
    marks = list(s.quiet_marks)
    for _ in range(20):
        await s.tick()
        await s.on_audio(FRAME)
    await settle()
    assert not judge.asked and s.quiet_marks == marks                    # no question to Jev, no quiet mark used up
    assert not heard                                                     # and nothing went to the recognizer


async def test_it_does_not_sleep_without_a_task_or_when_told_never_to():
    s, events, judge = scripted_session()
    await idle(s, ago=300.0)
    s.quiet_marks = []
    await s.tick()
    assert not s.asleep
    s, events, judge, ex = make(sleep_after_s=None)
    await s.start_task("agent", "x")
    await idle(s, ago=300.0)
    s.quiet_marks = []
    await s.tick()
    assert not s.asleep


async def test_a_companion_on_a_desk_sleeps_with_no_task_and_never_checks_on_the_user_or_hangs_up():
    s, events, judge = scripted_session(sleep_when_idle=True)
    s.spoke_into_quiet = 1
    assert QUIET.allowed(s, {"quiet_s": 60.0}) == ["wait", "go_on"]      # no "are you there?", no hang-up
    await idle(s, ago=21.0)
    s.quiet_marks = []
    await s.tick()
    assert s.asleep and events[-1] == {"type": "sleep", "why": "quiet"}


async def test_the_users_voice_wakes_it_and_the_words_that_woke_it_are_heard():
    s, events, judge, ex, heard = await asleep_with_a_task()
    await s.on_audio(FRAME)                                              # quiet frames while asleep: kept, not sent
    s.vad.voice = True
    await s.on_audio(FRAME)                                              # 200 ms of voice: not enough to wake
    assert s.asleep and not heard
    await s.on_audio(FRAME)                                              # 400 ms in a row: awake
    assert not s.asleep and {"type": "wake", "why": "voice"} in events
    assert heard == [6400, 6400, 6400] and s.utt is not None             # the kept audio went to the recognizer
    await s.on_segment(Segment("How is it going?"))
    assert s.woke == "" and s.utt.text == "How is it going?"


async def test_a_sound_with_no_words_after_it_puts_it_back_to_sleep_with_nothing_asked():
    s, events, judge, ex, heard = await asleep_with_a_task()
    s.vad.voice = True
    await s.on_audio(FRAME)
    await s.on_audio(FRAME)
    assert not s.asleep
    s.vad.voice = False
    for _ in range(8):                                                   # 1.6 s of quiet and no words: it was a noise
        await s.on_audio(FRAME)
    assert s.asleep and events[-1] == {"type": "sleep", "why": "no words"} and not judge.asked


async def test_a_task_coming_back_wakes_it_and_the_news_is_told_at_once():
    s, events, judge, ex, heard = await asleep_with_a_task()
    ex.finish(1, "Fixed.")
    await settle()
    assert not s.asleep and {"type": "wake", "why": "task"} in events
    await s.tick()
    await settle()
    assert lines(events) == ["Hey.", "What's up?"] and not s.tasks[0].news


async def test_the_client_can_put_it_to_sleep_and_wake_it():
    s, events, judge = scripted_session()
    await s.on_client({"type": "sleep"})
    assert s.asleep and events[-1] == {"type": "sleep", "why": "client"}
    await s.tick()
    assert not judge.asked
    await s.on_client({"type": "wake"})
    assert not s.asleep and events[-1] == {"type": "wake", "why": "client"}
    s.speaking = True
    await s.on_client({"type": "sleep"})                                 # not while a line is playing
    assert not s.asleep
