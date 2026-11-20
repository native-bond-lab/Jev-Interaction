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
JEV_PROVIDER=jev
LLM_BASE_URL=https://api.x.ai/v1
LLM_API_KEY=...
LLM_MODEL=grok-4.3
LLM_TEMPERATURE=0.7
ASR_PROVIDER=elevenlabs
TTS_PROVIDER=elevenlabs
TTS_API_KEY=...             # the ElevenLabs key: the voice, and recognition too
TTS_VOICE_ID=...
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
The same, as a whole file to copy to `.env`: [`deploy/mainland-china.env`](../deploy/mainland-china.env).

```bash
JEV_API_KEY=...            # the Bailian key
JEV_URL=https://<your-workspace-id>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/systemone
JEV_MODEL=decision-model-preview
JEV_TURN_QUESTION=last_words
JEV_PROVIDER=bailian
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
- It needs **`JEV_PROVIDER=bailian`**: its own wording of the questions (`jev_interaction/judge/bailian.py`). With the
  engine's own wording of "have they finished" its answers sit on one side whatever the user said (nearly every
  Chinese pause read as finished), and it misreads a question said over the agent's line as a reaction. The Bailian
  set sends the state as an object with the words a question is about in a field of their own, points each question
  at its field, asks it twice with the options in both orders (this model leans to whichever option is listed first),
  and splits a question that needs the whole call read into small ones. It covers the end of a turn
  (`JEV_TURN_QUESTION=last_words` alone does only that much), both talking, a silence and "something is due" while
  listening; the other decisions go out as the engine words them. It also takes the turn at a higher line on this
  model's p(finished) (below). Leave Jev on the engine's questions.
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

Which side of 0.5 is not the whole of it. A judge whose numbers sit nearer the middle answers into unfinished
sentences even when it ranks them well: on a sentence cut off mid-thought the Bailian model says about 0.35 where Jev
says about 0.1. With `JEV_PROVIDER=bailian` the turn is therefore taken at p(finished) 0.725 instead of 0.5
(`Config.finished_min`). Nothing is drawn: the line is a threshold, kept with every other line in `Config`, and the
same pause goes the same way. (0.2.x drew against p(finished), and a stretch of Bailian's number before the draw was
tried first, 0.6 → 0 and 0.85 → 1; 0.725 is where the stretched number crossed one half.) What that stretch measured
before the draw, on 80 pauses kept apart from the fitting (`python tools/judge_bench.py --held-out`):

| judge | answers a finished sentence at the first draw | speaks into an unfinished one at the first draw |
|---|---|---|
| Jev | 80% | 10% |
| Bailian, p(finished) as it comes | 87% | 35% |
| Bailian, stretched | 89% | 13% |

On 0.3.0, the same 80 held-out pauses asked the way the engine asks now (measured 2026-11-20 from a mainland network,
`JEV_PROVIDER=bailian python tools/judge_bench.py --held-out`): right 90% (zh 90%, en 90%), ranking 0.96, p(finished)
0.87 on average when finished and 0.35 when cut off. At the line (0.725) the agent answers 90% of the finished
sentences and speaks into 15% of the unfinished ones. With a sound model the words' own line is `words_min` (0.8, set
on Jev): there it answers 85% and speaks into 10% (en 5%, zh 15%), before the sound has its say. One request: median
143 ms with 1 question, 171 ms with 8, 176 ms with 11.

Without the closing punctuation a recognizer may or may not send (`--bare`) the same pauses give 76% / 10% on Jev and
83% / 13% on Bailian. What the line does not mend is a wording matter: a number given in pieces ("my code is four
eight") or "hold on, let me check" is a whole sentence, so this wording calls it finished, at about 0.8.

The other decisions, with `python tools/judge_bench.py --decisions`: written moments, Chinese and English alike, each
sent as the engine sends it and scored on the action the engine would take. The Bailian set was worded on 148 moments
(`tools/judge_cases.py`) and checked on 108 others kept apart from the wording (`tools/judge_cases_heldout.py`,
`--held-out`); the held-out column is the one to trust. "Engine questions" is the engine's 0.2 wording with
`JEV_TURN_QUESTION=last_words`; "0.2" and "0.3.0" are `JEV_PROVIDER=bailian` on each release's questions (0.3.0 asks the
pace, cutting in and a silence as small facts for every judge). 0.3.0 measured 2026-11-20 from a mainland network.

| decision | Jev, 0.3.0 questions | Bailian, engine questions, held out | Bailian 0.2, held out | **Bailian 0.3.0, held out** |
|---|---|---|---|---|
| both talking at once | 97% (tuning set) | 54% | 100% | **100%** (24 of 24) |
| speaking into a silence | 100% | 40% | 85% | **95%** (19 of 20) |
| listening: is something due | 96% | 67% | 96% | **96%** (23 of 24) |
| which pace | 100% | 75% | 71% | **75%** (18 of 24) |
| cutting in while the user talks (eager pace) | 100% | 56% | 56% | **62%** (10 of 16) |
| handing the line to someone else | 100% | 100% | 100% | not run |

Read with these in mind:

- **Both talking.** On the engine's question the Bailian model read a question or remark said over the agent's line
  as a reaction every time (0 of 8), so the agent talked on. Pointed at `user_words_over_it` (a reaction, a "stop", or
  something of their own that wants an answer) it gets all three apart. Reacting at once (`jump_in`) is not offered
  in this set.
- **A silence.** Five small questions in place of one: is the agent's last line asking something, did the user say
  they need a moment, have they said goodbye, has the agent already called out with no answer, is the quiet long.
  What still goes wrong: a short "okay" after the user said "hold on" is sometimes read as the agent's move.
- **Listening.** On the engine's question it never found the sound a user asked for earlier in the call ("say so each
  time I mention a cat"): 0 of 8. Asked separately whether such a rule was set earlier and whether the latest words
  bring it up (the two answers multiplied), it finds 7 of 8 held-out ones and still stays quiet where nothing was
  asked for.
- **On 0.3.0's questions** a silence got better on the Bailian model (85% → 95%: the four facts about a quiet grew out
  of its own set), and both talking and listening held.
- **Which pace** and **cutting in** are where it still falls short of Jev. The pace: it reads the eager, patient and
  narrate moments well (5 or 6 of 6 each) but sends most plain chat (4 of 6) to another pace; Jev gets all 24. Cutting
  in: it lets the user finish every time it should (8 of 8) but cuts in on only 2 of the 8 sparring moments, where Jev
  cuts in on all of them. The facts are worded for Jev; a wording of these two for the Bailian model is the next step.
- These are written moments, not calls, and the presets' thresholds were set on Jev's probabilities; only
  p(finished) has been fitted to the Bailian model's own numbers so far. Run the benchmark against your own judge
  before you rely on it, and again after any change to the wording: on the Bailian model a few changed words in the
  options moved a result by twenty points.

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
