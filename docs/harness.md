# Voice interaction inside a coding agent

You are in Claude Code. You run `/interaction:start`, and from then on you can talk, to the computer itself: a voice
companion hears you through its microphone, hands what you ask for to the session you are in, says how far it has got
when you ask, and tells you through its speakers when it is done. While nothing is happening it sleeps. There is no
page and no window.

    you  <— voice —>  the companion (a fast model talks)  <— tasks —>  your Claude Code session (its own model works)

Nothing is started beside the harness and nothing is configured outside it. The plugin's server, which Claude Code
starts with the session, brings the voice up on a free port the first time the session listens, and takes it down
when the session ends.

## Set it up in Claude Code

1. Install the package where Claude Code can find it: `pipx install "jev-interaction[server,local]"` or
   `uv tool install "jev-interaction[server,local]"`. The Claude Code command line has to be signed in (`claude`, then `/login`).
2. In Claude Code: `/plugin marketplace add native-bond-lab/Jev-Interaction`, then
   `/plugin install interaction@jev-interaction`.
3. Run `/interaction:start`.

The first time, the session asks you what to use, in Claude Code itself:

| | |
|---|---|
| the fast model that does the talking | Claude Code's own (`haiku`, for instance): no key, the account you are signed in to. Any OpenAI-compatible endpoint of your own can be chosen instead |
| speech recognition, speech synthesis | a provider each |

Nothing starts until the fast model is chosen. Keys are not typed into the conversation: the session names the file
they go in, `~/.jev-interaction/.env`, where their names are already waiting (the judge's, `JEV_API_KEY`, and the
speech provider's). What you choose is kept in the same file. Then the session listens, and you can talk.
`/interaction:stop` ends it, and so does pressing Esc while it is listening.

## The microphone and the speakers

The call is on the computer's own (`jev_interaction/local.py`), whichever are its defaults. A page in a browser has
echo cancellation and this has not: with speakers on, the microphone hears the companion's own voice. The engine raises
its bar for a voice while a line plays and drops recognized words that are its own; `JEV_LOCAL_ECHO=mute` in the `.env`
closes the microphone while a line plays instead (then you cannot talk over it). With headphones there is nothing to
cancel.

## How it works

`/interaction:start` puts the session in a loop of three tools of the plugin's server
(`jev_interaction/connectors/claude_code.py`):

| tool | |
|---|---|
| `listen` | waits for what you ask for out loud and gives it to the session, with a task number |
| `say` | the session's words for you to hear: the outcome, in a sentence or two |
| `stop` | ends voice interaction |
| `setup` | the first time: keeps what you chose |

The session does the work as it would a typed prompt, on its own model. The talking is done by the call server, on the
fast model (`adapters/claude_cli.py`: one `claude -p` kept open). Claude Code's hooks tell the call server what the
session is doing by calling a fourth tool the model never sees. If the session ends its turn while voice interaction
is on, it is sent back to listening.

## What happens

| you | what it does |
|---|---|
| ask for work by voice | the companion says it is on it and hands the task to the session through `listen` |
| ask how it is going | it answers from what the session is doing right now (each tool call is reported) |
| add something while it works | passed on; the session hears it when it next listens |
| the session needs permission | you are told, and answer on your own screen as always |
| the session finishes | it writes a sentence or two with `say`, and you are told at a quiet moment |
| you type a prompt yourself | it is done as usual; if it runs longer than 30 seconds you are told when it is done |
| nothing happens for a while | it may ask after you once; a minute after your last exchange, or sooner when you do not answer, it sleeps: no question to Jev, no audio to the recognizer. Your voice or the session's news wakes it |

## What Claude Code does not allow from outside

- A turn that is running cannot be interrupted by the voice. "Stop" drops the task on the voice's side; the session finishes its turn.
- A plugin cannot ask Claude Code for a model directly, which is why the talking goes through `claude -p` and needs the command line signed in.

## A connector for another harness

A connector joins the hub of the call server (`ws://127.0.0.1:<port>/harness/ws`, from this machine only, never from a
page; the server writes its address to `~/.jev-interaction/hub`), says
`{"type": "hello", "harness": "...", "cwd": "...", "steer": "now" | "turn"}`, and then exchanges the events listed at
the top of `jev_interaction/harness.py`.

## Checked, and not yet

Checked: the loop end to end with a stand-in for the session's model (a spoken request reached `listen`, `say` was
told, the call server stopped with the session); the first run (`listen` says what to choose, `setup` keeps it, the
keys' names wait in the file); the local call against the real stack with stand-ins for the two devices (a spoken
request recognized, lines decoded and played in order, talking over a line stops it); in Claude Code 2.1.280 the plugin
loads, both commands are there, its server connects; the talker reached the real `claude -p` and read its answer (an
error: not signed in).
Not checked yet: a real microphone and real speakers, echo included; and, for want of a signed-in command line, the
session itself running the loop and a reply spoken on Claude Code's own model.
