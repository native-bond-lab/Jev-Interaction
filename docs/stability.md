# What is public, and how it changes

Jev-Interaction is 0.x: the public surface below can still change, but never silently. Every change to it is in the
CHANGELOG, and a renamed name keeps working, with a warning, for at least one minor release. From 1.0.0-beta the
surface is frozen: names are only added; removing or renaming one waits for 2.0.

`tests/test_contract.py` lists this surface. A change that touches it fails that test until the list is edited too, so
no change to it lands by accident.

## Public

| surface | what is in it |
|---|---|
| Python | `jev_interaction.__all__` (with `Task`, `Executor`, `FunctionExecutor`: [tasks.md](tasks.md)); the `Session(...)` keyword arguments; `Config` and `Pace` fields; `preset` names (`recommended`, `tested`, `default`) |
| adapters | the protocols in `jev_interaction/adapters/base.py` (`VAD`, `Recognizer`, `Responder`, `Synthesizer`, `Embedder`, `Segment`) and `best_vad`, `best_embedder` |
| profiles | the YAML keys `name`, `task`, `prompt`, `manner`, `policies`, `turn_taking` (`yield_shift`, `cut_in`, `lead_scale`), `cast`, `voices`, `display`; the policy names `sample`, `threshold`, `argmax`; the decision names `end_of_turn`, `listen`, `floor`, `cut_in`, `quiet`, `who` |
| call protocol | the client messages and server events in [protocol.md](protocol.md), with their fields |
| settings | the environment variables in `.env.example`, `JEV_PRESET`, `JEV_RECORD_CALLS`, `JEV_VOICEPRINT`, the `MAX_*` limits |
| command line | `jev-interaction serve`, `init`, `replay` and their options |

## Not public

The wording of Jev's questions and of the responder's prompts (they are tuned all the time; that is the point), the
state text Jev reads, the call log format, anything starting with `_`, the page's HTML and CSS, the numbers inside the
`recommended` preset.
