"""A coding agent in another window as an executor (jev_interaction/harness.py) and Claude Code's connector."""
import asyncio
import io
import json
import os
import pathlib

import pytest

from jev_interaction import harness as H
from jev_interaction.adapters.base import Segment
from jev_interaction.connectors import claude_code as CC
from jev_interaction.testing import scripted_session


async def settle(n: int = 8):
    for _ in range(n):
        await asyncio.sleep(0)


async def desk(**hub):
    """A voice session, a hub, and one harness session on it whose connector keeps what it is sent."""
    hub = H.Hub(**hub)
    s, events, _ = scripted_session(executors={"agent": hub.executor()})
    hub.attach(s)
    sent = []

    async def send(e):
        sent.append(e)
    link = hub.add(H.Link("Claude Code", send, cwd="/work/app"))
    return hub, s, events, link, sent


async def tell(hub, link, **event):
    hub.post(link, event)
    await settle()


async def test_a_task_asked_by_voice_is_pushed_and_comes_back_with_what_the_agent_wrote_to_be_heard():
    hub, s, events, link, sent = await desk()
    s.llm.out = ("On it.", "/task agent: fix the login test and run the suite")
    await s.on_segment(Segment("Can you fix the login test?"))
    await s.respond("spoke")
    await settle()
    assert sent == [{"type": "prompt", "task": "1", "text": "fix the login test and run the suite"}]
    await tell(hub, link, type="turn_start", text='<channel source="jev" task="1">fix the login test…', ours=True)
    await tell(hub, link, type="progress", text="running: npm test")
    assert s.tasks[0].progress == "running: npm test" and len(s.tasks) == 1
    await tell(hub, link, type="say", task="1", text="Fixed. The token expiry was off by one.")
    assert s.tasks[0].status == "running"                                # the turn has not ended yet
    await tell(hub, link, type="turn_end", text="I changed auth/token.ts line 40 … (a long message)")
    assert s.tasks[0].status == "done" and s.tasks[0].result == "Fixed. The token expiry was off by one."
    assert not link.jobs and not link.busy


async def test_without_words_to_be_heard_the_last_message_comes_back_and_a_turn_already_running_is_not_mistaken_for_it():
    hub, s, events, link, sent = await desk()
    await tell(hub, link, type="progress", text="reading app.py")       # the harness is in the middle of something
    assert link.busy
    await s.start_task("agent", "now add a test for it")
    await settle()
    await tell(hub, link, type="turn_end", text="(the turn that was running)")
    assert s.tasks[0].status == "running"
    await tell(hub, link, type="turn_end", text="Added tests/test_app.py; it passes.")
    assert s.tasks[0].status == "done" and s.tasks[0].result == "Added tests/test_app.py; it passes."


async def test_more_words_for_claude_code_are_a_turn_of_their_own():
    hub, s, events, link, sent = await desk()
    await s.start_task("agent", "fix the login test")
    await settle()
    assert await s.tell_task(1, "use pnpm, not npm")
    assert sent[-1] == {"type": "steer", "task": "1", "text": "use pnpm, not npm"}
    await tell(hub, link, type="turn_end", text="Fixed with npm.")
    assert s.tasks[0].status == "running"                                # the words they added are still to be done
    await tell(hub, link, type="turn_end", text="Redone with pnpm.")
    assert s.tasks[0].result == "Redone with pnpm."


async def test_a_may_i_is_put_to_the_user_and_answered_on_their_screen_unless_voice_approvals_are_on():
    hub, s, events, link, sent = await desk()
    await s.start_task("agent", "clean the build")
    await settle()
    await tell(hub, link, type="ask", id="abcde", text="Claude Code asks to use Bash: delete the build folder")
    task = s.tasks[0]
    assert task.status == "waiting" and "They answer it on their own screen." in task.question
    await tell(hub, link, type="tool_done")                              # answered on the screen: the question is over
    assert task.status == "running" and not task.news and not link.asks
    assert not [e for e in sent if e["type"] == "answer"]

    hub, s, events, link, sent = await desk(voice_approvals=True)
    await s.start_task("agent", "clean the build")
    await settle()
    await tell(hub, link, type="ask", id="abcde", text="Claude Code asks to use Bash: delete the build folder")
    assert 'Pass their answer on as "allow" or "deny".' in s.tasks[0].question
    assert await s.tell_task(1, "allow")
    await settle()
    assert sent[-1] == {"type": "answer", "id": "abcde", "behavior": "allow"} and s.tasks[0].status == "running"
    assert H.verdict("deny it") == "deny" and H.verdict("allow") == "allow" and H.verdict("hmm, maybe") is None


