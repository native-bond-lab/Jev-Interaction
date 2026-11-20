# Parameters: the timing of a call

Every timing value is a field of `Config`. Start from a preset, then override what your product needs:

```python
from jev_interaction import preset
cfg = preset("recommended", language="en", overlap_ask_ms=600)
```

| preset | what it is |
|---|---|
| `recommended` (default) | the timing the voice-call engine in our product runs on at scale |
| `tested` | `recommended` plus the knobs measured on the benchmarks (README, "All knobs together") |
| `default` | the library defaults |

`JEV_PRESET` sets it for the server; `production`, the earlier name of `recommended`, still works.

Timing is only half of the behaviour. The other half is the persona's manner and policies, which Jev reads at every
moment: see [role policies](role-policies.md). Change the profile first when the problem is one persona; change these
when it is every call.

## Paces

Each turn Jev also judges which pace the call is in. A pace says who holds the floor, and its timing is **blended** by
Jev's probabilities: a call that is 60 % normal and 40 % patient waits in between.

| pace | when | `max_wait_ms` | `yield_p` | `leads` | `cut_in` |
|---|---|---|---|---|---|
| `normal` | even back-and-forth | 1200 | 0.5 | | |
| `patient` | the user needs room: upset, venting, thinking aloud | 2500 | 0.35 | | |
| `narrate` | the agent carries the call: a story, an explanation | 1200 | 0.5 | yes | |
| `eager` | the agent presses: a quarrel, a game, heated teasing | 1500 | 0.6 | yes | yes |

- `max_wait_ms`: after this much quiet the agent answers anyway.
- `yield_p`: how sure Jev must be that the user is taking the floor before the agent's line stops. Lower = yields sooner.
- `leads`: the agent may talk on over the user's sounds; the floor question offers "take the floor back" and "short aside".
- `cut_in`: the agent may cut in over the user's words.

Your own paces replace these (the description is what Jev reads to tell them apart):

```python
from jev_interaction import Config, Pace
cfg = Config(paces=[
    Pace("normal", "even back-and-forth: questions and answers"),
    Pace("dictation", "the user is reading out something long; the agent only confirms", max_wait_ms=3000, yield_p=0.3),
])
```

`start_pace` is where a call begins; `opening_turns` (2) keeps it through the first turns unless the user asks for
something else.

## The fields

### When the user pauses

| field | recommended | what it does |
|---|---|---|
| `turn_reask_ms` | (1000, 2000, 4000) | words Jev did not judge finished: the turn question is asked again at these marks of quiet, with the listen question beside it |
| `turn_last_ms` | 4000 | this far past the pace's longest wait the agent speaks anyway, and its line is told the user went silent (`trailed`) rather than finished |
| `sound_close_ms` | 1500 | a sound with no words (a cough, a breath) is over after this much quiet |

### When both talk at once

| field | recommended | what it does |
|---|---|---|
| `overlap_ask_ms` | 400 | the user talks over the agent this long: the floor question is asked on the words so far, closed or not, and again each time as much voice has passed. The line plays on until Jev says the user needs the floor |
| `voice_min_ms` | 60 | a frame with this much voice in it counts as the user making sound |

No clock pauses the agent's line: an "mm-hm" over it does not freeze it. (0.1 paused the audio after 400 ms of voice;
that field was `hold_after_ms`, still accepted as the old name of `overlap_ask_ms`.)

### While the user talks on

What the agent puts in while the user has the floor is one decision: Jev picks the moment, the language model writes
the words from the call's record.

| field | recommended | what it does |
|---|---|---|
| `listen_due_min` | 0.5 | something the user is waiting for (an item said back, a count they asked for) is put in when Jev is this sure, never left to a draw |
| `listen_gap_s` | 3.0 | at least this long between two sounds that could as well be left out |
| `listen_min_gap_s` | 1.0 | nothing put in closer than this to the last, whatever it is |
| `listen_finished_max` | 0.65 | no listening sound once Jev is this sure the user has finished |
| `listen_max_words` | 8 | anything longer is dropped: it would be a turn. Characters where words have no spaces (Chinese, Japanese, Korean) |

### When the line is quiet

