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
JEV_URL=https://api.typesafe.ai/v1/systemone      # the default, as is the next line
JEV_TURN_QUESTION=engine
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

One Alibaba Cloud Bailian key for all four nodes: its decision model as the judge, Qwen, Paraformer and CosyVoice.

```bash
JEV_API_KEY=...            # the Bailian key
JEV_URL=https://<your-workspace-id>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/systemone
JEV_MODEL=decision-model-preview
JEV_TURN_QUESTION=last_words
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=...            # the same key
LLM_MODEL=qwen-plus
ASR_PROVIDER=dashscope
TTS_PROVIDER=dashscope
DASHSCOPE_API_KEY=...
DASHSCOPE_ASR_MODEL=paraformer-realtime-v2
DASHSCOPE_TTS_MODEL=cosyvoice-v2
DASHSCOPE_TTS_VOICE=longxiaochun_v2
```

CosyVoice does not perform audio tags, so the model writes plain words. Give each persona its own voice in its profile
(`voices: {dashscope: longcheng_v2}`), see [role policies](role-policies.md#voice).

### The judge on the mainland

`api.typesafe.ai` does not serve requests from mainland networks (HTTP 451 when we measured, November 2026), so a
mainland deployment needs another judge. Several services now speak the same protocol (a state, typed questions, a
probability per choice back); `JEV_URL`, `JEV_MODEL` and `JEV_HEADERS` point the engine at one.

- **Bailian `decision-model-preview`** is the one we recommend there. The endpoint is your workspace's own address: the
  `llm-…` host shown as *API Host* when you create a key, with `/compatible-mode/v1/systemone` after it, and the key
  must belong to that workspace. It is a preview: free when we measured, and it rate-limited us above two requests at
  once.
- It needs **`JEV_TURN_QUESTION=last_words`**. With the engine's own wording of "have they finished" its answers sit on
  one side whatever the user said (nearly every Chinese pause read as finished). `last_words` sends the same state as
  an object with the user's words in a field of their own, asks whether those words are a complete utterance, and asks
  it twice with the options in both orders, because this model leans to whichever option is listed first. Jev reads
  both wordings equally well, so the setting is safe to leave on.
- **Volcengine Ark System One (beta)** reads the engine's wording as it is and judges close to Jev, but answers
  several times slower:

  ```bash
  JEV_URL=https://ark.cn-beijing.volces.com/api/v1/systemone
  JEV_MODEL=doubao-seed-2-1-lite-260915
  JEV_HEADERS={"ark-beta-systemone-api": "true"}
  ```

What we measured, from a mainland network (Jev through a route outside it), with `python tools/judge_bench.py`: 160
made-up pauses, 80 Chinese and 80 English, half a finished sentence and half cut off mid-thought, each asked the way
the engine asks when a user pauses. *Right* is p(finished) on the correct side of 0.5; *ranking* is how well
p(finished) orders the pauses whatever the threshold.

| judge | wording | right | ranking | one request, 1 → 9 questions |
|---|---|---|---|---|
| Jev | engine | 96% | 1.00 | tens of ms where it is reachable |
| Jev | `last_words` | 96% | 1.00 | |
| Bailian `decision-model-preview` | `last_words` | 88% | 0.97 | about 100 → 180 ms |
| Bailian `decision-model-preview` | engine | 63% | 0.72 | |
| Volcengine `doubao-seed-2-1-lite-260915` | engine | 95% | 0.99 | about 330 → 450 ms |

The other decisions, with `python tools/judge_bench.py --decisions`: 148 written moments (`tools/judge_cases.py`),
Chinese and English alike, each sent as the engine sends it and scored on the action the engine would take. The Bailian
column is with `JEV_TURN_QUESTION=last_words`.

| decision | moments | Jev right | Bailian right | Bailian takes the same action as Jev |
|---|---|---|---|---|
| handing the line to someone else | 16 | 100% | 100% | 100% |
| cutting in while the user talks (eager pace) | 16 | 69% | 56% | 88% |
| speaking into a silence | 28 | 39% | 43% | 86% |
| which pace | 32 | 81% | 78% | 75% |
| both talking at once | 32 | 97% | 69% | 72% |
| listening: is something due | 24 | 96% | 67% | 42% |

Read with these in mind:

- **Both talking.** The Bailian model keeps a reaction ("mm", a laugh) and a real "stop" apart, but a question or remark
  said over the agent's line it reads as a reaction every time (0 of 8), so the agent talks on and the question is
  not answered. In a trial, the same move that fixed the turn question (the user's words in a field of their own, and
  a question about that field in both orders) took both judges to 32 of 32; that wording is not in the engine yet.
- **Listening.** It knows when to stay quiet and when an answer is owed, but never finds the sound a user asked for
  earlier in the call ("say so each time I mention a cat"): 0 of 8, where Jev finds 7. Two rewordings did not fix it.
  On this judge the agent will not mark or count along.
- **A silence** and **cutting in.** Both judges wait longer and cut in less than the written answers expect, so the
  "right" columns are low for both; what matters there is that they act alike.
- These are written moments, not calls, and the presets' thresholds were set on Jev's probabilities. Run the benchmark
  against your own judge before you rely on it, and again after any change to the wording: on the Bailian model a few
  changed words in the options moved a result by twenty points.

## The caller's voiceprint

```bash
pip install "jev-interaction[voiceprint]"     # speechbrain + torch; CPU is enough, about 100 ms a clip
```

Recommended wherever people call from a room, a car or a speakerphone: other voices and the agent's own voice coming
back are not answered. The model (ECAPA-TDNN, about 80 MB) downloads from Hugging Face on first use into
`JEV_VOICEPRINT_CACHE`. The Docker image includes it (`--build-arg VOICEPRINT=0` leaves it out); `/api/health` says
`voiceprint: ready`. Thresholds: [parameters](parameters.md#the-callers-voiceprint).

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
