<div align="center">

# jev-interaction

**Turn-taking for voice agents, as decisions you write — not a model you train.**

[中文](README.zh-CN.md) · [Interactive architecture](docs/architecture.html) · [Profiles](examples/profiles) · [Decisions](jev_interaction/judge/questions.py)

![python](https://img.shields.io/badge/python-3.10%2B-3776ab) ![status](https://img.shields.io/badge/status-alpha-f59e0b) ![judge](https://img.shields.io/badge/judge-Jev-0f766e) ![duplex](https://img.shields.io/badge/full--duplex-voice-6366f1)

</div>

![jev-interaction architecture](docs/architecture.svg)

Most voice agents bolt a turn detector onto speech recognition → language model → speech synthesis: a small model trained
to guess *"has the user finished?"*. Everything else people do on a call is left to timers: the listening "mm-hm",
letting a pause stand, stopping when talked over, picking the conversation back up after a silence, knowing when to
hang up.

**jev-interaction turns each of those into an explicit decision.** A decision is a plain-language multiple-choice
question; [Jev](https://typesafe.ai) answers it with a probability for every choice, in tens of milliseconds; a policy
turns the probabilities into an action. Questions, policies and the agent's manner are all text you can read, change
and replay against real calls.

## Why

| | a typical voice agent | jev-interaction |
|---|---|---|
| when to answer | a trained end-of-turn model, one threshold | a question Jev answers from the words, the timing and the conversation |
| listening sounds | none, or a fixed clip | decided each time: a continuer, a reaction, an echoed word, or nothing |
| being talked over | stop on any voice, or never | carry on, yield, finish the sentence, take the floor back, or react at once |
| silence | a timeout | go on, check in, wait, or hang up — weighed against how this caller talks |
| different products | retrain or re-tune | a task profile: the manner Jev reads, the policy per decision |
| changing behaviour | collect data, retrain | reword a question, replay recorded calls, ship |

## How one moment is decided

The caller is mid-story and pauses for breath. The session writes down what is on the line and asks:

```text
State   Phone call between the user and Mara.
        Who Mara is: a companion character … On the call: a noisy, eager listener …
        Current pace of the call: normal.
        Recent call: …
        What the user has said so far: 0.6 s ago "and then my manager pulls me into a meeting"
        Right now the user has been quiet for 0.4 s.

Asked   listen: continuer · feeling · echo · quiet · answer_due

Jev     feeling 0.46 · quiet 0.27 · continuer 0.22 · answer_due 0.05

Policy  companion → sample        →  "feeling"  →  the agent says "Oh no." and the caller goes on
        support   → threshold 0.8 →  nothing clears the bar  →  silence
```

The same question, the same kind of answer; the profile decides how it is read.

## The decisions

| when | question | choices |
|---|---|---|
| the user pauses | `turn` | finished / continuing · how long to wait · reply / just a sound · which pace |
| the user talks on | `listen` | continuer · feeling · echo · quiet · an answer is due |
| both talk at once | `floor` | carry on · yield · finish the sentence · take the floor back · react at once · short aside |
| the agent leads | `cut_in` | cut in · let them finish |
| the line is quiet | `quiet` | go on · check on them · wait · hang up |

**Paces** (normal, patient, narrate, eager) say who holds the floor. Their timing is blended by Jev's probabilities
instead of switching at the most likely one, so a call that is "60% normal, 40% patient" waits in between.

## Task profiles

One framework, many products. A profile says what the agent is for, how it behaves on a call, and how each decision is
read.

| profile | listening sounds | mid-sentence pauses | talked over | silence | policies |
|---|---|---|---|---|---|
| [companion](examples/profiles/companion.yaml) | often, varied | quick to react | stops, delighted | fills it | sample |
| [support](examples/profiles/support.yaml) | a short "okay" | waits (numbers being read) | stops at once | waits, then one check | thresholds |
| [tutor](examples/profiles/tutor.yaml) | encouraging | very patient | finishes the explanation | offers a prompt | sample |
| [interviewer](examples/profiles/interviewer.yaml) | none | lets thinking run | cuts in on rambling | waits for the answer | mixed |

```yaml
name: Sam
task: A customer-support agent for a broadband provider.
prompt: >            # read by the language model
  Be clear and brief, confirm what you understood, one step at a time.
manner: >            # read by Jev
  Waits for the caller to finish even through long pauses (they may be reading a number). Stops at once when talked over.
policies:
  end_of_turn: {type: threshold, default: 0.7}
  quiet: argmax
```

## Quickstart

```bash
git clone https://github.com/yj972/jev-interaction && cd jev-interaction
pip install -e ".[server]"
cp .env.example .env     # JEV_API_KEY · an OpenAI-compatible LLM endpoint · ELEVENLABS_API_KEY and VOICE_ID
uvicorn server.app:app --port 8080
```

Open <http://localhost:8080>, pick a profile and press **Call**. The built-in VAD is a simple energy detector, so use
headphones.

### In your own code

```python
from jev_interaction import Config, Profile
from jev_interaction.adapters import EnergyVAD
from jev_interaction.adapters.openai_compat import OpenAICompatResponder
from jev_interaction.adapters.scribe import ScribeRealtime
from jev_interaction.judge import JevClient
from jev_interaction.session import Session

session = Session(
    Profile.load("examples/profiles/support.yaml"),
    send=my_send,                       # async: deliver events to your client
    judge=JevClient(),
    recognizer=ScribeRealtime(language="en"),
    responder=OpenAICompatResponder(),   # any OpenAI-compatible endpoint
    vad=EnergyVAD(),
    config=Config(language="en"),
)
await session.start()
await session.on_audio(frame)          # 200 ms of 16 kHz PCM16, as it arrives
await session.on_client({"type": "playback", "state": "idle"})
```

Events to the client: `line`, `listen`, `hold`, `unhold`, `stop`, `finish_line`, `hangup`, plus `user`, `pace` and
`decision` for display. Client messages: `playback` and `heard`.

### Add a decision

```python
# jev_interaction/judge/questions.py
def laugh(name: str) -> dict:
    return {"type": "choice", "instructions": f"The user just made a joke. Would {name}, being who they are, laugh?",
            "criteria": {"laugh": f"{name} finds it funny and laughs", "smile": "a warm word, no laugh", "none": "let it pass"}}
```

Ask it from the session where it belongs, give it a policy in `Config.policies`, and replay recorded calls with
`tools/replay.py` to see where its answers land.

## Early results

Measured on the companion-call engine this framework was extracted from (same decision layer, ElevenLabs Scribe and
TTS) on [Full-Duplex-Bench](https://github.com/DanielLin94144/Full-Duplex-Bench) v1.0: 50 samples per set, drawn with a
fixed seed. The pause sets used gpt-4o-mini as the language model and the interruption set grok-4.3.

| | this engine (n) | GPT-Realtime | Gemini 3.1 Flash Live (high / minimal) |
|---|---|---|---|
| synthetic pauses taken as turns (lower is better) | 0.12 (50) | 0.01 | 0.007 / 0.022 |
| real-conversation pauses taken as turns | 0.18 (50) | 0.12 | 0.10 / 0.15 |
| interruptions answered | 0.96 (50) | 0.97 | 0.995 / 1.0 |
| latency after an interruption (benchmark rule) | 1.79 s mean, 1.68 median | 1.50 s | 0.65 / 0.34 s |
| relevance of the answer, 0–5 | 4.35 (judged by grok) | 3.85 | 4.12 / 3.58 |

Interruptions are on par with the commercial systems and the answers score well. Pauses are the weak spot: of the 15
pause samples counted as taking the turn, 9 were the agent speaking up on its own because it believed the line had gone
quiet (the samples start without a greeting, and some recordings are quiet enough that the voice detector may miss the
caller), and 6 were answers before the caller had finished, mostly after a complete first sentence. Latency is mostly
the language model writing its first line; the decisions take tens of milliseconds.

### Case study: fixing pauses in two knobs

Because every decision is logged with the state Jev read, the 15 pause samples counted as "taking the turn" could be
traced one by one: 9 were the agent speaking up because the quiet-line question fired while the caller was still in
their first sentence (no words recognized yet), 4 were listening sounds longer than the benchmark's three-word limit,
and 2 were answers after a complete first sentence. Two knobs, tested on the same 100 samples:

| | synthetic pauses | real-conversation pauses |
|---|---|---|
| before | 0.12 | 0.18 |
| no quiet-line question while the caller's voice is going | 0.06 | 0.12 |
| plus listening sounds capped at three words | **0.06** | **0.08** |

Real-conversation pauses now beat the commercial systems in the table above (0.10–0.15). These knobs were tested in the
benchmark harness and are not yet in the engine; nothing was retrained.

A third knob, answering only when Jev is at least 0.8 sure the caller has finished, brought real-conversation pauses to
0.04 without slowing answers after interruptions, but ordinary answers took about a second longer (median 0.8 s → 1.8 s).
It stays off: the trade-off is visible, measured and reversible, which is the point.

## Swappable pieces

| piece | protocol | included |
|---|---|---|
| VAD | `is_voice(pcm) -> bool` | `EnergyVAD` |
| recognizer | streaming, closed segments | `ScribeRealtime` (ElevenLabs) |
| responder | `lines(messages) -> async lines` | `OpenAICompatResponder` |
| synthesizer | `audio(text) -> async bytes` | `ElevenLabsTTS` |
| judge | `ask(questions, state) -> probabilities` | `JevClient` |
| policy | `choose(probs, allowed)`, `draw(p)` | `SamplePolicy`, `ThresholdPolicy`, `ArgmaxPolicy` |

## Layout

```
jev_interaction/
  session.py          one call: inputs, decisions, speaking
  judge/              Jev client · the question set · the state text
  policy.py           sample · threshold · argmax
  profile.py          task profiles
  config.py           paces, timings, default policies
  ledger.py           the call's history, for both readers
  recorder.py         one JSON line per event, for replay
  adapters/           VAD · recognizer · responder · synthesizer
  prompts/system.md   the responder's default system prompt
server/app.py         WebSocket call server and line-audio route
web/                  minimal browser client
tools/replay.py       re-ask recorded decisions with changed questions
docs/                 architecture diagram and interactive walkthrough
```

## Roadmap

- Send the first sentence to synthesis as soon as it ends, not at the line break.
- Neural VAD and a second recognizer behind the existing protocols.
- A task-profile benchmark: the same audio, different profiles, measured behaviour.
- Full Full-Duplex-Bench v1.0 / v1.5 runs with published numbers.

## FAQ

**Is Jev required?** The judge is one protocol (`ask(questions, state)`). Jev is what this was built and measured with;
another judge that returns probabilities per choice fits the same slot.

**Does it need a big model for speed?** No. The decisions run in tens of milliseconds. Response speed follows the
language model you plug in.

**What does it cost?** On our measurements, a minute of call audio is a few cents, most of it the language model.

## Status

0.1, alpha, extracted from a companion phone-call system still in development. The decision layer is the tested part;
the browser client and energy VAD are minimal. Jev is a hosted API (`JEV_API_KEY`). License to be decided before the
repository is made public. jev-interaction is an independent project built on Jev; it is not affiliated with or
endorsed by TypeSafe.
