# interaction: talk to Claude Code out loud

A Claude Code plugin. `/interaction:start` brings up a voice companion for the session you are in: it hears you, hands
what you ask for to the session, tells you how it is going and when it is done, and sleeps in between.
`/interaction:stop` ends it.

- The session keeps working on its own model. The talking is done by a fast model of Claude Code's own that you choose
  the first time (the session asks you), or by another model of your choice.
- Nothing to start beside Claude Code, and no page or window: the plugin's server brings the voice up on the computer's
  own microphone and speakers when the session first listens, and takes it down when the session ends.
- The hooks only tell what the session is doing; none of them decides anything, except that a turn ending while voice
  interaction is on is sent back to listening.

Setup and how it works: [docs/harness.md](../../docs/harness.md).
