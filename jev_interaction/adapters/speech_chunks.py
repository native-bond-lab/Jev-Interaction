"""Release the first complete sentence before a model decides to write a newline.

Only the first spoken chunk gets the extra boundary: later chunks retain the model's line breaks so synthesis does
not turn a paragraph into many tiny requests. Never cut a word, a decimal, a common abbreviation or an audio tag.
"""
from __future__ import annotations

import re

from ..speaking import has_voice

_END = frozenset("。！？!?")
_CLOSE = frozenset('"\'”’»）)]}')
_ABBREVIATIONS = frozenset({"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "a.m", "p.m"})


class SpeechChunks:
    def __init__(self, mode: str = "newline"):
        if mode not in ("first_sentence", "newline"):
            raise ValueError("LLM_CHUNK_MODE must be first_sentence or newline")
        self.mode, self.buf, self.first = mode, "", True

    def _boundary(self) -> int | None:
        if self.mode == "newline":
            end = self.buf.find("\n")
            return end + 1 if end >= 0 else None
        tagged = False
        for i, char in enumerate(self.buf):
            if char == "[":
                tagged = True
            elif char == "]":
                tagged = False
            if tagged:
                continue
            if char == "\n":
                return i + 1
            if not self.first or self.mode == "newline" or char not in _END | {"."} or "<" in self.buf[:i]:
                continue
            if char == ".":
                # A period is ambiguous until the following character arrives. Be conservative with dotted words,
                # initials, numbered lists and ellipses rather than sending a fragment to a voice.
                before = self.buf[:i]
                if not before or before[-1].isdigit() or before[-1] == ".":
                    continue
                word = re.search(r"([A-Za-z]+(?:\.[A-Za-z]+)*)$", before)
                if word and (word[0].lower() in _ABBREVIATIONS or len(word[0]) == 1 or "." in word[0]):
                    continue
                if i + 1 < len(self.buf) and not (self.buf[i + 1].isspace() or self.buf[i + 1] in _CLOSE):
                    continue
            end = i + 1
            while end < len(self.buf) and self.buf[end] in _END | _CLOSE:
                end += 1
            if end == len(self.buf):
                continue  # keep a trailing quotation mark / punctuation run with its sentence, even across deltas
            if has_voice(self.buf[:end]):
                return end
        return None

    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        out = []
        while (end := self._boundary()) is not None:
            line, self.buf = self.buf[:end].strip(), self.buf[end:]
            if line:
                out.append(line)
                if has_voice(line):
                    self.first = False
        return out

    def finish(self) -> list[str]:
        line, self.buf = self.buf.strip(), ""
        return [line] if line else []
