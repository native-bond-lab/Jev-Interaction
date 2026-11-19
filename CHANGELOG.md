# Changelog

## Unreleased

- **The call's record is one timeline, and every question reads the same "now".** `Ledger` keeps the call on one
  clock (seconds into the call): each turn has when it began and ended (`Turn.at`, `Turn.end`), the user's turns have
  where their voice stopped and came back (`Turn.pauses`, `Config.pause_mark_ms`), and what the engine judged and did
  between the words is in it too (`Ledger.notes`: every answer from Jev with its probabilities, every action taken,
  pace changes). The call log's last line carries the whole of it in order (`timeline`), every log line has `at`, and
  a `judge` line has the moment it was asked about as fields (`now`), so a recorded call can be worked through again
  under other thresholds or asked a new question. What Jev reads about the present is written in one place
  (`judge/state.py`: `Now`, built by `Session.now`): a decision chooses its questions, never its own account of the
  call. The text is word for word what each decision sent before (all 832 requests of `tools/judge_bench.py` are
  byte-identical), so no answer changes. How soon a user usually answers is now read off the record
  (`Ledger.reply_gaps`) instead of being counted beside it; a cough that opened no turn no longer counts as an answer.
  Jev is not shown the times: asked the same pause with a user's earlier pauses written into the recent call, its
  "have they finished" did not move (within 0.03), so a user's rhythm is the engine's to read, not the judge's.
- **Questions worded for Bailian's judge.** `Config.judge_provider = "bailian"` (`JEV_PROVIDER=bailian`) sends Alibaba
  Cloud Bailian's `decision-model-preview` its own set of questions (`judge/bailian.py`); Jev keeps the engine's. The
  words a question is about go in a field of their own and the question points at it, every choice is asked in both
  option orders and averaged, and a question that needs the whole call read is split into small ones. It covers the
  end of a turn (the `last_words` wording), both talking, a silence and "something is due" while listening. On 108
  written moments kept apart from the wording: both talking 54% → 100%, a silence 40% → 85%, listening 67% → 96%
  (`tools/judge_bench.py --decisions --held-out`). The mainland setup in the cookbook and on the setup page sets it.
- **A judge for mainland China.** `api.typesafe.ai` does not serve mainland networks, and other services now speak the
  same protocol. `JEV_URL`, `JEV_MODEL` and `JEV_HEADERS` (a JSON object of extra request headers) point the judge at
  one; an empty `JEV_URL=` line no longer leaves the judge without an address. `Config.turn_question = "last_words"`
  (`JEV_TURN_QUESTION=last_words`) words "have they finished" about the user's own words, sent in a field of their
  own, with the options in both orders: Alibaba Cloud Bailian's `decision-model-preview` goes from 63% to 88% right
  with it on 160 written pauses, and Jev reads both wordings alike (96%). The mainland setup in the cookbook and on
  the setup page is now one Bailian key for all four nodes. `tools/judge_bench.py` measures any configured judge,
  the end of a turn and (`--decisions`, 148 written moments in `tools/judge_cases.py`) the other decisions; the numbers,
  and where the Bailian judge falls short of Jev, are in `cookbook/stacks.md`.
- **The turn request asks two questions, not four.** `wait` (how long to hold the answer) and `kind` (a reply or a
  sound) are no longer sent. `wait` said what `done` already says (on 627 recorded turn judgements its value tracked
  p(finished) at -0.92) and its only effect was to hold the draw back: in 217 held moments the user went on during the
  hold 4 times. Replies now start about 150 ms sooner on average, more in the patient pace. Nothing read `kind`'s
  answer; it is still asked, with its `elsewhere` choice, when `Config.not_for_me` is on. `judge.questions.WAIT_MS`
  is gone, `Session.judged` no longer carries `wait_ms` or `reply`, and a judge that answers per question (one
  forward pass each) is asked half as much on every pause.
