#!/usr/bin/env bash
# One-click local setup and start for Jev-Interaction.
#
#   ./scripts/setup.sh            install, start, open the page
#   ./scripts/setup.sh --china    the same through a domestic PyPI mirror
#   ./scripts/setup.sh --no-start install only
#
# It creates .venv, installs the package, then starts the server and opens http://localhost:8080, where the setup steps
# ask for each provider and key (saved to .env on this machine; nothing is sent anywhere else).
set -euo pipefail
cd "$(dirname "$0")/.."

CHINA=0; START=1; PORT="${PORT:-8080}"
for a in "$@"; do
  case "$a" in
    --china) CHINA=1 ;;
    --no-start) START=0 ;;
    --port=*) PORT="${a#--port=}" ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
  esac
done

say() { printf "\033[1;36m›\033[0m %s\n" "$*"; }

PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "Python 3.10+ is required (https://www.python.org/downloads/)"; exit 1; }

if [ ! -d .venv ]; then say "Creating .venv with $PY"; "$PY" -m venv .venv; fi
PIP_ARGS=()
if [ "$CHINA" = 1 ]; then PIP_ARGS=(-i "${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"); fi
say "Installing dependencies"
.venv/bin/python -m pip install -q --upgrade pip ${PIP_ARGS[@]+"${PIP_ARGS[@]}"}
.venv/bin/python -m pip install -q -e ".[server]" ${PIP_ARGS[@]+"${PIP_ARGS[@]}"}

if [ ! -f .env ]; then
  say "Writing .env (empty: the page walks you through each provider and key)"
  cp .env.example .env
fi
chmod 600 .env

if [ "$START" = 1 ]; then
  URL="http://localhost:$PORT"
  say "Starting on $URL  (Ctrl+C to stop; use headphones, the built-in VAD is simple)"
  ( sleep 2; command -v open >/dev/null && open "$URL" || { command -v xdg-open >/dev/null && xdg-open "$URL"; } || true ) >/dev/null 2>&1 &
  exec .venv/bin/jev-interaction serve --host 127.0.0.1 --port "$PORT"
fi
say "Done. Start with: .venv/bin/jev-interaction serve --port $PORT"
