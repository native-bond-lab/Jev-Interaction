#!/bin/sh
# Start the channel (`jev-interaction channel`) wherever jev-interaction was installed. Claude Code starts this with the
# PATH it was itself started with, which often lacks the folders pip, pipx and uv put commands in.
for c in "$JEV_INTERACTION_BIN" jev-interaction "$HOME/.local/bin/jev-interaction" /opt/homebrew/bin/jev-interaction \
         /usr/local/bin/jev-interaction "$HOME"/Library/Python/*/bin/jev-interaction "$HOME"/.pyenv/shims/jev-interaction; do
  if [ -n "$c" ] && command -v "$c" >/dev/null 2>&1; then exec "$c" channel "$@"; fi
done
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c "import jev_interaction.connectors.claude_code" 2>/dev/null; then
    exec "$py" -m jev_interaction.cli channel "$@"
  fi
done
echo 'jev-voice: jev-interaction was not found. Install it (pipx install "jev-interaction[server]"), or set JEV_INTERACTION_BIN to its path.' >&2
exit 127
