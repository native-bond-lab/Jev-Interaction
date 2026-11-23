---
name: "interaction"
description: "Start voice interaction: the user talks out loud, and what they ask for comes to this session. Use only when the user asks for it by name ($interaction, /interaction, \"start voice interaction\")."
---

Voice interaction starts now. Call the `listen` tool of the `jev` server.

It returns what the user asked for out loud, with a task number. Do it as you would a typed request of theirs. When it
is done, call `say` with that task number and what to tell them: a sentence or two in plain spoken words, what matters
and nothing else. They are listening, not reading, so no code, no paths, no lists; the details stay on the screen.
When `say` has answered, call `listen` again. One after the other, never in the same step: `listen` waits, and what is
sent along with it does not run until it returns.

Keep going this way: listen, do the work, say, listen. If the user asks to end voice interaction, call `stop`.

The first time, `listen` answers that voice interaction is not set up yet and says what has to be chosen. Ask the user
those choices, call `setup` with what they chose, and call `listen` again. Keys are never typed here: `listen` names the
file they go in, and you tell the user that. If `listen` answers that it did not start for another reason, tell the
user what it said and stop there.
