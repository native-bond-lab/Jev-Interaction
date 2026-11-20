# jev-voice: Claude Code under your voice

A Claude Code plugin that puts the session on the hub of a running [Jev-Interaction](../../README.md) call server:

- a channel (`jev-interaction channel`, started by Claude Code) through which your spoken words arrive as prompts,
  Claude says things back with a `say` tool, and permission prompts are relayed;
- hooks that tell the call server what Claude Code is doing (a prompt typed, a tool about to run, the turn ended).

Setup and what to expect: [docs/harness.md](../../docs/harness.md).

The hooks post to `http://127.0.0.1:8080`. They only tell: none of them decides anything in Claude Code, and when the
call server is not running they fail at once and Claude Code carries on.
