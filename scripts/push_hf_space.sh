#!/usr/bin/env bash
# Publish this repository to a Hugging Face Docker Space.
#
#   HF_TOKEN=hf_... ./scripts/push_hf_space.sh <owner>/<space-name>
#
# Copies the tracked files plus deploy/huggingface/README.md (the Space card) into a temporary folder and uploads it
# with huggingface_hub. Keys are never uploaded: set them as Space secrets in the Space settings.
set -euo pipefail
cd "$(dirname "$0")/.."
SPACE="${1:?usage: HF_TOKEN=... $0 <owner>/<space-name>}"
: "${HF_TOKEN:?set HF_TOKEN to a token with write access}"
TMP="$(mktemp -d)"
git ls-files -z | xargs -0 -I{} rsync -R "{}" "$TMP/"
cp deploy/huggingface/README.md "$TMP/README.md"
rm -rf "$TMP/.github" "$TMP/docs" "$TMP/tests"
python3 - "$SPACE" "$TMP" <<'PY'
import os, sys
from huggingface_hub import HfApi
space, folder = sys.argv[1], sys.argv[2]
api = HfApi(token=os.environ["HF_TOKEN"])
api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
api.upload_folder(repo_id=space, repo_type="space", folder_path=folder, commit_message="Publish Jev-Interaction")
print(f"https://huggingface.co/spaces/{space}")
PY
rm -rf "$TMP"
