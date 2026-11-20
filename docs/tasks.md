# Background tasks and sleep

The agent on the line is the voice: it listens, talks and picks its moments. Work that takes longer than a breath is
handed to an executor and runs in the background while the call carries on.

```python
from jev_interaction import FunctionExecutor, Session

async def think(about, tell):
    await tell.progress("reading the thread")
    return await bigger_model(about)          # what came back, in words worth saying; "" for nothing

session = Session(profile, ..., executors={"think": FunctionExecutor(think, "a question that needs real thought")})
```

## What an executor is

Anything with `describe` (one sentence telling the responder what this kind of task is for) and
`async run(task, tell) -> str`:

| | |
|---|---|
| return a string | the task has come back with that; `""` means it found nothing |
| raise | the task failed; the record says why |
| be cancelled | the task was stopped (`/stop`, or the call ended) |
| `await tell.progress(text)` | how far it has got; shown to the agent with its next line, nothing is said for it |
| `await tell.ask(question)` | something only the user can answer (may I run this?); the agent asks them at a moment of its choosing and the answer is returned here |
| `async steer(task, text)` (optional) | more words from the user while it runs |

A memory lookup, a longer-thinking model and a search use `run` alone. A coding agent in another window (Claude Code,
Codex, DeepSeek Harness) uses all of it: it reports progress, asks for permission, and can be steered or stopped.

## What the responder does

The system prompt gains a paragraph (`prompts/tasks.md`) only when the session has executors. The responder writes a
line of its own that starts with a slash:

    /task <kind>: <what to do, in full>
    /tell <number>: <more for a running task, or the user's answer to what it asked>
    /stop <number>

Such a line is acted on, kept in the record as the agent's own, and never spoken.

## Where a task lives

On the call's one record (`ledger.py`). Each thing that happens to a task is an entry where it happened:

    (background task 1 started · agent: fix the login test)
    (background task 1 is waiting on the user · agent: fix the login test · it asks: May I delete the build folder?)
    (background task 1 has come back · agent: fix the login test
    The test passes now: the token expiry was off by one.)

The responder hears these like anything else on the call, and Jev reads them in the recent call. The bracketed line of
every reply lists what is still going and what has news not told yet:

    [pace: normal · event: they spoke · tasks: 1 agent "fix the login test" running 40 s, so far: "running the suite" · speak: English]

so the agent has the state in front of it every time it speaks, and the result cannot be lost by the user talking
over it: it is in the record whether or not it has been said.

## When the news is told

- Nobody is making a sound: the agent tells it, once the quiet has lasted `Config.task_report_after_s`.
- The user is talking, or the agent is: nothing is said over anyone. The news is in the record and in the line of the
  next reply, marked "not told yet".

## Sleep

A task unfinished and nobody making a sound for `Config.sleep_after_s`: the session sleeps. Asleep, no question goes
to Jev and no audio goes to the recognizer. It wakes on

- the user's voice: `Config.wake_voice_ms` of it in a row. The last `Config.sleep_preroll_ms` of audio is kept while
  asleep and heard on waking, so the first words are not lost. A sound with no words after it puts it back to sleep,
  with nothing asked;
- a task's news: it is told at once;
- the client: `{"type": "wake"}` (and `{"type": "sleep"}` to put it to sleep by hand).

The client is told with `sleep` and `wake` events ([protocol.md](protocol.md)).

## Not there yet

- Whether this is the moment to tell the news is a clock, not a question to Jev.
- The voiceprint is not consulted on waking: anyone's voice wakes it.
- The numbers are starting values; nothing here has been measured on recorded calls.
