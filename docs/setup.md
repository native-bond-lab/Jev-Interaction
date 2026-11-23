[← README](../README.md) · [中文](setup.zh-CN.md)

# Setup

**Every node is your choice.** The language model is any OpenAI-compatible endpoint (xAI, OpenAI, DeepSeek, Qwen,
Doubao, GLM, Kimi, OpenRouter, Groq, a local Ollama or vLLM server); recognition and voice come from the provider
registry, and a third-party package can add its own ([docs/adapters.md](adapters.md)). The language model is told
how to write for the voice you pick: voices that perform audio tags (ElevenLabs v3/v4) get a style that uses
`[laughs]`, `[whispers]`; others get plain spoken words (`jev_interaction/prompts/speech/`).

**Recommended setups**, offered on the setup page and at the bottom of `.env.example`, never applied unless you choose them
(what each is good for, and how to swap one node: [cookbook/stacks.md](../cookbook/stacks.md)):

| | recommended (global), proven at scale in our product | recommended (mainland China) |
|---|---|---|
| judge | Jev | Bailian `decision-model-preview`, the same protocol (`JEV_PROVIDER=bailian`; what we measured: [cookbook](../cookbook/stacks.md#the-judge-on-the-mainland)) |
| language model | grok-4.3, reasoning off, temperature 0.7 | qwen-plus via DashScope |
| recognition | ElevenLabs Scribe v3 Live | Paraformer realtime v2 |
| voice | ElevenLabs eleven_v4_turbo (audio tags) | CosyVoice v2, per-persona voices (plain words) |
| keys | Jev, the language model (xAI), TTS (ElevenLabs; `TTS_API_KEY`) | one Bailian (DashScope) key |
| ready-made file | the bottom of `.env.example` | [`deploy/mainland-china.env`](../deploy/mainland-china.env): copy to `.env`, fill in two values |

**Presets.** `JEV_PRESET=recommended` (default) is the timing our product runs on today; `tested` adds the knobs
measured in [benchmarks.md](benchmarks.md); `default` is the library defaults. In code: `jev_interaction.preset("recommended", language="en")`
(`production`, its earlier name, still works). What each knob does: [cookbook/parameters.md](../cookbook/parameters.md).

**Hugging Face Space.** `HF_TOKEN=... ./scripts/push_hf_space.sh <owner>/<space>` publishes this repository as a Docker
Space ([card](../deploy/huggingface/README.md)); add the keys as Space secrets and the push sets `MAX_CONCURRENT_CALLS`,
`MAX_CALL_SECONDS` and `MAX_CALL_MINUTES_PER_DAY` as variables, since every call is billed to them.
