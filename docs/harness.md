# Voice interaction inside a coding agent

You are in Claude Code (or DeepSeek Harness, where the command is `/interaction`, or Codex, where it is `$interaction`). You run `/interaction:start`, and from then on you can talk, to the computer itself: a voice
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
| speech recognition, speech synthesis | a provider each, from the ones the engine has adapters for (ElevenLabs, Alibaba Cloud Bailian, or any OpenAI-compatible speech endpoint, your own machine's included: [adapters.md](adapters.md)), and what that provider needs: a voice, a model, an address |

None is chosen for you.

Nothing starts until the fast model is chosen. Keys are not typed into the conversation: the session names the file
they go in, `~/.jev-interaction/.env`, where their names are already waiting (the judge's, `JEV_API_KEY`, and the
speech provider's). What you choose is kept in the same file. Then the session listens, and you can talk.
`/interaction:stop` ends it, and so does pressing Esc while it is listening.

## Set it up in DeepSeek Harness

1. Install the package: `pipx install "jev-interaction[server,local]"` or `uv tool install "jev-interaction[server,local]"`.
2. Add the plugin to the profile you use, from a checkout of this repository (it is not on npm yet):
   `dsh plugin --profile tui add <path>/connectors/deepseek-harness` (`--profile web` for `dsh web`).
3. In a session: `/interaction`. `/interaction stop` ends it.

The first time, `/interaction` says what is still to choose, and each is given with `/interaction set NAME=value`:
the fast model that does the talking, as `provider/model` of the harness's own (`JEV_FAST_MODEL`), a provider for
speech recognition and one for synthesis, and their keys. A command is not sent to the model and this one is not
written to the session log; the keys can be put in `~/.jev-interaction/.env` by hand as well. None is chosen for you.

Here the harness gives more than Claude Code does (`connectors/deepseek-harness/index.js`): the plugin asks the
harness for a model directly, so each reply of the voice is written by the harness on the fast model
(`LLM_PROVIDER=harness`: the call server asks, the plugin answers with `ctx.llm.stream`); a spoken request becomes a
prompt of the session, something added while it works reaches the turn at its next step, and "stop" stops the turn.

## Set it up in Codex

1. Install the package: `pipx install "jev-interaction[server,local]"` or `uv tool install "jev-interaction[server,local]"`.
   Codex has to be signed in (the desktop app's sign-in counts; its command line is found inside the app).
2. `codex plugin marketplace add native-bond-lab/Jev-Interaction`, then `codex plugin add interaction@jev-interaction`.
3. In a session: `$interaction`. `$interaction-stop` ends it.

Codex's plugins have the same shape as Claude Code's (skills, an MCP server, hooks that call a tool of it), so this is
the same server (`jev-interaction connect codex`) and the same loop of `listen`, the work, `say`. Two things differ.
The talking is done by one `codex app-server` kept open for the call (`adapters/codex_cli.py`, `LLM_PROVIDER=codex`):
a thread on the fast model you chose, with nothing of the coding agent left on, about 1.2 s to the first words of a
reply (the greeting of a call takes about 10 s: the process connecting). And the fast model matters: the smallest one
in Codex's list chatted but never handed a request to the session; the next ones up did.

## The microphone and the speakers

The call is on the computer's own (`jev_interaction/local.py`), whichever are its defaults. A page in a browser has
echo cancellation and this has not: with speakers on, the microphone hears the companion's own voice. The engine raises
its bar for a voice while a line plays, and drops words recognized while a line plays or within three seconds after it
that are mostly the line's own (`Config.echo_tail_s`, `echo_same`). On a MacBook's own speakers and microphone that
was enough: its lines coming back were dropped, a spoken request was heard and talking over a line stopped it. What
still gets through is a stretch the recognizer closes with its words and yours in one piece. `JEV_LOCAL_ECHO=mute` in
the `.env` closes the microphone while a line plays instead (then you cannot talk over it), and `JEV_LOCAL_MIC` /
`JEV_LOCAL_SPEAKER` name other devices than the defaults. With headphones there is nothing to cancel.

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
`{"type": "hello", "harness": "...", "cwd": "...", "steer": "now" | "turn", "talks": true | false}`, and then
exchanges the events listed at the top of `jev_interaction/harness.py`. `talks` says the harness lends its model for
the talking: the call server then sends `talk` (a system prompt, the messages, a model) and reads the reply back as
`talk_line`s and a `talk_end`. `GET /harness/setup` says what is still to choose, for a connector to put to its user.

## Checked, and not yet

Checked: the loop end to end with a stand-in for the session's model (a spoken request reached `listen`, `say` was
told, the call server stopped with the session); the first run (`listen` says what to choose, `setup` keeps it, the
keys' names wait in the file); the local call against the real stack with stand-ins for the two devices (a spoken
request recognized, lines decoded and played in order, talking over a line stops it); in Claude Code 2.1.280 the plugin
loads, both commands are there, its server connects; the talker reached the real `claude -p` and read its answer (an
error: not signed in).
Checked out loud on a MacBook's own speakers and microphone as well (see above).

And with a signed-in Claude Code 2.1.280, the whole of it: `/interaction:start` typed in a session, the session called
`listen` and the voice came up; the greeting and every line after it were spoken on Claude Code's own model (`haiku`,
about 2.2 s to a first line here; the first of a call takes about 8 s, the command line starting); a spoken request
("count the files in this folder") reached the session, which ran its command, said the outcome with `say`, and the
companion told it: three files, which was right. Run several times over on 2.1.323 as well, which turned up what a
real session does differently from the stand-in: it sends `say` and `listen` in one step, names the words of `say`
`message` as often as `text`, and the talking model now and then writes its `/task` line as a tool call. All three
are taken as they come.

And in DeepSeek Harness 0.2.2-rc.5 (`dsh web`, the plugin added with `dsh plugin --profile web add`, the harness's
model here xAI's `grok-4.3` since no DeepSeek key was at hand): `/interaction` is in the command list; the first run
said what to choose and `/interaction set` kept it; a synthetic voice into the call asked to count the files in the
folder, the reply was written by the harness's model, the request arrived in the session as a prompt, each tool call
was reported, and the outcome was told (about 6 s from the request being recognized to the first words, 24 s to the
outcome). Not checked there: the call on real speakers and microphone (the engine's side is the same as Claude
Code's), `dsh` in the terminal (`--profile tui`), a DeepSeek model doing the talking, steering and stopping a turn
by voice, a permission prompt.

And in Codex (codex-cli 0.163, the one inside the desktop app, signed in): the plugin installs from this repository's
marketplace and its server is listed; `codex exec '$interaction'` put a session in the loop; a synthetic voice asked
to count the files in the folder, the reply was written by Codex's own fast model (1.7 s to the first words), the
request reached the session, it ran its command, said the outcome with `say`, and the companion told it: three files,
which was right; the session went back to listening. Not checked there: the hooks (Codex runs a plugin's hooks only
once the user has trusted them, which a run without a person cannot do), so progress while a task runs, the report of
a typed prompt and the Stop hook that keeps the loop; the interactive window and the desktop app; the call on real
speakers and microphone.

## What is open

For whoever picks this up. Each of these was seen on a real run or is a known gap, not a guess.

| | |
|---|---|
| it is slow to answer | per reply: the talking model's first line (about 2.2 s here, through a proxy) plus the synthesizer's first bytes (about 1.9 s). The first reply of a call adds the command line starting, about 8 s: `claude -p` could be started when the call server starts rather than at the first line. A provider near the user is the rest |
| echo, with speakers | handled by dropping words that are mostly its own (`Config.echo_tail_s`); a stretch the recognizer closes with its words and the user's in one piece still gets through. Real echo cancellation (the OS's voice processing, or a WebRTC one fed what is played) is not there |
| the talking model | it sometimes says it will try again without writing the `/task` line; once in a while it writes its planning out, which is then spoken (it is told that everything it writes is said, `adapters/claude_cli.py`); it wrote `/task` as a tool call a few times (taken as it comes, `tasks.action`) |
| when the news is told | a clock (`Config.task_report_after_s`), not a question to Jev. The sleep and echo numbers are starting values too; none has been tuned on recorded calls |
| permission prompts | told to the user, answered on their screen. Answering by voice (the `PermissionRequest` hook can decide) is not wired |
| stopping a task | Claude Code cannot be interrupted from outside: "stop" only drops the task on the voice's side |
| other voices in the room | the local call has no voiceprint on; anyone's voice is heard and wakes it |
| the generic speech adapters | `openai-compatible` recognition and synthesis are tested against a stand-in only, with no real service yet |
| other harnesses | Codex's is checked without its hooks and outside the interactive window; DeepSeek Harness's in `dsh web` only, and it is not on npm. The hub's protocol for another one is at the top of `harness.py` |
| the fast model | it has to follow the `/task` convention: Codex's smallest did not. Nothing checks this at setup; a test line at first run could |
| other systems | checked on macOS only (`bin/connect.sh` is a shell script; the audio is miniaudio's) |

To see what a session really does, in what order: `JEV_CONNECT_LOG=/tmp/connect.log` in Claude Code's environment
writes every tool call the plugin's server gets and what it answered.
