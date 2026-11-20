# jev-voice: Claude Code under your voice

A Claude Code plugin that puts the session on the hub of a running [Jev-Interaction](../../README.md) call server:

- a channel (`jev-interaction channel`, started by Claude Code) through which your spoken words arrive as prompts,
  Claude says things back with a `say` tool, and permission prompts are relayed;
- hooks that tell what Claude Code is doing (a prompt typed, a tool about to run, the turn ended) by calling the
  channel's own `hook` tool, so each event comes from the session it is about.

Setup and what to expect: [docs/harness.md](../../docs/harness.md).

The hooks only tell: none of them decides anything in Claude Code, and when the call server is not running the channel
answers them all the same and Claude Code carries on. The channel finds the call server by
itself (the server writes its address to `~/.jev-interaction/hub`); `JEV_INTERACTION_HUB` overrides it.
