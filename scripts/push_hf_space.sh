#!/usr/bin/env bash
# Publish this repository to a Hugging Face Docker Space.
#
#   ./scripts/push_hf_space.sh <owner>/<space-name>      (uses `hf auth login`, or HF_TOKEN=hf_... with write access)
#
# Copies the tracked files plus deploy/huggingface/README.md (the Space card) into a temporary folder and uploads it
# with huggingface_hub. Keys are never uploaded: set them as Space secrets in the Space settings. On the first push the
# public-demo limits below are set as Space variables (change them in the Space settings; later pushes keep yours).
set -euo pipefail
cd "$(dirname "$0")/.."
SPACE="${1:?usage: $0 <owner>/<space-name>}"
TMP="$(mktemp -d)"
git ls-files -z | xargs -0 -I{} rsync -R "{}" "$TMP/"
cp deploy/huggingface/README.md "$TMP/README.md"
rm -rf "$TMP/.github" "$TMP/docs" "$TMP/tests"
python3 - "$SPACE" "$TMP" <<'PY'
import os, sys
from huggingface_hub import HfApi
space, folder = sys.argv[1], sys.argv[2]
api = HfApi(token=os.environ.get("HF_TOKEN") or None)
api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
LIMITS = {"JEV_RECORD_CALLS": "0", "MAX_CONCURRENT_CALLS": "2", "MAX_CALL_SECONDS": "180", "MAX_CALL_MINUTES_PER_DAY": "120"}
have = api.get_space_variables(space)
for name, value in LIMITS.items():
    if name not in have:
        api.add_space_variable(space, name, value)
api.upload_folder(repo_id=space, repo_type="space", folder_path=folder, commit_message="Publish Jev-Interaction")
print(f"https://huggingface.co/spaces/{space}")
PY
rm -rf "$TMP"
