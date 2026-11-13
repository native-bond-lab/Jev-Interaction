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
import pathlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

KINDS = {"judge": ("Judge", "法官 (Jev)"), "llm": ("Language model", "大模型"),
         "asr": ("Speech recognition", "语音识别"), "tts": ("Speech synthesis", "语音合成")}
SELECTOR = {"asr": "ASR_PROVIDER", "tts": "TTS_PROVIDER"}     # nodes with a choice of provider, and the setting that picks it
# Nodes with a single built-in provider use it; speech is the user's choice, never picked for them.
DEFAULT: dict[str, str | None] = {"judge": "jev", "llm": "openai-compatible", "asr": None, "tts": None}


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
    docs: str = ""                                    # where to get a key
    key_pattern: str = ""                             # a regex its keys match, to recognise a pasted key
    speech: Callable[[], str] | None = None           # tts: the speaking style its voices take (see speech_prompt)

    def missing(self) -> list[str]:
        need = lambda s: s.required() if callable(s.required) else s.required  # noqa: E731
        return [s.name for s in self.settings if need(s) and not os.getenv(s.name)]


_PROVIDERS: dict[tuple[str, str], Provider] = {}
_loaded_plugins = False


def register(kind: str, name: str, factory: Callable[..., Any], settings: list[Setting] | tuple = (), label: str = "",
             docs: str = "", key_pattern: str = "", speech: Callable[[], str] | None = None) -> Provider:
    """Add (or replace) a provider. `factory(**options)` builds it; options are node-specific (language=, voice=).
    A synthesizer's `speech()` names the speaking style its voices take: "plain", "audio_tags", or a style registered
    with register_style()."""
    if kind not in KINDS:
        raise ValueError(f"unknown node {kind!r}; one of {sorted(KINDS)}")
    p = Provider(kind, name, factory, list(settings), label or name, docs, key_pattern, speech)
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


def selected(kind: str) -> str | None:
    """The provider name chosen for a node: its selector setting, or the node's only built-in; None when not chosen."""
    if kind in SELECTOR:
        return (os.getenv(SELECTOR[kind]) or "").strip().lower() or DEFAULT[kind]
    return DEFAULT[kind]


class NotChosen(KeyError):
    """No provider picked for a node that needs a choice."""


def get(kind: str, name: str | None = None) -> Provider:
    _load_plugins()
    name = name or selected(kind)
    if not name:
        raise NotChosen(f"no {kind} provider chosen: set {SELECTOR[kind]} to one of "
                        f"{', '.join(p.name for p in providers(kind))}")
    try:
        return _PROVIDERS[(kind, name)]
    except KeyError:
        known = ", ".join(p.name for p in providers(kind)) or "none"
        raise KeyError(f"no {kind} provider {name!r} (registered: {known})") from None


def create(kind: str, name: str | None = None, **options) -> Any:
    return get(kind, name).factory(**options)


def missing_settings() -> list[str]:
    """Required settings that are empty for the providers chosen now, each named once (a node with no provider chosen
    reports its selector, e.g. TTS_PROVIDER)."""
    out: list[str] = []
    for kind in KINDS:
        if not selected(kind):
            out.append(SELECTOR[kind])
            continue
        for name in get(kind).missing():
            if name not in out:
                out.append(name)
    return out


# ---------------------------------------------------------------- speaking styles (per synthesizer)

_STYLE_DIR = pathlib.Path(__file__).resolve().parents[1] / "prompts" / "speech"
_STYLES: dict[str, str] = {}


def register_style(name: str, text: str) -> None:
    """A speaking style a plugin's synthesizer can name: the paragraph the language model reads about how to write
    for that voice (the tags it understands, what to leave out)."""
    _STYLES[name] = text.strip()


def speech_style(name: str | None = None) -> str:
    """The style the chosen (or named) synthesizer takes; "plain" when it names none or nothing is chosen."""
    try:
        p = get("tts", name)
    except KeyError:
        return "plain"
    return (p.speech() if p.speech else "") or "plain"


def speech_prompt(name: str | None = None) -> str:
    """The responder's paragraph on how to write for the chosen voice."""
    for style in (speech_style(name), "plain"):
        if style not in _STYLES and (_STYLE_DIR / f"{style}.md").exists():
            _STYLES[style] = (_STYLE_DIR / f"{style}.md").read_text(encoding="utf-8").strip()
        if style in _STYLES:
            return _STYLES[style]
    return ""


# ---------------------------------------------------------------- language-model endpoints and key recognition

@dataclass(frozen=True)
class Vendor:
    """An OpenAI-compatible endpoint the llm node can point at. `reference_model` is only a model we have run, shown as
    a reference; the page lists the vendor's own models from its /models route."""
    id: str
    label: str
    base_url: str
    key_pattern: str = ""
    docs: str = ""
    reference_model: str = ""
    local: bool = False

    def card(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "key_pattern" and (v not in ("", False) or k in ("id", "label", "base_url"))}


