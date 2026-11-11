# Changelog

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
