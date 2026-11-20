"""SmartTurn v3.2 (pipecat-ai/smart-turn-v3, BSD-2-Clause): has the user finished, from the sound of their voice.

    pip install "jev-interaction[sound]"            # onnxruntime + huggingface_hub

One question about the last 8 s of audio, the pause so far included: the probability that the turn is over. It hears
what the words do not carry (the voice falling, a breath taken to go on, a word cut short) and knows nothing of what was
said; the turn decision weighs the two (Config.sound_rule, decisions/turn.py).

The CPU model (int8, about 8 MB) is downloaded from Hugging Face on first use into JEV_SOUND_CACHE and loaded in a
background thread; until it is ready, or without the packages, `score` returns None and the turn goes by the words.
The model's input is Whisper's log-mel spectrogram, computed here with numpy (the same numbers as transformers'
WhisperFeatureExtractor, which is not needed).
"""
from __future__ import annotations

import logging
import os
import pathlib
import threading

import numpy as np

log = logging.getLogger(__name__)
MODEL = os.getenv("JEV_SOUND_MODEL", "pipecat-ai/smart-turn-v3")
FILE = os.getenv("JEV_SOUND_FILE", "smart-turn-v3.2-cpu.onnx")
SR = 16000
WINDOW = 8 * SR                       # the model hears the last 8 s, left-padded with silence when shorter
N_FFT, HOP, N_MELS = 400, 160, 80


def _hz_to_mel(f):
    f = np.asarray(f, dtype=np.float64)
    return np.where(f >= 1000.0, 15.0 + np.log(np.maximum(f, 1e-10) / 1000.0) * (27.0 / np.log(6.4)), 3.0 * f / 200.0)


def _mel_to_hz(m):
    m = np.asarray(m, dtype=np.float64)
    return np.where(m >= 15.0, 1000.0 * np.exp(np.log(6.4) / 27.0 * (m - 15.0)), 200.0 * m / 3.0)


def mel_filters() -> np.ndarray:
    """(201, 80) Slaney-scale, Slaney-normalised triangular filters from 0 to 8 kHz, as Whisper's feature extractor."""
    fft_freqs = np.linspace(0, SR // 2, N_FFT // 2 + 1)
    edges = _mel_to_hz(np.linspace(_hz_to_mel(0.0), _hz_to_mel(SR / 2), N_MELS + 2))
    diff = np.diff(edges)
    slopes = edges[None, :] - fft_freqs[:, None]
    fb = np.maximum(0.0, np.minimum(-slopes[:, :-2] / diff[:-1], slopes[:, 2:] / diff[1:]))
    return fb * (2.0 / (edges[2:] - edges[:-2]))[None, :]


_FILTERS = mel_filters()
_WINDOW = np.hanning(N_FFT + 1)[:-1]  # periodic Hann


def features(audio: np.ndarray) -> np.ndarray:
    """(1, 80, 800) float32 model input for 16 kHz float audio: the last 8 s, left-padded with zeros, normalised to zero
    mean and unit variance, then Whisper's log-mel spectrogram."""
    x = np.asarray(audio, dtype=np.float32)[-WINDOW:]
    x = np.pad(x, (WINDOW - len(x), 0)).astype(np.float64)
    x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
    padded = np.pad(x, (N_FFT // 2, N_FFT // 2), mode="reflect")
    n = 1 + (len(padded) - N_FFT) // HOP
    frames = np.lib.stride_tricks.as_strided(padded, (n, N_FFT), (padded.strides[0] * HOP, padded.strides[0]))
    power = np.abs(np.fft.rfft(frames * _WINDOW, axis=1)) ** 2              # (frames, 201)
    log_mel = np.log10(np.maximum(1e-10, power @ _FILTERS)).T[:, :-1]       # (80, 800)
    log_mel = np.maximum(log_mel, log_mel.max() - 8.0)
    return ((log_mel + 4.0) / 4.0)[None].astype(np.float32)


class SmartTurn:
    """`score(pcm)`: p(the turn is over) for 16 kHz PCM16, or None while the model is not ready."""

    def __init__(self, model: str = MODEL, filename: str = FILE, cache: str | None = None):
        self.model_id, self.filename = model, filename
        self.cache = cache or os.getenv("JEV_SOUND_CACHE") or str(pathlib.Path.home() / ".cache" / "jev-interaction" / "sound")
        self.session = None
        self.error = ""
        self._lock = threading.Lock()
        self._started = False

    @property
    def name(self) -> str:
        return f"{self.model_id}/{self.filename}"

    def warm(self) -> None:
        """Start loading the model off the request path (once)."""
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._load, name="sound-turn-model", daemon=True).start()

    def _load(self) -> None:
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
            path = hf_hub_download(self.model_id, self.filename, cache_dir=self.cache)
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = max(1, min(2, os.cpu_count() or 1))
            opts.log_severity_level = 3
            self.session = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
            log.info("sound turn model ready: %s", self.name)
        except Exception as exc:  # noqa: BLE001 - calls go by the words alone
            self.error = f"{type(exc).__name__}: {str(exc)[:120]}"
            log.warning("sound turn model unavailable: %s", self.error)

    @property
    def ready(self) -> bool:
        return self.session is not None

    def score_audio(self, audio: np.ndarray) -> float | None:
        if self.session is None:
            return None
        out = self.session.run(None, {"input_features": features(audio)})[0]
        return float(np.asarray(out).reshape(-1)[0])

    def score(self, pcm: bytes) -> float | None:
        """p(the turn is over) for 16 kHz PCM16 (the last 8 s count), None while the model is not ready."""
        if self.session is None or not pcm:
            return None
        return self.score_audio(np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768)