- **Citation.** `CITATION.cff` (GitHub's *Cite this repository*) and a BibTeX block in the README; a test keeps
  their version equal to the package version.
- **The caller's voiceprint** (`pip install "jev-interaction[voiceprint]"`), the same check the call engine in our
  product runs. Each stretch of voice gets a speaker embedding (ECAPA-TDNN on the CPU, `EcapaEmbedder`) and is compared
  with a print learned from the words the agent answers, with no enrollment step. A clear stranger is not answered and
  does not stop the agent's line (`not_for_me`, `why: "voice"`); a doubtful voice is treated as before; the print needs
  two answered utterances before it can call anyone a stranger. Thresholds `voice_same`, `voice_other`,
  `voice_verdict_ms`, `voice_enroll_ms`; any embedder fits the new `Embedder` protocol (`Session(embedder=...)`). The
  server and the Docker image use it when installed (`JEV_VOICEPRINT=0` turns it off; `/api/health` shows `voiceprint`).
- **Packaging checked.** CI builds the wheel and sdist, installs the wheel alone in a clean environment and checks,
  from outside the repository, that every file the package reads is there (`scripts/check_wheel.py`); the 0.2.0 wheel
  had shipped without the speech prompts. A tag `v*` publishes to PyPI by trusted publishing (`release.yml`), once the
  publisher is set up on PyPI.
- **The public surface is written down** (`docs/stability.md`) and listed in `tests/test_contract.py`: exports, `Session`
  arguments, `Config` and `Pace` fields, adapter protocols, decision names, and the call protocol's messages, which must
  match `docs/protocol.md`. From 1.0.0-beta it is frozen.

## 0.2.0 — 2026-11-16

Highlights: a cookbook (stacks, parameters, role policies); listening as one Jev question, so the agent can say an
item back or count what you asked it to; no clock pauses the agent's line; mid-call hand-over to another persona;
Scribe v3 Live; a waiting line for public demos. Features marked experimental may change before 1.0.

Breaking: the `hold` / `unhold` events and the page's paused state are gone; `listen` events carry `kind` `due` or
`fits` instead of five kinds of sound; `Config(hold_after_ms=...)` and `hold_release_ms` are accepted with a warning.

- **Cookbook** (`cookbook/`): recipes from the voice-call engine in our product. Stacks (the setups we recommend for
  each node, and why), parameters (presets, paces, every `Config` field, and what to change for what you hear) and role
  policies (writing the manner Jev reads, choosing policies, listening with content, handing over). Example profiles: a
  hotel front desk and concierge that hand over to each other, a bakery order line that says each item back. Tests keep
  the cookbook in step with the code.
- The preset `production` is now `recommended` (the old name still works). Provider choices are recommendations only:
  `.env.example` no longer fills in any provider's model; the setups we recommend are at its bottom, on the setup page
  and in `cookbook/stacks.md`.
- `Config(hold_after_ms=...)` is still accepted as the old name of `overlap_ask_ms`, with a deprecation warning.
- Fixed: `turn_reask_ms` marks that are not multiples of a frame (e.g. 500) never fired; a `Config(policies=...)`
  written without the newer `who` decision broke turn-taking when the persona had a `cast`; after "finish the
  sentence" the next early floor question needed three times the voice; the speech prompts were missing from the
  wheel. `Config(hold_release_ms=...)` is accepted (and ignored) with a warning.
- Lyra and Kai no longer say their lab builds Jev (Jev is TypeSafe's); the lab is behind Jev-Interaction.
- Known, experimental: a hand-over switches persona when the goodbye is written, not when it has played, so talking
  over the goodbye does not keep the first persona; byte-range audio requests can synthesize a line twice.
- The benchmark numbers in the README were measured on the 0.1 behaviour (the line paused after 400 ms of voice, five
  kinds of listening sound); the experimental changes below have not been re-measured yet.

- Someone else can be put on the line mid-call (experimental). A persona lists who the caller may ask for (`cast:
  [vera]`); the question `who` then rides in the turn request, and when Jev is sure the caller is asking for one of
  them, the agent on the line says so in a few words and the other comes on: their prompt, manner, policies and voice
  (`persona` event; `Session.hand_over`, `Session(cast=...)`). The call stays one record that says who said what: the
  new agent reads the other's lines as things heard, "(Lyra: ...)", never as its own turns. Naming someone is not
  asking for them. Lyra and Kai list each other.
- Listening, one question (experimental). Everything the agent puts in while the user has the floor is one thing,
  a bare "mm" as much as a count the user asked for ("say a number every time I mention the cat") or an item of a list
  said back. Jev is asked only about the moment: `due` (the user is waiting for it and would miss it), `fits` (a spot
  for a sound that could as well be left out), `quiet`, `answer_due`. What is said is the responder's, from the call's
  record; its event line says which moment Jev saw and quotes nothing. `due` is made when Jev is `listen_due_min` sure
  (0.5), `fits` is drawn by the listen policy and keeps `listen_gap_s`; nothing put in comes closer than
  `listen_min_gap_s` to the last, or runs longer than `listen_max_words`. All of it goes into the record where it came,
  as the agent's own turn between the user's words, and Jev reads it there. Gone: the five kinds of listening sound and
  their per-kind lengths, the fixed 50 % inviting "mm?", the separate question for a silence after unfinished words.
- The turn in progress is part of the call's record (`Ledger.open`), read by every decision and by the responder.
- A silence after words Jev never judged finished stays the user's: the turn question is asked again as the quiet grows
  (`turn_reask_ms`), with the listen question beside it, so a sound may slip in while the turn is not taken. Only
  `turn_last_ms` past the pace's longest wait does the agent speak anyway, and its line is told so (`trailed`).
- No clock pauses the agent's line (experimental). 400 ms of the user's voice over a line used to pause it (`hold`)
  before a word was recognized or Jev was asked, then resume it or stop it; an "mm-hm" froze the line for a second.
  Now the line plays on, and that much voice over it (`overlap_ask_ms`, was `hold_after_ms`) is when the floor question
  is asked on the words so far, closed or not, and again each time as much voice has passed. Asked early, only "the
  user needs the floor" does anything: the line stops. A sound without words asks nothing. Recognizers may send the
  words so far of an unclosed piece (`Segment(final=False)`; Scribe and Paraformer do). The `hold` / `unhold` events,
  `hold_release_ms` and the page's paused state are gone.
- Words said over a line that ended before Jev judged them are asked about as the quiet grows, like any pause, rather
  than answered by the clock.
- The companion on the page is now Lyra Vex (`lyra`, `lyra_zh`): an AI colleague at Native Bond Lab with things she
  cares about, the same four paces and every decision open. Kai and 江屿 stay
  in the package, unlisted.
- A reply that fails (the provider refuses, times out, drops the stream) or comes back with nothing a voice can say
  is asked for once more, so the user is not met with silence; a second miss is reported to the page
  (`error`, `what: "responder"`) and the call goes on.
- The floor question no longer talks on when Jev is sure the line should stop but split on how ("yield" 0.43,
  "overrule" 0.48: neither reached its own threshold, so the agent finished a long line over "let me finish!"). When
  the ways of stopping together outweigh going on and reach the pace's yield threshold, the likeliest one is taken.
- After an interruption the record keeps everything the user heard of the reply, not only the line that was playing
  (a story cut in its fourth line used to lose the first three, so "how old were you again?" had nothing to go on).
  `heard` now carries the reply's `gen` and all of it that played; an empty text means none of it did. A client that
  sends no `gen` works as before.
- Listening sounds are measured in characters where words have no spaces (a whole Chinese sentence used to count as
  one word and was voiced as a listening sound).
- A line that is only an audio tag ("[laughs]") is no longer sent: the voice cannot speak it, and it used to show as
  said while nothing was heard. The speech prompt now says a tag makes no sound alone, so the model writes the sound
  itself ("[laughs] ha").
- The server log says how each call started and ended (time limit, a failed start, the page closing it), and the page
  reports the failures that never reach the call route (a refused microphone, a socket that never opened or dropped).
  No words of the call are logged. The API browser (`/docs`, `/openapi.json`) is off.
- ElevenLabs recognition defaults to Scribe v3 Live (`scribe_v3_live`): same socket and settings, the first words
  arrive much sooner. Set `ELEVENLABS_ASR_MODEL=scribe_v2_realtime` to stay on v2.
- A waiting line for a public demo: when every line is taken a caller is held in line, first come first, instead of
  being turned away (`MAX_WAITING_CALLS`, default 20). The page shows their place and at most how long, and the call
  starts by itself when a line frees up (protocol: `queue`, `ready`). The Space's suggested limits are now 4 calls
  at once, 5 minutes a call, 300 minutes a day.
- The page shows one reply as one caption, however many lines it was written in, and fetches the next line while the
  one before it plays; the words appear as the voice reaches them, and a long
  reply rolls upward, its older lines fading out behind the top edge.
- Words said over a line that carries on go into the call's record at once, for the responder and for Jev.
- The page lists four personas per language: the companion (now Lyra / 小张) and three working ones (support, tutor,
  interviewer; `tutor_zh` and `interviewer_zh` are new). Vera, Mara, 阿乐 and 小言 stay in the package, unlisted.
- The ear our product runs on: TEN VAD (`adapters.best_vad()`, the energy detector when `ten-vad` is not installed),
  the bar raised while the agent's own line plays, voice counted only after 400 ms of it, and the agent's own words
  coming back through the microphone are dropped. A loud room no longer reads as the user talking without end.
- The page: the orb in the middle is the call button (click to call, click to hang up) and beats with whoever is
  speaking; personas follow the page language; the simulated call is gone.
- Personas `kai` and `kai_zh`: one character moving through all four paces with every decision open.
- Vendor-neutral setup. No recognition or voice provider is chosen for you; the language model needs an endpoint and a
  model you pick. The setup we recommend is one you can copy from, not the default. A pasted key is
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

On the voice-call engine in our product, zero-shot, across Full-Duplex-Bench v1.0 / v1.5, LiveKit
eot-bench and TurnBench (16 metrics): first on 3, top three on 8 with the tested knobs. Leads on real-conversation
pauses, relevance after an interruption, talking through an "mm-hm" and letting background speech pass; trails on
pure audio timing and on speed after an interruption. Details and the reason behind each number are in the README.

### Known limits

- The browser client and the energy VAD are minimal.
- Benchmark harnesses are not in this repository yet.
- Jev is a hosted API (`JEV_API_KEY`).