| field | recommended | what it does |
|---|---|---|
| `quiet_marks_s` | (1.5, 4, 10, 25, 60, 120, 240) | when the quiet question is asked (go on, check on them, wait, hang up) |
| `quiet_jitter` | 0.3 | the marks move by up to this share, so silences do not feel timed |
| `check_min_quiet_s` | 10 | "are you still there?" only after this much quiet |
| `hangup_min_quiet_s` | 25 | a hang-up only after this much quiet, and never as the first thing said into it |

### The judge

| field | recommended | what it does |
|---|---|---|
| `judge_timeout_s` | 3.0 | an answer slower than this is dropped; the decision takes its fallback |
| `judge_turns` / `judge_turn_chars` | 8 / 300 | how much of the call Jev reads at each moment |
| `safe_words` | ("red",) | stop everything, no judgement involved |

### The caller's voiceprint

On when the session has an embedder (`pip install "jev-interaction[voiceprint]"`; the server and the Docker image pick
it up by themselves, `JEV_VOICEPRINT=0` turns it off). The print is learned from the words the agent answers, so it needs
no enrollment step; a clear stranger is not answered and does not stop the agent's line; a doubtful voice is treated as
if there were no print.

| field | recommended | what it does |
|---|---|---|
| `voice_same` | 0.45 | similarity to the caller's print at or above this: the caller |
| `voice_other` | 0.25 | at or below this: someone else (also a voice in between that is `far_db` quieter, 10 dB when unset) |
| `voice_verdict_ms` | 1500 | a voice shorter than this is never called someone else |
| `voice_enroll_ms` | 2000 | an answered utterance at least this long teaches the print |

The print needs two answered utterances before it can call anyone a stranger, so a thin print never shuts the caller
out. Every verdict is in the call log (`voice`, with the similarity), for tuning the two thresholds on your own calls.

### Video calls (experimental)

On when the server has eyes: `VISION_MODEL` names any vision model on an OpenAI-compatible endpoint (`VISION_BASE_URL`
and `VISION_API_KEY` fall back to the responder's). No model is picked for you. The page watches the camera with plain
rules and sends a picture only when the view has changed (its thresholds are `RULES` in `server/web/watch.js`: share of
the frame moved, settled or still moving, a cool-down of 1 s that doubles up to 8 s while looks find nothing new); the seer writes what is new in one sentence, which goes into the
record for Jev and the responder; the `notice` question asks whether to remark on it once nobody is talking. While it
is experimental the page opens the camera only when its address has `?camera=1`.

| field | recommended | what it does |
|---|---|---|
| `jev_sees` | False | Jev compares the last picture that was news with the newest itself (its experimental image input), and the responder is shown the view; the seer only writes the record line, off the path. The server turns it on with `JEV_SEES=1` |
| `notice_stale_s` | 6.0 | a sight not yet asked about after this long has passed: no remark on it |
| `frame_max_bytes` | 600000 | a bigger picture from the page is dropped |

### Tested knobs (off by default)

| field | tested at | effect | trade-off |
|---|---|---|---|
| `not_for_me` | True | a "not said to me" choice in the turn and floor questions; side remarks and background voices are let pass | never offered before the first answer |
| `far_db` | 10 | a voice this many dB under the caller's answered words is someone else's | a quiet caller can be dropped; pair it with the voiceprint |

## Symptom → what to change

| what you hear | try first | then |
|---|---|---|
| the agent jumps in while the user is still thinking | the manner: "lets a thinking pause run" | `patient` pace `max_wait_ms`, or an `end_of_turn` threshold |
| the user waits too long for an answer | `normal` pace `max_wait_ms` down | `turn_reask_ms` earlier |
| an "mm-hm" stops the agent mid-sentence | the manner: "goes on through mm-hms" | `overlap_ask_ms` up (1000 was tested), `yield_p` up |
| the agent talks over a real interruption | `overlap_ask_ms` down | `yield_p` down, a `floor` threshold lower |
| too many listening sounds | the manner: "listens mostly in silence" | `listen_gap_s` up, or a `listen` threshold |
| a listening sound comes out as a whole sentence | `listen_max_words` down (3 was tested) | |
| answers a voice in the background | the voiceprint (`[voiceprint]` extra) | `not_for_me=True`, `far_db=10` |
| "are you there?" too soon, or hangs up too soon | `check_min_quiet_s`, `hangup_min_quiet_s` up | the `quiet` policy to a threshold |

Every decision is logged with the state Jev read and the probabilities it gave, so before changing a number, look at
the moment: `jev-interaction replay runs/*.jsonl --purpose floor` re-asks the recorded questions.
