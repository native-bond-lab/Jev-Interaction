# interaction: talk to DeepSeek Harness out loud

A DeepSeek Harness plugin. `/interaction` brings up a voice companion for the session you are in: it hears you, hands
what you ask for to the session, tells you how it is going and when it is done, and sleeps in between.
`/interaction stop` ends it.

- The session keeps working on its own model. The talking is done by a fast model of the harness's own that you choose
  the first time (`/interaction set JEV_FAST_MODEL=provider/model`), through the harness: no second key.
- Nothing to start beside the harness, and no page or window: the plugin starts the call server on a free port, on the
  computer's own microphone and speakers, and takes it down when the harness closes.
- Speech recognition and synthesis are providers of your choice. None is chosen for you.

## Install

    pipx install "jev-interaction[server,local]"        # or: uv tool install "jev-interaction[server,local]"
    dsh plugin --profile tui add <this folder>           # the same with --profile web for `dsh web`

The plugin is not on npm yet, so it is added from a checkout of this repository
(`connectors/deepseek-harness`). `dsh plugin add` puts it in the profile; nothing else is edited.

## The first time

`/interaction` says what is still to choose. Each is given with `/interaction set NAME=value` (several at once is
fine); a command is never sent to the model and this one is not written to the session log, so a key can be given
there, or put in `~/.jev-interaction/.env` by hand.

    /interaction set JEV_FAST_MODEL=deepseek-official/deepseek-flash
    /interaction set ASR_PROVIDER=... TTS_PROVIDER=...
    /interaction

Why a call did not start is in `~/.jev-interaction/server.log`.

Setup and how it works: [docs/harness.md](../../docs/harness.md).