_SK = r"^sk-[A-Za-z0-9]{20,}$"                                       # the plain shape several vendors share
_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
LLM_VENDORS: list[Vendor] = [
    Vendor("xai", "xAI (Grok)", "https://api.x.ai/v1", r"^xai-", "console.x.ai", "grok-4.3"),
    Vendor("openai", "OpenAI", "https://api.openai.com/v1", r"^sk-(proj|svcacct|admin)-|" + _SK, "platform.openai.com/api-keys"),
    Vendor("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", r"^sk-or-", "openrouter.ai/keys"),
    Vendor("groq", "Groq", "https://api.groq.com/openai/v1", r"^gsk_", "console.groq.com/keys"),
    Vendor("deepseek", "DeepSeek", "https://api.deepseek.com/v1", _SK, "platform.deepseek.com"),
    Vendor("dashscope", "Alibaba Cloud Bailian (Qwen)", "https://dashscope.aliyuncs.com/compatible-mode/v1", _SK,
           "bailian.console.aliyun.com", "qwen-plus"),
    Vendor("dashscope-intl", "Alibaba Cloud Model Studio (international)",
           "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", _SK, "modelstudio.console.alibabacloud.com"),
    Vendor("moonshot", "Moonshot (Kimi)", "https://api.moonshot.cn/v1", _SK, "platform.moonshot.cn"),
    Vendor("volcengine", "Volcengine Ark (Doubao)", "https://ark.cn-beijing.volces.com/api/v3", _UUID, "console.volcengine.com/ark"),
    Vendor("byteplus", "BytePlus ModelArk", "https://ark.ap-southeast.bytepluses.com/api/v3", _UUID, "console.byteplus.com/ark"),
    Vendor("zhipu", "Zhipu (GLM)", "https://open.bigmodel.cn/api/paas/v4", r"^[0-9a-f]{32}\.[A-Za-z0-9]+$", "open.bigmodel.cn"),
    Vendor("ollama", "Ollama (on this machine)", "http://localhost:11434/v1", docs="ollama.com", local=True),
]


def detect(kind: str, key: str) -> list[dict]:
    """Whose key this looks like, most specific first: a guess from the key's shape, to be confirmed by a test call.
    Nothing is sent anywhere."""
    key = (key or "").strip()
    if not key:
        return []
    if kind == "llm":
        hits = [v for v in LLM_VENDORS if v.key_pattern and re.search(v.key_pattern, key)]
        distinctive = [v for v in hits if v.key_pattern not in (_SK, _UUID) and not (v.id == "openai" and re.fullmatch(_SK, key))]
        rest = [v for v in hits if v not in distinctive]
        return [v.card() for v in distinctive + rest]
    _load_plugins()
    return [{"id": p.name, "label": p.label} for p in providers(kind) if p.key_pattern and re.search(p.key_pattern, key)]


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


def _eleven_style() -> str:
    """eleven_v3 and v4 voices perform inline audio tags ([laughs], [whispers]); older models read them out."""
    return "audio_tags" if os.getenv("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo").startswith(("eleven_v3", "eleven_v4")) else "plain"


ELEVEN_KEY = Setting("ELEVENLABS_API_KEY", "ElevenLabs API key", "ElevenLabs 密钥", secret=True, required=True)
DASHSCOPE_KEY = Setting("DASHSCOPE_API_KEY", "DashScope API key", "百炼（DashScope）密钥", secret=True, required=True)
ELEVEN = {"docs": "elevenlabs.io/app/settings/api-keys", "key_pattern": r"^sk_[0-9a-f]{20,}$"}
DASHSCOPE = {"docs": "bailian.console.aliyun.com", "key_pattern": r"^sk-[0-9a-f]{20,}$"}

register("judge", "jev", _jev, [
    Setting("JEV_API_KEY", "Jev API key", "Jev 密钥", secret=True, required=True),
    Setting("JEV_MODEL", "Model", "模型", default="jev-latest")], label="Jev", docs="console.typesafe.ai")
register("llm", "openai-compatible", _openai_compat, [
    Setting("LLM_BASE_URL", "Endpoint (OpenAI-compatible)", "接口地址（兼容 OpenAI）", required=True),
    Setting("LLM_API_KEY", "API key", "密钥", secret=True, required=lambda: not _local_llm()),
    Setting("LLM_MODEL", "Model", "模型", required=True),
    Setting("LLM_TEMPERATURE", "Temperature", "温度", default="0.7")], label="OpenAI-compatible")
register("asr", "elevenlabs", _scribe, [
    ELEVEN_KEY, Setting("ELEVENLABS_ASR_MODEL", "Model", "模型", default="scribe_v3_live")], label="ElevenLabs Scribe", **ELEVEN)
register("asr", "dashscope", _paraformer, [
    DASHSCOPE_KEY, Setting("DASHSCOPE_ASR_MODEL", "Model", "模型", default="paraformer-realtime-v2")],
    label="Paraformer (Alibaba Cloud Bailian)", **DASHSCOPE)
register("tts", "elevenlabs", _eleven_tts, [
    ELEVEN_KEY, Setting("ELEVENLABS_VOICE_ID", "Voice ID", "音色 ID", required=True, hint="elevenlabs.io/app/voice-library"),
    Setting("ELEVENLABS_TTS_MODEL", "Model", "模型", default="eleven_v4_turbo")], label="ElevenLabs", speech=_eleven_style, **ELEVEN)
register("tts", "dashscope", _cosyvoice, [
    DASHSCOPE_KEY, Setting("DASHSCOPE_TTS_VOICE", "Voice", "音色", default="longxiaochun_v2"),
    Setting("DASHSCOPE_TTS_MODEL", "Model", "模型", default="cosyvoice-v2")], label="CosyVoice (Alibaba Cloud Bailian)", **DASHSCOPE)
