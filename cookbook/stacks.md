# Stacks: which provider at each node

Jev-Interaction has four nodes you fill: the **judge** (Jev), the **language model**, **speech recognition** and the
**voice**. Nothing here picks them for you. The setups below are recommendations: the setup page and the bottom of
`.env.example` offer them to copy, and none is applied unless you choose it. A model field you leave empty uses the
provider's own default.

| node | what it decides | what matters most |
|---|---|---|
| judge | every turn-taking moment | answers in tens of milliseconds, one probability per choice |
| language model | the words | time to the first token; reasoning off |
| recognition | what the user said, while they say it | time to the first partial words; partials for unfinished speech |
| voice | how the words sound | time to first audio; whether it performs audio tags (`[laughs]`) |

## Recommended (global)

Proven at scale in our product.

```bash
JEV_API_KEY=...
LLM_BASE_URL=https://api.x.ai/v1
LLM_API_KEY=...
LLM_MODEL=grok-4.3
LLM_TEMPERATURE=0.7
ASR_PROVIDER=elevenlabs
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...
ELEVENLABS_ASR_MODEL=scribe_v3_live
ELEVENLABS_TTS_MODEL=eleven_v4_turbo
```

Why these:

- **Reasoning off.** A call cannot wait for a model to think. With reasoning on, grok-4.3 took about 8 s to its first
  word; off, well under a second. The adapter switches reasoning off wherever the provider has a switch.
- **Scribe v3 Live.** Same socket and settings as v2 realtime, but the first partial words arrive in about 0.3 s instead
  of about 1.9 s. Partial words matter here: the floor question is asked on the words so far, before a segment closes.
- **eleven_v4_turbo.** Fast, and it performs audio tags. With a voice like this, the language model is told to write
  `[laughs] ha`, `[whispers]` (`prompts/speech/audio_tags.md`); with other voices it writes plain spoken words.

## Recommended (mainland China)

One DashScope (Alibaba Cloud Bailian) key for all three nodes besides the judge.

```bash
JEV_API_KEY=...
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=...            # the DashScope key
LLM_MODEL=qwen-plus
ASR_PROVIDER=dashscope
TTS_PROVIDER=dashscope
DASHSCOPE_API_KEY=...
DASHSCOPE_ASR_MODEL=paraformer-realtime-v2
DASHSCOPE_TTS_MODEL=cosyvoice-v2
DASHSCOPE_TTS_VOICE=longxiaochun_v2
# HTTPS_PROXY=...          # only if api.typesafe.ai is slow from your network
```

CosyVoice does not perform audio tags, so the model writes plain words. Give each persona its own voice in its profile
(`voices: {dashscope: longcheng_v2}`), see [role policies](role-policies.md#voice).

## Your own language model

Any OpenAI-compatible chat endpoint works: OpenAI, DeepSeek, Qwen, Doubao, GLM, Kimi, OpenRouter, Groq, or a local
Ollama / vLLM server.

```bash
LLM_BASE_URL=http://localhost:11434/v1     # Ollama
LLM_MODEL=qwen2.5:14b
LLM_API_KEY=ollama
LLM_EXTRA_BODY={"top_p": 0.9}              # anything else the endpoint takes, as JSON
```

How fast the agent answers follows the model you plug in: the decisions take tens of milliseconds, the first words take
as long as the model's first token. Pick a model that writes short, spoken sentences; the responder asks for one or two.

## Swapping one node

- **One voice per persona** for this deployment: `TTS_VOICES="lyra=<voice id>,kai=<voice id>"`. It wins over the
  profile's `voices`.
- **A provider that is not listed**: write an adapter against the small protocol for that node and register it; it
  shows up on the setup page. See [docs/adapters.md](../docs/adapters.md).
- **The judge** is one protocol too (`ask(questions, state) -> probabilities`). Everything here was built and measured
  with Jev.

## A public demo

Every call is billed to your keys, so cap it:

```bash
MAX_CONCURRENT_CALLS=4
MAX_CALL_SECONDS=300
MAX_CALL_MINUTES_PER_DAY=300
MAX_WAITING_CALLS=20        # callers wait in line, first come first, when every line is taken
JEV_RECORD_CALLS=0          # no call logs
```

`scripts/push_hf_space.sh <owner>/<space>` publishes the repository as a Hugging Face Space with these as variables;
add the keys as Space secrets.
