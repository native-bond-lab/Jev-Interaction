#!/usr/bin/env bash
# One-click local setup and start for Jev-Interaction.
#
#   ./scripts/setup.sh            global providers (xAI grok + ElevenLabs)
#   ./scripts/setup.sh --china    mainland-China providers (Alibaba Cloud Bailian: Qwen + Paraformer + CosyVoice),
#                                 and a domestic PyPI mirror
#   ./scripts/setup.sh --no-start set up only
#
# It creates .venv, installs the package, writes .env from the right template (asking for each key once; nothing is
# sent anywhere), then starts the server and opens http://localhost:8080.
set -euo pipefail
cd "$(dirname "$0")/.."

CHINA=0; START=1; PORT="${PORT:-8080}"
for a in "$@"; do
  case "$a" in
    --china) CHINA=1 ;;
    --no-start) START=0 ;;
    --port=*) PORT="${a#--port=}" ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
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

TEMPLATE=.env.example; [ "$CHINA" = 1 ] && TEMPLATE=.env.china.example
if [ ! -f .env ]; then
  say "Writing .env from $TEMPLATE"
  cp "$TEMPLATE" .env
fi

set_key() {   # set_key NAME value  (in .env, without printing the value)
  local k="$1" v="$2" tmp; tmp="$(mktemp)"
  awk -v k="$k" -v v="$v" 'BEGIN{d=0} $0 ~ "^"k"=" {print k"="v; d=1; next} {print} END{if(!d) print k"="v}' .env > "$tmp" && mv "$tmp" .env
}
ask_key() {   # ask_key NAME "prompt"  (only if empty in .env)
  local k="$1" p="$2" cur
  cur="$(grep -E "^$k=" .env | head -1 | cut -d= -f2- || true)"
  if [ -z "$cur" ] && [ -t 0 ]; then
    read -r -s -p "  $p: " val; echo
    [ -n "$val" ] && set_key "$k" "$val"
  fi
}

say "Keys (press Enter to skip any; edit .env later)"
ask_key JEV_API_KEY "Jev API key (typesafe.ai)"
if [ "$CHINA" = 1 ]; then
  ask_key DASHSCOPE_API_KEY "Alibaba Cloud Bailian / DashScope API key"
  dk="$(grep -E '^DASHSCOPE_API_KEY=' .env | cut -d= -f2- || true)"
  lk="$(grep -E '^LLM_API_KEY=' .env | cut -d= -f2- || true)"
  if [ -n "$dk" ] && [ -z "$lk" ] && grep -q '^LLM_BASE_URL=https://dashscope' .env; then set_key LLM_API_KEY "$dk"; fi
  ask_key LLM_API_KEY "LLM API key"
else
  ask_key LLM_API_KEY "LLM API key (xAI by default; any OpenAI-compatible endpoint, see .env)"
  ask_key ELEVENLABS_API_KEY "ElevenLabs API key"
  ask_key ELEVENLABS_VOICE_ID "ElevenLabs voice ID"
fi
chmod 600 .env

if [ "$START" = 1 ]; then
  URL="http://localhost:$PORT"
  say "Starting on $URL  (Ctrl+C to stop; use headphones, the built-in VAD is simple)"
  ( sleep 2; command -v open >/dev/null && open "$URL" || { command -v xdg-open >/dev/null && xdg-open "$URL"; } || true ) >/dev/null 2>&1 &
  exec .venv/bin/jev-interaction serve --host 127.0.0.1 --port "$PORT"
fi
say "Done. Start with: .venv/bin/jev-interaction serve --port $PORT"
