"""Every decision is written down: the state Jev read, the questions, the probabilities, what was done.

A call's log is one JSON line per event. tools/replay.py re-asks the recorded questions, as asked or reworded, which is how
a wording change is checked against real calls before it ships.
"""
from __future__ import annotations

import json
import pathlib
import time


class Recorder:
    def __init__(self, path: str | pathlib.Path | None):
        self.f = None
        if path:
            p = pathlib.Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self.f = p.open("a", encoding="utf-8")

    def write(self, event: str, **data):
        if self.f:
            self.f.write(json.dumps({"t": round(time.time(), 3), "event": event, **data}, ensure_ascii=False, default=str) + "\n")
            self.f.flush()

    def close(self):
        if self.f:
            self.f.close()
            self.f = None
