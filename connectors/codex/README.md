# interaction: talk to Codex out loud

A Codex plugin. `$interaction` brings up a voice companion for the session you are in: it hears you, hands what you ask
for to the session, tells you how it is going and when it is done, and sleeps in between. `$interaction-stop` ends it.

- The session keeps working on its own model. The talking is done by a fast model of Codex's own that you choose the
  first time (the session asks you), on the account you are signed in to: no second key.
- Nothing to start beside Codex, and no page or window: the plugin's server brings the voice up on the computer's own
  microphone and speakers when the session first listens, and takes it down when the session ends.
- Speech recognition and synthesis are providers of your choice. None is chosen for you.

## Install

    pipx install "jev-interaction[server,local]"        # or: uv tool install "jev-interaction[server,local]"
    codex plugin marketplace add native-bond-lab/Jev-Interaction
    codex plugin add interaction@jev-interaction

Codex asks once whether to trust the plugin's hooks; they only tell the voice what the session is doing.

## The fast model

Pick one from Codex's own list (`/model`) that follows instructions well. The smallest one we tried chatted but never
handed a request to the session; the next ones up did, at about the same speed.

Setup and how it works: [docs/harness.md](../../docs/harness.md).
