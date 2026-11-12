"""One table of providers per pipeline node, read by the server's factories, the health check and the settings page.

    from jev_interaction.adapters import registry
    asr = registry.create("asr", "dashscope", language="zh")

Each provider says how to build it and which environment settings it reads (with labels for the settings page and
whether they are secret or required). A third-party package registers its own providers through the entry-point group
`jev_interaction.adapters`: the entry point is a callable that receives this module and calls `register(...)`.

    [project.entry-points."jev_interaction.adapters"]
    my_asr = "my_package.jev:register"        # def register(registry): registry.register("asr", "mine", ...)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Callable

KINDS = {"judge": ("Judge", "法官 (Jev)"), "llm": ("Language model", "大模型"),
         "asr": ("Speech recognition", "语音识别"), "tts": ("Speech synthesis", "语音合成")}
SELECTOR = {"asr": "ASR_PROVIDER", "tts": "TTS_PROVIDER"}     # nodes with a choice of provider, and the setting that picks it
DEFAULT = {"judge": "jev", "llm": "openai-compatible", "asr": "elevenlabs", "tts": "elevenlabs"}


@dataclass(frozen=True)
class Setting:
    name: str
    label: str
    label_zh: str = ""
    secret: bool = False
    required: bool | Callable[[], bool] = False   # or a check made at the time (the LLM key is optional for a local server)
    default: str = ""
    hint: str = ""

    def card(self) -> dict:
        return {k: v for k, v in {"name": self.name, "label": self.label, "label_zh": self.label_zh or self.label,
                                  "secret": self.secret, "hint": self.hint}.items() if v not in ("", False) or k == "name"}


@dataclass
class Provider:
    kind: str
    name: str
    factory: Callable[..., Any]
    settings: list[Setting] = field(default_factory=list)
    label: str = ""

    def missing(self) -> list[str]:
        need = lambda s: s.required() if callable(s.required) else s.required  # noqa: E731
        return [s.name for s in self.settings if need(s) and not os.getenv(s.name)]


_PROVIDERS: dict[tuple[str, str], Provider] = {}
_loaded_plugins = False


def register(kind: str, name: str, factory: Callable[..., Any], settings: list[Setting] | tuple = (), label: str = "") -> Provider:
    """Add (or replace) a provider. `factory(**options)` builds it; options are node-specific (language=, voice=)."""
    if kind not in KINDS:
        raise ValueError(f"unknown node {kind!r}; one of {sorted(KINDS)}")
    p = Provider(kind, name, factory, list(settings), label or name)
    _PROVIDERS[(kind, name)] = p
    return p


def _load_plugins() -> None:
    global _loaded_plugins
    if _loaded_plugins:
        return
    _loaded_plugins = True
    import sys
    for ep in entry_points(group="jev_interaction.adapters"):
        ep.load()(sys.modules[__name__])


def providers(kind: str) -> list[Provider]:
    _load_plugins()
    return [p for (k, _), p in _PROVIDERS.items() if k == kind]


def selected(kind: str) -> str:
    """The provider name chosen for a node: its selector setting, or the default."""
    return os.getenv(SELECTOR[kind], DEFAULT[kind]).lower() if kind in SELECTOR else DEFAULT[kind]


def get(kind: str, name: str | None = None) -> Provider:
    _load_plugins()
    name = name or selected(kind)
    try:
        return _PROVIDERS[(kind, name)]
    except KeyError:
        known = ", ".join(p.name for p in providers(kind)) or "none"
        raise KeyError(f"no {kind} provider {name!r} (registered: {known})") from None


def create(kind: str, name: str | None = None, **options) -> Any:
    return get(kind, name).factory(**options)


def missing_settings() -> list[str]:
    """Required settings that are empty for the providers chosen now, each named once."""
    out: list[str] = []
    for kind in KINDS:
        for name in get(kind).missing():
            if name not in out:
                out.append(name)
    return out


# ---------------------------------------------------------------- built-in providers

def _scribe(language: str = "en", **_):
    from .scribe import ScribeRealtime
    return ScribeRealtime(language=language)


def _paraformer(language: str = "zh", **_):
    from .dashscope_asr import ParaformerRealtime
    return ParaformerRealtime(language=language)


def _eleven_tts(voice: str | None = None, **_):
    from .elevenlabs_tts import ElevenLabsTTS
    return ElevenLabsTTS(voice_id=voice)


def _cosyvoice(voice: str | None = None, **_):
    from .dashscope_tts import CosyVoiceTTS
    return CosyVoiceTTS(voice=voice)


def _openai_compat(**options):
    from .openai_compat import OpenAICompatResponder
    return OpenAICompatResponder(**options)


def _jev(**options):
    from ..judge import JevClient
    return JevClient(**options)


def _local_llm() -> bool:
    return any(h in os.getenv("LLM_BASE_URL", "") for h in ("localhost", "127.0.0.1", "0.0.0.0"))


ELEVEN_KEY = Setting("ELEVENLABS_API_KEY", "ElevenLabs API key", "ElevenLabs 密钥", secret=True, required=True)
DASHSCOPE_KEY = Setting("DASHSCOPE_API_KEY", "DashScope API key", "百炼（DashScope）密钥", secret=True, required=True,
                        hint="bailian.console.aliyun.com")

register("judge", "jev", _jev, [
    Setting("JEV_API_KEY", "Jev API key", "Jev 密钥", secret=True, required=True, hint="console.typesafe.ai"),
    Setting("JEV_MODEL", "Model", "模型", default="jev-latest")], label="Jev")
register("llm", "openai-compatible", _openai_compat, [
    Setting("LLM_BASE_URL", "Endpoint (OpenAI-compatible)", "接口地址（兼容 OpenAI）", default="https://api.x.ai/v1"),
    Setting("LLM_API_KEY", "API key", "密钥", secret=True, required=lambda: not _local_llm()),
    Setting("LLM_MODEL", "Model", "模型", default="grok-4.3"),
    Setting("LLM_TEMPERATURE", "Temperature", "温度", default="0.7")], label="OpenAI-compatible")
register("asr", "elevenlabs", _scribe, [
    ELEVEN_KEY, Setting("ELEVENLABS_ASR_MODEL", "Model", "模型", default="scribe_v2_realtime_turbo")], label="ElevenLabs Scribe")
register("asr", "dashscope", _paraformer, [
    DASHSCOPE_KEY, Setting("DASHSCOPE_ASR_MODEL", "Model", "模型", default="paraformer-realtime-v2")], label="Paraformer (阿里云百炼)")
register("tts", "elevenlabs", _eleven_tts, [
    ELEVEN_KEY, Setting("ELEVENLABS_VOICE_ID", "Voice ID", "音色 ID", required=True, hint="elevenlabs.io/app/voice-library"),
    Setting("ELEVENLABS_TTS_MODEL", "Model", "模型", default="eleven_v4_turbo")], label="ElevenLabs")
register("tts", "dashscope", _cosyvoice, [
    DASHSCOPE_KEY, Setting("DASHSCOPE_TTS_VOICE", "Voice", "音色", default="longxiaochun_v2"),
    Setting("DASHSCOPE_TTS_MODEL", "Model", "模型", default="cosyvoice-v2")], label="CosyVoice (阿里云百炼)")
