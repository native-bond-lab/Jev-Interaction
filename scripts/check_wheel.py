"""Check an installed jev-interaction, run from outside the repository (CI's `package` job): every file the package
reads at run time is in the install, and the pieces that read them work. The 0.2.0 wheel shipped without the speech
prompts and nothing noticed, because the tests run against the source tree.

    python scripts/check_wheel.py <version> <number of built-in profiles>
"""
import pathlib
import sys

import jev_interaction
from jev_interaction import Profile, preset
from jev_interaction.adapters import registry
from jev_interaction.server import paths

version, profiles = sys.argv[1], int(sys.argv[2])
root = pathlib.Path(jev_interaction.__file__).resolve().parent
assert "site-packages" in str(root), f"checking the source tree, not an install: {root}"
assert jev_interaction.__version__ == version, (jev_interaction.__version__, version)
for rel in ("prompts/system.md", "prompts/speech/audio_tags.md", "prompts/speech/plain.md", "server/web/index.html",
            "server/web/client.js", "py.typed"):
    assert (root / rel).is_file(), f"missing from the install: {rel}"
assert registry.speech_prompt("elevenlabs") and registry.speech_prompt("dashscope"), "speech prompts unreadable"
found = sorted(p.stem for p in (root / "profiles").glob("*.yaml"))
assert len(found) == profiles, (len(found), profiles)
assert all(Profile.load(pid).manner for pid in found) and "lyra" in paths.profiles()
assert preset("recommended").overlap_ask_ms == 400
print(f"ok: jev-interaction {version} from {root}, {len(found)} profiles, prompts and page present")
