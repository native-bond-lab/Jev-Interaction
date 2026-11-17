"""Start the isolated Doubao + DeepSeek + AmigosJev local test, without changing .env."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tools.local_voice_profile import PROFILE, activate, log_config  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=pathlib.Path, default=PROFILE)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--probe", action="store_true", help="Enable a separate prerecorded-speech browser test document")
    args = parser.parse_args()
    values = activate(args.profile)
    from jev_interaction.adapters import registry
    from jev_interaction.server import settings
    from jev_interaction.server.latency_config import snapshot

    # Settings edits in this page belong to its isolated profile, never the main .env.
    settings.ENV_FILE = args.profile.resolve()
    missing = registry.missing_settings()
    if missing:
        print(json.dumps({"ready": False, "missing_fields": missing}))
        return 1
    if registry.selected("asr") != "doubao" or registry.selected("tts") != "doubao":
        print(json.dumps({"ready": False, "reason": "Expected Doubao ASR and TTS in the private profile"}))
        return 1
    if args.check:
        print(json.dumps({"ready": True, "configuration": snapshot(), "direct": values.get("VOICE_TEST_DIRECT") == "1"}))
        return 0

    import uvicorn

    from jev_interaction.server.app import app

    if args.probe:
        from tools.voice_browser_fixture import install
        install(app, label="domestic")

    port = int(values.get("VOICE_TEST_PORT", "8083"))
    print(f"Domestic voice test: http://127.0.0.1:{port}/; call logs: runs/domestic-test/", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_config=log_config())
    return 0


if __name__ == "__main__":
    sys.exit(main())
