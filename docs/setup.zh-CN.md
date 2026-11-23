[← README](../README.zh-CN.md) · [English](setup.md)

# 配置

**每个节点都由你选。** 大模型是任意兼容 OpenAI 接口的服务（xAI、OpenAI、DeepSeek、通义千问、豆包、智谱 GLM、Kimi、OpenRouter、Groq、本地 Ollama 或 vLLM）；识别和音色来自服务商注册表，第三方包也能注册自己的（[docs/adapters.md](adapters.md)）。大模型会按你选的音色调整写法：能演绎音频标签的音色（ElevenLabs v3/v4）用带 `[laughs]`、`[whispers]` 的写法，其他音色只写说出口的话（`jev_interaction/prompts/speech/`）。

**推荐配置**，在设置页面和 `.env.example` 末尾提供，只有你选了才会用（各自适合什么、怎么换掉其中一个节点：[cookbook/stacks.md](../cookbook/stacks.md)）：

| | 推荐（海外），在我们产品的规模化通话里验证过 | 推荐（中国大陆） |
|---|---|---|
| 法官 | Jev | 百炼 `decision-model-preview`，同一套协议（要设 `JEV_PROVIDER=bailian`；实测结果见 [cookbook](../cookbook/stacks.md#the-judge-on-the-mainland)） |
| 大模型 | grok-4.3，关闭思考，温度 0.7 | 通过百炼调用 qwen-plus |
| 语音识别 | ElevenLabs Scribe v3 Live | Paraformer realtime v2 |
| 音色 | ElevenLabs eleven_v4_turbo（音频标签） | CosyVoice v2，每个角色可配音色（纯文字） |
| 需要的密钥 | Jev、语言模型（xAI）、TTS（ElevenLabs；`TTS_API_KEY`） | 一把百炼（DashScope）密钥 |
| 现成的配置文件 | `.env.example` 末尾 | [`deploy/mainland-china.env`](../deploy/mainland-china.env)：复制成 `.env`，填两个值 |

**预设。** `JEV_PRESET=recommended`（默认）是我们产品现在用的时间参数；`tested` 在此基础上打开[测过的旋钮](benchmarks.zh-CN.md)；`default` 是库的默认值。代码里用 `jev_interaction.preset("recommended", language="zh")`（旧名 `production` 仍可用）。每个参数的作用见 [cookbook/parameters.md](../cookbook/parameters.md)。

**Hugging Face Space。** `HF_TOKEN=... ./scripts/push_hf_space.sh <owner>/<space>` 会把本仓库发布成 Docker Space（[说明](../deploy/huggingface/README.md)）；密钥放在 Space 的 secrets 里，首次发布会自动设好 `MAX_CONCURRENT_CALLS`、`MAX_CALL_SECONDS` 和每日总分钟数 `MAX_CALL_MINUTES_PER_DAY`，因为每通电话都按这些密钥计费。
