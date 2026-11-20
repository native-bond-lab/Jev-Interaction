"""A coding agent in another window as an executor (jev_interaction/harness.py) and Claude Code's connector."""
import asyncio
import io
import json

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


async def test_a_turn_that_breaks_off_on_an_error_fails_the_task_with_the_reason():
    hub, s, events, link, sent = await desk()
    await s.start_task("agent", "fix it")
    await settle()
    await tell(hub, link, type="turn_end", text="", error="API Error: Rate limit reached")
    assert s.tasks[0].status == "failed" and "Claude Code could not go on: API Error: Rate limit reached" in s.tasks[0].result


def test_an_event_from_a_hook_finds_its_session_by_folder():
    hub = H.Hub()

    async def go():
        async def send(e): ...
        a = hub.add(H.Link("Claude Code", send, cwd="/work/a"))
        assert hub.find("Claude Code", "/somewhere/else") is a           # the only one there is
        b = hub.add(H.Link("Claude Code", send, cwd="/work/b"))
        assert hub.find("Claude Code", "/work/b") is b and hub.find("Claude Code", "/work/a") is a
        assert hub.find("Claude Code", "/somewhere/else") is None and hub.find("Codex", "/work/a") is None
        hub.drop(a), hub.drop(b)
    asyncio.run(go())


# ---------------------------------------------------------------------- Claude Code's connector
def test_claude_codes_hooks_as_the_hubs_events():
    typed = CC.events({"hook_event_name": "UserPromptSubmit", "prompt": "fix the bug"})
    assert typed == [{"type": "turn_start", "text": "fix the bug", "ours": False}]
    for source in ("jev", "plugin:jev-voice:jev"):
        pushed = CC.events({"hook_event_name": "UserPromptSubmit", "prompt": f'<channel source="{source}" task="2">fix it</channel>'})
        assert pushed[0]["ours"]
    tool = CC.events({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "npm test", "description": "Run the tests"}})
    assert tool == [{"type": "tool_done"}, {"type": "progress", "text": "running: Run the tests"}]
    assert CC.events({"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "/a/b/app.py"}})[1]["text"] == "editing app.py"
    assert CC.events({"hook_event_name": "PreToolUse", "tool_name": "mcp__plugin_jev-voice_jev__say", "tool_input": {}}) == []
    assert CC.events({"hook_event_name": "PostToolUse", "tool_name": "Bash"}) == [{"type": "tool_done"}]
    assert CC.events({"hook_event_name": "Stop", "last_assistant_message": "Done."}) == [{"type": "turn_end", "text": "Done."}]
    assert CC.events({"hook_event_name": "StopFailure", "error": "rate_limit", "last_assistant_message": "API Error: Rate limit reached"}) == [
        {"type": "turn_end", "text": "", "error": "API Error: Rate limit reached"}]
    assert CC.events({"hook_event_name": "SessionStart"}) == []
    ask = CC.asks({"request_id": "abcde", "tool_name": "Bash", "description": "Delete the build folder", "input_preview": '{"command": "rm -rf build"}'})
    assert ask == {"type": "ask", "id": "abcde", "text": 'Claude Code asks to use Bash: Delete the build folder ({"command": "rm -rf build"})'}


async def test_the_channel_speaks_mcp_to_claude_code_and_passes_words_both_ways():
    out = io.StringIO()
    ch = CC.Channel("ws://unused", "/work/app", out=out)
    to_hub = []

    class Hub:
        async def send(self, raw):
            to_hub.append(json.loads(raw))
    written = lambda: [json.loads(x) for x in out.getvalue().splitlines()]  # noqa: E731
    await ch.on_mcp({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    init = written()[-1]["result"]
    assert init["capabilities"] == {"experimental": {"claude/channel": {}, "claude/channel/permission": {}}, "tools": {}}
    assert init["protocolVersion"] == "2025-06-18" and "say" in init["instructions"]
    await ch.on_mcp({"jsonrpc": "2.0", "method": "notifications/initialized"})
    await ch.on_mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert [t["name"] for t in written()[-1]["result"]["tools"]] == ["say"]
    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "say", "arguments": {"task": "1", "text": "Fixed."}}}
    await ch.on_mcp(call)                                                # the call server is not up: Claude is told so
    assert "not running" in written()[-1]["result"]["content"][0]["text"] and not to_hub
    ch.hub = Hub()
    await ch.on_mcp({**call, "id": 4})
    assert to_hub == [{"type": "say", "task": "1", "text": "Fixed."}] and written()[-1]["result"]["content"][0]["text"] == "Said."
    await ch.on_mcp({"jsonrpc": "2.0", "method": "notifications/claude/channel/permission_request",
                     "params": {"request_id": "abcde", "tool_name": "Bash", "description": "Run shell command", "input_preview": "rm -rf build"}})
    assert to_hub[-1]["type"] == "ask" and to_hub[-1]["id"] == "abcde"
    ch.on_hub({"type": "prompt", "task": "2", "text": "now run the suite"})
    assert written()[-1] == {"jsonrpc": "2.0", "method": "notifications/claude/channel",
                             "params": {"content": "now run the suite", "meta": {"task": "2"}}}
    ch.on_hub({"type": "answer", "id": "abcde", "behavior": "allow"})
    assert written()[-1]["method"] == "notifications/claude/channel/permission" and written()[-1]["params"] == {"request_id": "abcde", "behavior": "allow"}
    n = len(written())
    ch.on_hub({"type": "cancel", "task": "2"})                           # a running turn cannot be stopped from outside
    await ch.on_mcp({"jsonrpc": "2.0", "id": 9, "method": "resources/list"})
    assert len(written()) == n + 1 and written()[-1]["error"]["code"] == -32601
