"""Kept for old instructions: the replay now lives in the package.  jev-interaction replay runs/*.jsonl --purpose floor"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from jev_interaction.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["replay", *sys.argv[1:]]))