async def test_a_turn_the_user_typed_is_taken_up_once_it_has_run_a_while_and_a_short_one_is_left_alone():
    hub, s, events, link, sent = await desk(adopt_after_s=0.02)
    await tell(hub, link, type="turn_start", text="what does this function do")
    await tell(hub, link, type="turn_end", text="It parses the header.")
    await asyncio.sleep(0.05)
    assert not s.tasks                                                   # over before anyone would want to be told
    await tell(hub, link, type="turn_start", text="migrate the whole test suite to pytest")
    await asyncio.sleep(0.05)
    await settle()
    assert s.tasks and s.tasks[0].given["observed"] and "migrate the whole test suite" in s.tasks[0].about and not sent
    await tell(hub, link, type="turn_end", text="All 214 tests migrated and passing.")
    assert s.tasks[0].status == "done" and s.tasks[0].news and "214" in s.tasks[0].result


async def test_a_may_i_in_a_turn_nobody_asked_for_by_voice_is_taken_up_at_once():
    hub, s, events, link, sent = await desk()
    await tell(hub, link, type="turn_start", text="tidy the repo")
    await tell(hub, link, type="ask", id="qrstu", text="Claude Code asks to use Bash: git clean -fd")
    assert s.tasks and s.tasks[0].status == "waiting" and "git clean" in s.tasks[0].question


async def test_words_for_the_user_with_no_task_behind_them_are_told_as_news():
    hub, s, events, link, sent = await desk()
    await tell(hub, link, type="say", task="", text="The deploy you started this morning finished.")
    assert s.tasks[0].status == "done" and s.tasks[0].result == "The deploy you started this morning finished."


async def test_with_no_harness_connected_or_one_that_goes_away_the_task_fails_and_says_so():
    hub = H.Hub()
    s, events, _ = scripted_session(executors={"agent": hub.executor()})
    await s.start_task("agent", "fix it")
    await settle()
    assert s.tasks[0].status == "failed" and "no coding agent is connected" in s.tasks[0].result
    hub, s, events, link, sent = await desk()
    await s.start_task("agent", "fix it")
    await settle()
    hub.drop(link)
    await settle()
    assert s.tasks[0].status == "failed" and "went away" in s.tasks[0].result


async def test_words_an_idle_harness_does_not_take_fail_the_task_instead_of_hanging():
    hub, s, events, link, sent = await desk()
    link.acks, hub.TAKEN_S = True, 0.05           # Claude Code: a pushed prompt is followed by its turn starting
    await s.start_task("agent", "fix it")
    await asyncio.sleep(0.15)
    assert s.tasks[0].status == "failed" and "did not take the words" in s.tasks[0].result
    await s.start_task("agent", "fix it again")
    await settle()
    await tell(hub, link, type="turn_start", text="fix it again", ours=True)       # taken: it runs as long as it runs
    await asyncio.sleep(0.15)
    assert s.tasks[1].status == "running"


async def test_a_turn_that_breaks_off_on_an_error_fails_the_task_with_the_reason():
    hub, s, events, link, sent = await desk()
    await s.start_task("agent", "fix it")
    await settle()
    await tell(hub, link, type="turn_end", text="", error="API Error: Rate limit reached")
    assert s.tasks[0].status == "failed" and "Claude Code could not go on: API Error: Rate limit reached" in s.tasks[0].result


