"""sherpa-onnx: offline streaming recognition that is actually good at Chinese, no key and no account.

Vosk's small Mandarin model gets about five characters out of a sentence — enough to make a call answer nonsense. This
recognizer (a streaming Zipformer trained on Chinese and English) is the same kind of offline model but far more accurate,
and still runs on the CPU in real time.

The model folder is `sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20` (about 490 MB, downloaded once) under
`~/.jev-interaction/models/`. `SHERPA_MODEL_DIR` picks another folder.
"""
from __future__ import annotations

import asyncio
import os
import pathlib

from .base import Segment

DEFAULT_MODEL = "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"


def model_dir() -> pathlib.Path:
    """The model folder: SHERPA_MODEL_DIR, the call's home, or the user's own ~/.jev-interaction (a throwaway home still
    finds the model the machine has)."""
    chosen = os.getenv("SHERPA_MODEL_DIR", "").strip()
    if chosen:
        return pathlib.Path(chosen).expanduser()
    mine = pathlib.Path.home() / ".jev-interaction" / "models" / DEFAULT_MODEL
    home = os.getenv("JEV_HOME")
    if home:
        asked = pathlib.Path(home) / "models" / DEFAULT_MODEL
        return asked if asked.exists() else mine
    return mine


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _pick(folder: pathlib.Path, pattern: str) -> str:
    """The float32 model file when present (more accurate), else the int8 one."""
    found = sorted(folder.glob(pattern))
    if not found:
        raise RuntimeError(f"no {pattern} in {folder}")
    plain = [f for f in found if ".int8." not in f.name]
    return str((plain or found)[0])


class SherpaRealtime:
    def __init__(self, language: str = "zh"):
        self.language = language
        self.error: Exception | None = None
        self.closed = False
        self.finished = False
        self.queue: asyncio.Queue = asyncio.Queue()
        self._pcm: asyncio.Queue = asyncio.Queue(maxsize=600)
        self._recognizer = None
        self._stream = None
        self._worker: asyncio.Task | None = None
        self._partial = ""

    async def connect(self) -> None:
        where = model_dir()
        if not where.exists():
            raise RuntimeError(f"sherpa-onnx model not found at {where}; download "
                               f"{DEFAULT_MODEL} into ~/.jev-interaction/models/ or set SHERPA_MODEL_DIR")
        import sherpa_onnx  # noqa: PLC0415 - only imported when this provider is used

        def load():
            return sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(where / "tokens.txt"),
                encoder=_pick(where, "encoder*.onnx"),
                decoder=_pick(where, "decoder*.onnx"),
                joiner=_pick(where, "joiner*.onnx"),
                num_threads=2,
                sample_rate=16000,
                feature_dim=80,
                decoding_method="greedy_search",
                enable_endpoint_detection=True,
                # A sentence is closed on a short pause, but not on every breath: 0.6/0.4 cut normal Chinese into halves,
                # and 0.8 still split "换个方向" from the rest of the same remark. 1.1 s keeps one remark together; the
                # session waits a little longer too (merge_gap_ms) when Jev is unsure.
                rule1_min_trailing_silence=_env_float("SHERPA_TRAILING_S", 1.1),
                rule2_min_trailing_silence=_env_float("SHERPA_TRAILING_S", 1.1),
                rule3_min_utterance_length=25.0,
            )

        if self._recognizer is None:
            self._recognizer = await asyncio.to_thread(load)      # loading takes a second: off the loop
        self._stream = self._recognizer.create_stream()
        self.closed, self.finished, self.error = False, False, None
        self._worker = asyncio.create_task(self._run())

    async def restart(self) -> None:
        await self.close(final=False)
        await self.connect()

    async def close(self, final: bool = True) -> None:
        if self.closed:
            return
        self.closed, self.finished = True, final
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None
        self._stream = None
        while not self._pcm.empty():
            self._pcm.get_nowait()
        if final:
            if self.queue.full():
                self.queue.get_nowait()
            self.queue.put_nowait(None)

    async def send(self, pcm: bytes) -> None:
        if self.closed or self._stream is None:
            raise RuntimeError("sherpa-onnx recognizer is not connected")
        if self._pcm.full():
            try:
                self._pcm.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self._pcm.put_nowait(pcm)

    async def segments(self):
        while (segment := await self.queue.get()) is not None:
            yield segment
        if self.error is not None:
            raise self.error

    # ------------------------------------------------------------------ the worker
    async def _run(self) -> None:
        try:
            while not self.closed:
                pcm = await self._pcm.get()
                answer = await asyncio.to_thread(self._accept, pcm)
                if answer is None:
                    continue
                text, final = answer
                if final:
                    self._partial = ""
                    self.queue.put_nowait(Segment(text, final=True))
                elif text and text != self._partial:
                    self._partial = text
                    self.queue.put_nowait(Segment(text, final=False))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - handed to the consumer, as the streaming recognizers do
            self.error = RuntimeError(f"sherpa-onnx recognition failed ({type(exc).__name__}: {str(exc)[:160]})")

    def _accept(self, pcm: bytes):
        """One frame in the worker thread: None, or (text, final)."""
        import numpy as np

        recognizer, stream = self._recognizer, self._stream
        if recognizer is None or stream is None:
            return None
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        stream.accept_waveform(16000, samples)
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        text = (recognizer.get_result(stream) or "").strip()
        if recognizer.is_endpoint(stream):
            recognizer.reset(stream)
            return (text, True) if text else None
        return (text, False) if text else None
