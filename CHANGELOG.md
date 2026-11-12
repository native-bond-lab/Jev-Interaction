# Changelog

## Unreleased

- A hold is measured on voice over the line only (an earlier cough gave it a head start), lets go when no new words
  follow, and words said over a line that carries on are filed for the user's next turn instead of holding the next sound.
- The page lists four personas per language: the companion (Kai / 江屿) and three working ones (support, tutor,
  interviewer; `tutor_zh` and `interviewer_zh` are new). Vera, Mara, 阿乐 and 小言 stay in the package, unlisted.
- The ear production runs on: TEN VAD (`adapters.best_vad()`, the energy detector when `ten-vad` is not installed),
  the bar raised while the agent's own line plays, a hold only after 400 ms of real voice, and the agent's own words
  coming back through the microphone are dropped. A loud room no longer reads as the user talking without end.
- The page: the orb in the middle is the call button (click to call, click to hang up) and beats with whoever is
  speaking; personas follow the page language; the simulated call is gone.
- Personas `kai` and `kai_zh`: the companion call this framework was extracted from, moving through all four paces with
  every decision open.
- Vendor-neutral setup. No recognition or voice provider is chosen for you; the language model needs an endpoint and a
  model you pick. What we run in production is a reference setup you can copy from, not the default. A pasted key is
  recognised by its shape; the endpoint's own model list is offered. `.env.china.example` is folded into `.env.example`
  as a commented reference.
- The language model is told how to write for the chosen voice (`prompts/speech/`: audio tags for ElevenLabs v3/v4,
  plain words otherwise); synthesizer plugins can register their own style.
- Personas are grouped into tasks and fun characters.
- `pip install "jev-interaction[server]"` then `jev-interaction serve` (and `init`): the server, its page and the
  built-in personas ship in the package. `.env`, `runs/` and your own `profiles/` live in the folder you start from
  (`JEV_HOME`); a persona of yours replaces a built-in one with the same name. `Profile.load("support")` loads a built-in.
- One provider registry per node (`jev_interaction.adapters.registry`), with an entry-point group for third parties.
- Settings panel on the page: every node's provider and key, quick-fill templates for global and mainland China, a
  test per node; writes only from this machine.
- Mainland China providers: DashScope Paraformer and CosyVoice. Presets: production, tested, default.
- A call without its keys says which ones are missing; system SOCKS proxies work (python-socks).
- Each decision is its own module (`jev_interaction/decisions/`); a new one is a module, `register()` and a policy.
- `from jev_interaction import Session, Profile, JevClient, Recorder, preset`; `presets.config` is now `preset` (old
  name kept). `jev_interaction.testing` has fakes for every provider; `examples/minimal.py` runs a call with no keys.
- `jev-interaction replay` (was tools/replay.py, which still works). `JEV_RECORD_CALLS=0` keeps no call logs.
- Fix: on the floor decision a sampled "elsewhere" that is not the likeliest answer carries on instead of being spoken.
- `py.typed`; ruff in CI; Python 3.13 in the test matrix; CI starts the installed command and checks the page.
- Hardening: settings writes need loopback, same origin and JSON; WebSocket origin check; a failed or slow judge falls
  back instead of freezing the call; call slots and line audio are bounded.

## 0.1.0 — first public release

**Jev-Interaction: System-One-controlled full-duplex voice interaction.** Turn-taking written as plain-language
decisions that Jev answers in tens of milliseconds, on a cascade of any recognizer, any language model and any voice.

### What is in it

- Five decisions on every call: `turn` (finished? how long to wait? a reply or a sound? which pace), `listen` (a
  listening sound or none), `floor` (both talking: carry on, yield, finish the sentence, take the floor back, react),
  `cut_in` and `quiet` (go on, check in, wait, hang up).
- Four paces (normal, listening, narrating, eager) that Jev routes between turn by turn, with their timing blended by
  probability.
- Policies per decision: sample, threshold, argmax.
- Task profiles as YAML: companion, support, tutor and interviewer included; the persona's manner is read by Jev, so it
  changes how the agent takes turns, not only what it says.
- Tested knobs as `Config` options, off by default: `hold_after_ms`, `listen_max_words`, `not_for_me`, `far_db`.
- Adapters behind small protocols: energy VAD, ElevenLabs Scribe realtime, any OpenAI-compatible language model,
  ElevenLabs synthesis.
- A WebSocket call server and a minimal browser client; a recorder that logs every decision with the state Jev read;
  `tools/replay.py` to re-ask recorded decisions with a reworded question.

### Measured

On the production engine this framework was extracted from, zero-shot, across Full-Duplex-Bench v1.0 / v1.5, LiveKit
eot-bench and TurnBench (16 metrics): first on 3, top three on 8 with the tested knobs. Leads on real-conversation
pauses, relevance after an interruption, talking through an "mm-hm" and letting background speech pass; trails on
pure audio timing and on speed after an interruption. Details and the reason behind each number are in the README.

### Known limits

- The browser client and the energy VAD are minimal.
- Benchmark harnesses are not in this repository yet.
- Jev is a hosted API (`JEV_API_KEY`).
