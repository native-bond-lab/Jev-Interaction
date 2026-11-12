# Contributing

Thanks for helping. Most changes here are small and readable: a reworded question, a new decision, an adapter, a
policy or a task profile. Each one can be checked against recorded calls and the public benchmarks.

## Set up

```bash
git clone https://github.com/native-bond-lab/Jev-Interaction && cd Jev-Interaction
pip install -e ".[server,dev]"
pytest -q
```

The tests use a fake judge and fake adapters, so they need no API keys. A real call needs the keys in `.env.example`.

## Kinds of change

| change | where | how to check it |
|---|---|---|
| reword a question or a choice | `jev_interaction/judge/questions.py` | `jev-interaction replay <call logs> --purpose <decision> --edit <file>` shows which recorded answers flip |
| add a decision | the question in `judge/questions.py`, one module in `jev_interaction/decisions/` registered in `DECISIONS`, a policy in `Config.policies` | a test in `tests/`, then replay recorded calls |
| change what Jev reads | `jev_interaction/judge/state.py` | replay: the state is the only input besides the question |
| a new VAD, recognizer, responder or synthesizer | `jev_interaction/adapters/` | implement the protocol in the README table "Swappable pieces"; add a fake-driven test |
| a policy | `jev_interaction/policy.py` | a unit test; policies are pure functions of probabilities |
| a task profile | `jev_interaction/profiles/*.yaml` | load it in the browser client and call it; describe what changed |

## Benchmark results

A pull request that changes behaviour is most convincing with numbers. Say which benchmark and split (Full-Duplex-Bench
v1.0 / v1.5, LiveKit eot-bench, TurnBench), how many samples, the seed, the language model, and the before/after
scores. Results are welcome in either direction: a knob that makes one metric worse is as useful as one that helps.

## Style

- Plain words in questions and states: Jev reads them, and so do people.
- Keep decisions small: one question per moment, choices that are mutually exclusive.
- No secrets in code, logs or tests. Call logs can contain people's words; strip them before sharing.

## Pull requests

Open an issue first for anything large. Keep a pull request to one change, with a test or a replay that shows it.
By contributing you agree that your contribution is licensed under the Apache-2.0 license of this repository.