# ---------------------------------------------------------------------- Claude Code's connector
def test_claude_codes_hooks_as_the_hubs_events():
    assert CC.events({"hook_event_name": "UserPromptSubmit", "prompt": "fix the bug"}) == [{"type": "turn_start", "text": "fix the bug", "ours": False}]
    tool = CC.events({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "npm test", "description": "Run the tests"}})
    assert tool == [{"type": "tool_done"}, {"type": "progress", "text": "running: Run the tests"}]
    assert CC.events({"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "/a/b/app.py"}})[1]["text"] == "editing app.py"
    for own in ("listen", "say", "stop"):                                # the plugin's own tools are not work to tell about
        assert CC.events({"hook_event_name": "PreToolUse", "tool_name": f"mcp__plugin_interaction_jev__{own}", "tool_input": {}}) == []
    assert CC.events({"hook_event_name": "PostToolUse", "tool_name": "Bash"}) == [{"type": "tool_done"}]
    ask = CC.events({"hook_event_name": "PermissionRequest", "tool_name": "Bash", "tool_input": {"command": "rm -rf build"}})
    assert ask == [{"type": "ask", "id": "permission", "text": "Claude Code asks to use Bash (running: rm -rf build)"}]
    assert CC.events({"hook_event_name": "Stop", "last_assistant_message": "Done."}) == [{"type": "turn_end", "text": "Done."}]
    assert CC.events({"hook_event_name": "StopFailure", "error": "rate_limit", "last_assistant_message": "API Error: Rate limit reached"}) == [
        {"type": "turn_end", "text": "", "error": "API Error: Rate limit reached"}]
    assert CC.events({"hook_event_name": "SessionStart"}) == []
    filled = CC.hook_of({"event": "PreToolUse", "tool_name": "Bash", "command": "npm test", "file_path": "${tool_input.file_path}"})
    assert filled["tool_input"] == {"command": "npm test"}               # a field the hook did not have counts as empty


class FakeHubSocket:
    def __init__(self):
        self.got = []

    async def send(self, raw):
        self.got.append(json.loads(raw))

    async def close(self): ...


def connector():
    """Claude Code's connector with what it writes kept, joined to a hub that keeps what it is sent."""
    out, hub = io.StringIO(), FakeHubSocket()
    c = CC.Connector("/work/app", out=out)

    async def join():
        c.hub = hub
        return ""
    c.join = join
    written = lambda: [json.loads(x) for x in out.getvalue().splitlines()]  # noqa: E731
    return c, hub, written


async def call(c, mid, name, **args):
    await c.on_mcp({"jsonrpc": "2.0", "id": mid, "method": "tools/call", "params": {"name": name, "arguments": args}})
    await settle()


def answer(written, mid) -> str:
    return next(m for m in written() if m.get("id") == mid)["result"]["content"][0]["text"]


async def test_the_connector_is_an_mcp_server_with_three_tools_and_one_the_model_is_never_shown():
    c, hub, written = connector()
    await c.on_mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    init = written()[-1]["result"]
    assert init["capabilities"] == {"tools": {}} and init["protocolVersion"] == "2025-06-18" and "listen" in init["instructions"]
    await c.on_mcp({"jsonrpc": "2.0", "method": "notifications/initialized"})
    await c.on_mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert [t["name"] for t in written()[-1]["result"]["tools"]] == ["listen", "say", "stop", "setup"]   # `hook` is for hooks only
    await c.on_mcp({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    assert written()[-1]["error"]["code"] == -32601


async def test_the_session_listens_does_the_work_says_the_outcome_and_listens_again():
    c, hub, written = connector()
    await call(c, 1, "listen")                                           # waits: nothing asked yet
    assert c.on and not [m for m in written() if m.get("id") == 1]
    c.prompts.put_nowait({"type": "prompt", "task": "3", "text": "fix the login test"})
    await settle()
    assert 'task 3' in answer(written, 1) and "fix the login test" in answer(written, 1)
    assert hub.got == [{"type": "turn_start", "text": "fix the login test", "ours": True}]
    await call(c, 2, "hook", event="PreToolUse", tool_name="Bash", description="Run the tests")    # a hook gets through
    assert hub.got[-2:] == [{"type": "tool_done"}, {"type": "progress", "text": "running: Run the tests"}]
    assert answer(written, 2) == "{}"
    await call(c, 3, "say", task="3", text="Fixed.")
    assert hub.got[-1] == {"type": "say", "task": "3", "text": "Fixed."} and answer(written, 3) == "Said."
    await call(c, 4, "listen")                                           # back to listening: that task's turn is over
    assert hub.got[-1] == {"type": "turn_end", "text": ""}


async def test_the_outcome_is_heard_however_the_session_names_it_and_an_empty_say_is_told_so():
    c, hub, written = connector()
    await call(c, 1, "listen")
    c.prompts.put_nowait({"type": "prompt", "task": "1", "text": "count the files"})
    await settle()
    await call(c, 2, "say", task="1", message="There are three files.")  # "message", not "text"
    assert hub.got[-1] == {"type": "say", "task": "1", "text": "There are three files."} and answer(written, 2) == "Said."
    await call(c, 3, "say", content="Three.")                            # no task named: the one it is on
    assert hub.got[-1] == {"type": "say", "task": "1", "text": "Three."}
    n = len(hub.got)
    await call(c, 4, "say", task="1")
    assert "Nothing was said" in answer(written, 4) and len(hub.got) == n


async def test_say_and_listen_called_together_end_the_turn_with_the_outcome_whichever_arrives_first():
    c, hub, written = connector()
    await call(c, 1, "listen")
    c.prompts.put_nowait({"type": "prompt", "task": "1", "text": "count the files"})
    await settle()
    await call(c, 2, "listen")                                           # the session sent say and listen at once, and
    assert hub.got[-1]["type"] == "turn_start"                           # listen got here first: the turn is not ended yet
    await call(c, 3, "say", task="1", text="Three files.")
    assert [e["type"] for e in hub.got[-2:]] == ["say", "turn_end"]      # the outcome, then the end of the turn
    # sent in one step with listen first, say does not run while listen waits: listen answers at once instead
    CC.SAY_S = 0.05
    c.prompts.put_nowait({"type": "prompt", "task": "2", "text": "count them again"})
    await settle()
    n = len(hub.got)
    await call(c, 4, "listen")
    await asyncio.sleep(0.15)
    assert "no outcome said yet" in answer(written, 4) and 'task "2"' in answer(written, 4) and len(hub.got) == n
    await call(c, 5, "say", task="2", text="Still three.")
    await call(c, 6, "listen")
    assert [e["type"] for e in hub.got[-2:]] == ["say", "turn_end"]
    c.prompts.put_nowait({"type": "prompt", "task": "3", "text": "nothing to report on this one"})
    await settle()
    await call(c, 7, "listen")
    await asyncio.sleep(0.15)                                            # told once ...
    await call(c, 8, "listen")
    await asyncio.sleep(0.15)                                            # ... a session with nothing to say is let through
    assert hub.got[-1] == {"type": "turn_end", "text": ""}
    CC.SAY_S = 1.0


async def test_a_turn_ending_while_voice_interaction_is_on_is_sent_back_to_listening():
    c, hub, written = connector()
    await call(c, 1, "listen")
    c.prompts.put_nowait({"type": "prompt", "task": "1", "text": "tidy up"})
    await settle()
    await call(c, 2, "hook", event="Stop", last_assistant_message="Tidied.")     # it stopped without listening again
    assert json.loads(answer(written, 2))["decision"] == "block" and "listen" in answer(written, 2)
    assert hub.got[-1] == {"type": "turn_end", "text": "Tidied."}
    n = len(hub.got)
    await call(c, 3, "listen")                                           # the turn has ended once already: not twice
    assert len(hub.got) == n
    await call(c, 4, "hook", event="UserPromptSubmit", prompt="what does this function do")       # the user types meanwhile
    await call(c, 5, "hook", event="Stop", last_assistant_message="It parses the header.")
    assert hub.got[-2:] == [{"type": "turn_start", "text": "what does this function do", "ours": False},
                            {"type": "turn_end", "text": "It parses the header."}]
    await call(c, 6, "stop")
    assert answer(written, 6) == "Voice interaction is off." and not c.on and c.hub is None
    await call(c, 7, "hook", event="Stop", last_assistant_message="Bye.")
    assert answer(written, 7) == "{}"                                    # off: a turn ends as it always did


async def test_interrupting_the_listen_call_puts_the_user_back_at_the_keyboard():
    c, hub, written = connector()
    await call(c, 1, "listen")
    assert c.on
    await c.on_mcp({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}})
    await settle()
    assert not c.on
    await call(c, 2, "hook", event="Stop")
    assert answer(written, 2) == "{}"


async def test_when_the_voice_cannot_start_the_session_is_told_why_and_is_not_held_in_the_loop():
    c, hub, written = connector()

    async def join():
        return "voice interaction is not set up yet: JEV_FAST_MODEL missing"
    c.join = join
    await call(c, 1, "listen")
    assert "did not start" in answer(written, 1) and "JEV_FAST_MODEL" in answer(written, 1) and not c.on
    await call(c, 2, "say", text="hello")
    assert "not on" in answer(written, 2)


async def test_what_the_user_chose_the_first_time_is_kept_and_a_key_never_goes_through_the_conversation(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_HOME", str(tmp_path))
    c, hub, written = connector()
    await call(c, 1, "setup", values={"JEV_FAST_MODEL": "haiku", "ASR_PROVIDER": "elevenlabs"})
    assert answer(written, 1) == "Kept. Call listen again."
    env = (tmp_path / ".env")
    assert env.read_text() == "JEV_FAST_MODEL=haiku\nASR_PROVIDER=elevenlabs\n" and oct(env.stat().st_mode)[-3:] == "600"
    await call(c, 2, "setup", values={"TTS_API_KEY": "sk-secret"})
    assert "is a key" in answer(written, 2) and "sk-secret" not in env.read_text()
    CC.keep({"TTS_API_KEY": "", "JEV_FAST_MODEL": "sonnet"})                 # a key's name waits in the file for its value
    assert env.read_text() == "JEV_FAST_MODEL=sonnet\nASR_PROVIDER=elevenlabs\nTTS_API_KEY=\n"
    env.write_text(env.read_text().replace("TTS_API_KEY=", "TTS_API_KEY=typed-by-the-user"))
    CC.keep({"TTS_API_KEY": ""})                                           # ... and is never wiped once it is there
    assert "TTS_API_KEY=typed-by-the-user" in env.read_text()


def test_what_is_still_to_choose_is_read_from_the_call_servers_own_settings(monkeypatch):
    steps = [{"id": "judge", "title": "Judge", "ready": False, "selected": "jev", "providers": [
                 {"name": "jev", "missing": ["JEV_API_KEY"], "fields": [{"name": "JEV_API_KEY", "label": "Jev API key", "secret": True}]}]},
             {"id": "llm", "title": "Language model", "ready": False, "selected": "claude-code", "selector": "LLM_PROVIDER", "providers": [
                 {"name": "openai-compatible", "missing": ["LLM_BASE_URL"], "fields": []},
                 {"name": "claude-code", "missing": ["JEV_FAST_MODEL"], "fields": [{"name": "JEV_FAST_MODEL", "label": "Fast model for talking"}]}]},
             {"id": "asr", "title": "Speech recognition", "ready": False, "selected": None, "selector": "ASR_PROVIDER", "providers": [
                 {"name": "elevenlabs", "missing": [], "fields": []}, {"name": "dashscope", "missing": [], "fields": []}]},
             {"id": "tts", "title": "Speech synthesis", "ready": True, "selected": "elevenlabs", "providers": []}]
    monkeypatch.setattr(CC, "_get", lambda origin, path: {"steps": steps})
    assert CC.unset("http://127.0.0.1:1") == H.needs(steps)                # the connector reads the hub's own account
    choose, keys, said = H.needs(steps)
    assert choose == ["JEV_FAST_MODEL", "ASR_PROVIDER"] and keys == ["JEV_API_KEY"]
    assert "Fast model for talking: set JEV_FAST_MODEL (or set LLM_PROVIDER to openai-compatible for another)" in said
    assert "Speech recognition: set ASR_PROVIDER to one of elevenlabs, dashscope" in said


# ---------------------------------------------------------------------- the call on the computer itself
async def test_the_local_call_plays_lines_in_order_and_says_what_was_heard_when_it_is_stopped():
    from jev_interaction.local import RATE, LocalCall

    class Socket:
        def __init__(self):
            self.sent = []

        async def send(self, raw):
            self.sent.append(json.loads(raw) if isinstance(raw, str) else raw)
    call_, ws = LocalCall(1, profile="pet", language="en"), Socket()
    call_.ws = ws
    assert await call_._on({"type": "line", "gen": 3, "id": "a", "text": "[softly] One two three four.", "audio": "/tts/a"})
    assert await call_._on({"type": "line", "gen": 3, "id": "b", "text": "Five six.", "audio": "/tts/b"})
    assert call_.lines.qsize() == 2
    call_.heard = ["One two three four."]                                  # the first played to its end ...
    call_.current = {"gen": 3, "text": "Five six.", "audio": "/tts/b", "done": False}
    call_.speaker.played = int(RATE * 2 * 0.5)                             # ... and half a second of the second went out
    call_.speaker.feed(b"\x00" * 4000)
    assert await call_._on({"type": "stop", "gen": 4})
    assert ws.sent[-1] == {"type": "heard", "gen": 3, "text": "One two three four.\nFive"}
    assert call_.current is None and call_.speaker.waiting() == 0 and call_.lines.empty()
    assert not await call_._on({"type": "error", "what": "settings"})      # not set up: the call ends and is tried again
    out = call_.speaker.stream()
    next(out)
    call_.speaker.feed(b"\x01\x02" * 10)
    assert out.send(8) == b"\x01\x02" * 8 and out.send(8) == b"\x01\x02" * 2 + b"\x00" * 12     # silence when it runs dry


# ---------------------------------------------------------------------- Claude Code's own model as the responder
FAKE_CLAUDE = """#!/usr/bin/env python3
import json, sys
log = open(sys.argv[0] + ".log", "a")
log.write(json.dumps(sys.argv[1:]) + "\\n"); log.flush()
for line in sys.stdin:
    text = json.loads(line)["message"]["content"][0]["text"]
    log.write(json.dumps({"heard": text}) + "\\n"); log.flush()
    for piece in ("Sure", " thing.\\nOn", " it."):
        print(json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}}}), flush=True)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "Sure thing."}), flush=True)
"""


async def test_claude_codes_own_model_talks_through_one_open_command_line(tmp_path):
    from jev_interaction.adapters.claude_cli import ClaudeCodeResponder
    fake = tmp_path / "claude"
    fake.write_text(FAKE_CLAUDE)
    fake.chmod(0o755)
    r = ClaudeCodeResponder(model="haiku", command=str(fake))
    first = [{"role": "system", "content": "You are Biscuit."}, {"role": "user", "content": "[event: they spoke]\nHello?"}]
    assert [x async for x in r.lines(first)] == ["Sure thing.", "On it."]
    more = [*first, {"role": "assistant", "content": "Sure thing.\nOn it."}, {"role": "user", "content": "(background task 1 started)"},
            {"role": "user", "content": "[event: they spoke]\nHow far is it?"}]
    async for line in r.lines(more):                                     # the listener stops at the first line ...
        assert line == "Sure thing."
        break
    assert [x async for x in r.lines(more)] == ["Sure thing.", "On it."]  # ... and the next reply is still its own
    await r.aclose()
    log = [json.loads(x) for x in (tmp_path / "claude.log").read_text().splitlines()]
    assert len([x for x in log if isinstance(x, list)]) == 1             # one process for the whole call
    argv = log[0]
    assert argv[argv.index("--model") + 1] == "haiku" and argv[argv.index("--system-prompt") + 1].startswith("You are Biscuit.\n\nEverything you write here is said aloud")
    assert argv[argv.index("--tools") + 1] == "" and "--strict-mcp-config" in argv
    heard = [x["heard"] for x in log if isinstance(x, dict)]
    assert heard[0] == "[event: they spoke]\nHello?"
    assert heard[1] == "(background task 1 started)\n[event: they spoke]\nHow far is it?"     # only what it had not heard


# ---------------------------------------------------------------------- any provider that speaks the OpenAI audio API
async def test_speech_from_any_openai_compatible_service_and_no_provider_is_chosen_for_the_user(monkeypatch):
    import httpx

    from jev_interaction.adapters import registry as R
    from jev_interaction.adapters.openai_speech import OpenAICompatASR, OpenAICompatTTS
    seen = []

    def service(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("authorization"), request.content))
        if request.url.path.endswith("/audio/speech"):
            return httpx.Response(200, content=b"ID3-some-mp3-bytes", headers={"content-type": "audio/mpeg"})
        return httpx.Response(200, json={"text": "count the files"})
    transport = httpx.MockTransport(service)
    tts = OpenAICompatTTS(voice="nova", base_url="http://speech.test/v1/", api_key="k", model="tts-1", transport=transport)
    assert b"".join([c async for c in tts.audio("Three files.")]) == b"ID3-some-mp3-bytes" and tts.media_type == "audio/mpeg"
    said = json.loads(seen[-1][2])
    assert seen[-1][:2] == ("/v1/audio/speech", "Bearer k") and said == {"model": "tts-1", "input": "Three files.", "response_format": "mp3", "voice": "nova"}
    asr = OpenAICompatASR(language="en", base_url="http://speech.test/v1", model="whisper-1", transport=transport)   # no key: a local server
    await asr.connect()
    quiet, voice = b"\x00\x00" * 3200, (b"\x00\x40" + b"\x00\xc0") * 1600          # 200 ms frames: silence, and a loud square wave
    for frame in (quiet, quiet, voice, voice, voice, quiet):
        await asr.send(frame)
    assert asr.clips.empty()                                             # one quiet frame is not yet a pause
    await asr.send(quiet)                                                # 400 ms of quiet: the stretch is a clip
    seg = await asyncio.wait_for(asr.out.get(), 2)
    assert seg.text == "count the files" and seg.final
    path, auth, body = seen[-1]
    assert path == "/v1/audio/transcriptions" and auth is None and b"RIFF" in body and b"whisper-1" in body
    await asr.close()
    strict = OpenAICompatASR(base_url="http://speech.test/v1", model="whisper-1", min_voice_ms=300, transport=transport)
    await strict.connect()
    for frame in (quiet, voice, quiet, quiet):                           # one frame of sound: under min_voice_ms, not a clip
        await strict.send(frame)
    assert strict.clips.empty() and strict.out.empty()
    await strict.close()
    # the registry offers it beside the others, and nothing is the default for speech
    for k in ("ASR_PROVIDER", "TTS_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    assert R.selected("asr") is None and R.selected("tts") is None
    assert {"elevenlabs", "dashscope", "openai-compatible"} <= {p.name for p in R.providers("asr")}
    assert {"elevenlabs", "dashscope", "openai-compatible"} <= {p.name for p in R.providers("tts")}


def test_the_local_call_plays_whatever_format_the_chosen_synthesizer_sends():
    miniaudio = pytest.importorskip("miniaudio")       # the `local` extra

    from jev_interaction import local
    assert local.encoded(miniaudio, "audio/mpeg") == miniaudio.FileFormat.MP3
    assert local.encoded(miniaudio, "audio/wav") == miniaudio.FileFormat.WAV
    assert local.encoded(miniaudio, "audio/ogg") == miniaudio.FileFormat.VORBIS
    assert local.encoded(miniaudio, "audio/pcm;rate=24000") is None      # raw: no decoder

    class Source:
        def __init__(self, data): self.data = data

        def read(self, n):
            out, self.data = self.data[:n], self.data[n:]
            return out
    same = b"".join(local.raw(Source(b"\x01\x00" * 2400), "audio/pcm;rate=24000"))
    assert same == b"\x01\x00" * 2400
    up = b"".join(local.raw(Source(b"\x01\x00" * 1600), "audio/pcm;rate=16000"))        # 16 kHz to the speakers' 24 kHz
    assert len(up) == 1600 * 2 * 24000 // 16000


# ---------------------------------------------------------------------- the harness's own model for the talking
async def test_the_talking_is_done_on_the_model_of_a_harness_that_lends_it():
    hub = H.Hub()
    sent = []

    async def send(e):
        sent.append(e)
    link = hub.add(H.Link("DeepSeek Harness", send, cwd="/work/app", talks=True))
    r = hub.responder()
    out = []

    async def talk():
        msgs = [{"role": "system", "content": "You are Biscuit."}, {"role": "user", "content": "[event: they spoke]\nHello?"}]
        async for line in r.lines(msgs, max_tokens=60):
            out.append(line)
    job = asyncio.create_task(talk())
    await settle()
    ask = sent[-1]
    assert ask["type"] == "talk" and ask["system"] == "You are Biscuit." and ask["max_tokens"] == 60
    assert ask["messages"] == [{"role": "user", "content": "[event: they spoke]\nHello?"}]
    hub.post(link, {"type": "talk_line", "id": ask["id"], "text": "Hey."})
    hub.post(link, {"type": "talk_line", "id": ask["id"], "text": "What's up?"})
    hub.post(link, {"type": "talk_end", "id": ask["id"]})
    await asyncio.wait_for(job, 2)
    assert out == ["Hey.", "What's up?"] and not hub.talking and not link.busy     # a reply is not the session working

    async def cut_short():
        async for _ in r.lines([{"role": "user", "content": "Tell me a story."}]):
            break                                                        # they talked over it
    job = asyncio.create_task(cut_short())
    await settle()
    hub.post(link, {"type": "talk_line", "id": sent[-1]["id"], "text": "Once upon a time"})
    await asyncio.wait_for(job, 2)
    await settle()
    assert sent[-1]["type"] == "talk_stop"                               # the model is told it may stop
    hub.drop(link)
    try:
        async for _ in hub.responder().lines([{"role": "user", "content": "hi"}]):
            pass
        raise AssertionError("no harness: no reply")
    except RuntimeError as exc:
        assert "not connected" in str(exc)


def test_an_ipv6_host_in_brackets_in_no_proxy_is_written_so_the_http_client_reads_it(monkeypatch):
    import httpx

    from jev_interaction import cli
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,::1,.local,[::1]")      # as DeepSeek Harness hands it on
    cli.no_proxy()
    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1,::1,.local"
    httpx.AsyncClient()                        # with `[::1]` as it was, this raises InvalidURL


# ---------------------------------------------------------------------- DeepSeek Harness's plugin (connectors/deepseek-harness)
DSH_DRIVER = """
import { apply } from %(plugin)s
const cmds = {}, prompts = []
const ctx = {                                   // what the plugin asks of the harness, and nothing else
  effect: (f) => f(), on: () => () => {},
  commands: { register: (c) => { cmds[c.name] = c; return () => {} } },
  llm: { stream: async function* () { yield { type: 'text-delta', text: 'Hi.' }; yield { type: 'finish', reason: { kind: 'stop' } } } },
}
apply(ctx)
const agent = { followup: (m) => prompts.push(m), steer() {}, cancel() {}, session: { id: 's1', meta: { cwd: process.cwd() } } }
const run = async (rawInput) => (await cmds.interaction.handler({ rawInput, agent })).text
const out = { command: cmds.interaction.name, recorded: cmds.interaction.recordInput }
out.first = await run('')
out.set = await run('set JEV_FAST_MODEL=deepseek/fast ASR_PROVIDER=openai-compatible ASR_BASE_URL=http://127.0.0.1:9/v1 ASR_MODEL=w '
  + 'TTS_PROVIDER=openai-compatible TTS_BASE_URL=http://127.0.0.1:9/v1 TTS_MODEL=t JEV_API_KEY=k')
out.on = await run('')
const hub = (await import('node:fs')).readFileSync(%(hub)s, 'utf8').trim()
const health = await (await fetch(hub.replace('ws://', 'http://').replace('/harness/ws', '/api/health'))).json()
out.links = health.harness
out.off = await run('stop')
await new Promise((r) => setTimeout(r, 1500))
out.gone = await fetch(hub.replace('ws://', 'http://').replace('/harness/ws', '/api/health')).then(() => false, () => true)
console.log(JSON.stringify(out))
process.exit(0)
"""


def test_deepseek_harness_plugin_sets_up_starts_and_stops_the_call_server(tmp_path):
    """The plugin as DeepSeek Harness loads it, against the real call server and a stand-in for the harness: the
    command is there, the first run says what to choose, `set` keeps it, then the plugin is on the hub lending its
    model, and `stop` takes the server down."""
    import shutil
    import subprocess
    import sys
    pytest.importorskip("uvicorn")
    node = shutil.which("node")
    if node is None or int(subprocess.run([node, "-p", "process.versions.node.split('.')[0]"], capture_output=True, text=True).stdout or 0) < 22:
        pytest.skip("needs node 22 or later (the plugin uses its WebSocket)")
    root = pathlib.Path(__file__).resolve().parent.parent
    home = tmp_path / "home"
    (home / ".jev-interaction").mkdir(parents=True)
    bin_ = tmp_path / "jev-interaction"
    bin_.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m jev_interaction.cli "$@"\n')
    bin_.chmod(0o755)
    driver = tmp_path / "driver.mjs"
    driver.write_text(DSH_DRIVER % {"plugin": json.dumps((root / "connectors/deepseek-harness/index.js").as_uri()),
                                    "hub": json.dumps(str(home / ".jev-interaction" / "hub"))})
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("JEV_", "ASR_", "TTS_", "LLM_", "ELEVENLABS_", "DASHSCOPE_"))}
    env = {**clean, "HOME": str(home), "JEV_HOME": str(tmp_path / "jev"), "JEV_INTERACTION_BIN": str(bin_), "JEV_LOCAL_AUDIO": "0",
           "JEV_VOICEPRINT": "0", "JEV_SOUND": "off", "PYTHONPATH": str(root)}
    done = subprocess.run([node, str(driver)], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
    assert done.returncode == 0, done.stderr[-800:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["command"] == "interaction" and out["recorded"] is False          # a key given with `set` is not logged
    assert "not set up yet" in out["first"] and "JEV_FAST_MODEL" in out["first"] and "ASR_PROVIDER" in out["first"]
    assert out["set"].startswith("Kept JEV_FAST_MODEL") and "Everything is set" in out["set"]
    assert out["on"].startswith("Voice interaction is on")
    assert [k["harness"] for k in out["links"]] == ["DeepSeek Harness"]
    assert out["off"] == "Voice interaction is off." and out["gone"] is True
