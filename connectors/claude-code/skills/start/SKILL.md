---
name: start
description: Start voice interaction. The user talks to a voice companion, and what they ask for out loud comes to this session.
disable-model-invocation: true
allowed-tools: mcp__plugin_interaction_jev__listen mcp__plugin_interaction_jev__say mcp__plugin_interaction_jev__stop
---

Voice interaction starts now. Call the `listen` tool of the `jev` server.

It returns what the user asked for out loud, with a task number. Do it as you would a typed request of theirs. When it
is done, call `say` with that task number and what to tell them: a sentence or two in plain spoken words, what matters
and nothing else. They are listening, not reading, so no code, no paths, no lists; the details stay on the screen.
Then call `listen` again.

Keep going this way: listen, do the work, say, listen. If `listen` answers that voice interaction did not start, tell
the user what it said and stop there. If the user asks to end voice interaction, call `stop`.
