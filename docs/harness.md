# The voice of a coding agent

With `JEV_HARNESS=1` the call server is also a hub for the coding agents open on this machine. You talk; the agent on
the line hands the work to the coding agent as a background task ([tasks.md](tasks.md)), keeps the call going, and
tells you when it is done or needs your OK. While nothing is happening it sleeps.

    you  <— voice —>  Jev-Interaction (call server + hub)  <— connector —>  Claude Code

Today there is one connector, for Claude Code. Codex and DeepSeek Harness speak the same small protocol to the hub
(`jev_interaction/harness.py`) and are next.

## Set it up with Claude Code

1. Install the package so that `jev-interaction` is on your PATH (Claude Code starts it):
   `pipx install "jev-interaction[server]"` or `uv tool install "jev-interaction[server]"`.
2. Add `JEV_HARNESS=1` to `.env` and run `jev-interaction serve` (port 8080: the plugin's hooks post there).
3. In Claude Code: `/plugin marketplace add native-bond-lab/Jev-Interaction`, then
   `/plugin install jev-voice@jev-interaction`.
4. Start Claude Code in your project with the channel on:
   `claude --dangerously-load-development-channels plugin:jev-voice@jev-interaction`
   and confirm "I am using this for local development". Channels are a research preview in Claude Code and this one is
   not on Anthropic's allowlist, which is why the flag is needed. On Team and Enterprise plans an admin has to enable
   channels.
5. Open http://localhost:8080, start a call, and ask for something: "can you run the tests and fix what fails?"

`GET /api/health` lists the harness sessions on the hub under `harness`.

## The pet

The call does not need the big page. `http://localhost:8080/pet` is the same call drawn as a pixel dog that stands on
two legs (`server/web/pet.js`, the personas `pet` and `pet_zh`), and `pet/` is a small floating window for it:

    cd pet && npm install && npm start

Click the dog to start. It perks its ears when it hears you, struts while a task runs, waves when the coding agent
needs your OK, and lies down when it sleeps. Click it (or Cmd/Ctrl+Shift+J) to put it to sleep or wake it.

## What happens

| you | what it does |
|---|---|
| ask for work by voice | the agent on the line writes `/task agent: ...`; the words arrive in Claude Code as a prompt |
| ask how it is going | it answers from what Claude Code is doing right now (each tool call is reported) |
| add something while it works | passed on; Claude Code takes it up when the turn it is on ends |
| Claude Code needs permission | you are told. With `JEV_VOICE_APPROVALS=1` your spoken allow or deny is passed back; without it you answer on your own screen, as always |
| Claude Code finishes | Claude writes a sentence or two to be said (its `say` tool) and you are told at a quiet moment |
| you typed a prompt in Claude Code yourself | if it runs longer than 30 seconds, you are told when it is done; a short one is left alone |
| nothing happens for 20 seconds | it sleeps: no question to Jev, no audio to the recognizer. Your voice or Claude Code's news wakes it |

## What Claude Code does not allow from outside

- A turn that is running cannot be interrupted. "Stop" drops the task on the voice's side; Claude Code finishes its turn.
- Words pushed while a turn runs wait for it to end.

## A connector for another harness

A connector opens `ws://127.0.0.1:8080/harness/ws` (from this machine only, never from a page), says
`{"type": "hello", "harness": "...", "cwd": "...", "steer": "now" | "turn"}`, and then exchanges the events listed at
the top of `jev_interaction/harness.py`.

## Checked, and not yet

Checked against Claude Code 2.1.280: the channel registers, a pushed prompt arrives as a turn, the hooks reach the hub,
and a turn that breaks off fails the task with its reason. Not checked yet with a signed-in session: Claude calling
`say`, the permission relay, and a whole spoken round trip.
