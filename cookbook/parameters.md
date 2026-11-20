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

Each turn Jev is also asked which pace the call is in: one yes/no fact for each pace but the starting one (is this going
on right now, or has the user just asked for it?), worded from the pace's own description. A pace says who holds the
floor, and its timing is **blended** by Jev's probabilities: a call that is 60 % normal and 40 % patient waits in between.

| pace | when | `max_wait_ms` | `yield_p` | `leads` | `cut_in` | `lead_after_s` |
|---|---|---|---|---|---|---|
| `normal` | even back-and-forth | 1200 | 0.5 | | | 6 |
| `patient` | the user needs room: upset, venting, thinking aloud | 2500 | 0.35 | | | 15 |
| `narrate` | the agent carries the call: a story, an explanation | 1200 | 0.5 | yes | | 2.5 |
| `eager` | the agent presses: a quarrel, a game, heated teasing | 1500 | 0.6 | yes | yes | 2.5 |

- `max_wait_ms`: after this much quiet the agent answers anyway.
- `yield_p`: how sure Jev must be that the user is taking the floor before the agent's line stops. Lower = yields sooner.
- `leads`: the agent may talk on over the user's sounds; the floor question offers "take the floor back" and "short aside".
- `cut_in`: the agent may cut in over the user's words.
- `lead_after_s`: quiet after a line of the agent's that asked the user nothing: it picks its own thread up once this
  much has passed (at the next quiet mark). Blended like the timing above.

Your own paces replace these. The description is the fact Jev is asked about, so write it as something that is either
going on in the call or not:

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
| `judge_provider` | "jev" | whose wording of the questions. `"bailian"` (`JEV_PROVIDER=bailian`) sends Alibaba Cloud Bailian's decision model its own set: the `last_words` turn question, and both talking, quiet and "something is due" put as small questions about fields of their own, each asked in both option orders ([stacks](stacks.md#the-judge-on-the-mainland)). Jev keeps the engine's questions |
| `turn_question` | "engine" | how "have they finished" is worded. `"last_words"` asks about the user's own words, sent in a field of their own, with the options in both orders; for judges that read the engine's wording poorly ([stacks](stacks.md#recommended-mainland-china)) |
| `turn_last_ms` | 4000 | this far past the pace's longest wait the agent speaks anyway, and its line is told the user went silent (`trailed`) rather than finished |
| `pause_mark_ms` | 600 | the user's voice stops this long inside their turn and comes back: kept in the call's record as a pause of theirs (`Turn.pauses`). Nothing is decided on it; it is there for reading a user's rhythm and for tuning |
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
| `listen_gap_jitter` | 0.3 | after each sound the gap to the next moves by up to this share, so they do not come on a beat |
| `listen_due_min` | 0.5 | something the user is waiting for (an item said back, a count they asked for) is put in when Jev is this sure, never left to a draw |
| `listen_gap_s` | 3.0 | at least this long between two sounds that could as well be left out |
| `listen_min_gap_s` | 1.0 | nothing put in closer than this to the last, whatever it is |
| `listen_finished_max` | 0.65 | no listening sound once Jev is this sure the user has finished |
| `listen_max_words` | 8 | anything longer is dropped: it would be a turn. Characters where words have no spaces (Chinese, Japanese, Korean) |

### When the line is quiet

| field | recommended | what it does |
|---|---|---|
| `quiet_marks_s` | (1.5, 4, 10, 25, 60, 120, 240) | when a quiet is looked at: Jev is asked the facts (whose move it is, whether they are busy, whether goodbyes were said, whether the agent has called out with no answer) and the engine acts on them and on how long it has been |
| `quiet_jitter` | 0.3 | the marks move by up to this share, so silences do not feel timed. This is the only chance in it: the same facts after the same quiet give the same action |
| `check_min_quiet_s` | 10 | "are you still there?" only after this much quiet |
| `hangup_min_quiet_s` | 25 | a hang-up only after this much quiet, and never as the first thing said into it |

The move is the agent's own (its last line asked nothing): it goes on after the pace's `lead_after_s`. The move is the
user's: it lets the quiet be, and checks on them after `check_min_quiet_s`. The call has ended: it hangs up once that
is open. The `quiet` policy is a threshold by default; `sample` draws among the same actions if you want that back.

### The judge

| field | recommended | what it does |
|---|---|---|
| `judge_timeout_s` | 3.0 | an answer slower than this is dropped; the decision takes its fallback |
| `judge_turns` / `judge_turn_chars` | 8 / 300 | how much of the call Jev reads at each moment |
| `safe_words` | ("red",) | stop everything, no judgement involved |

### The sound of the voice

On when the session has a sound model (`pip install "jev-interaction[sound]"`: SmartTurn v3.2, BSD-2-Clause, about 8 MB on
CPU; the server and the Docker image pick it up by themselves, `JEV_SOUND=off` turns it off, `JEV_SOUND_RULE` sets the
rule). At each frame of a pause after the user's words it reads the last 8 s of audio and says how likely the turn is
over. The words and the sound miss on different pauses: on eot-bench v1.0 each cut people off on about 85 of 850
mid-turn pauses and only 11 of those were the same, so requiring both removes most cut-offs.

| field | recommended | what it does |
|---|---|---|
| `sound_rule` | "and" | "and": the turn is taken only when the words and the sound both say finished; "or": either; "off": the words alone |
| `sound_min` | zh 0.8, en 0.4, other 0.5 | the sound's line, by language |
| `words_min` | 0.8 | the words' line (Jev's p(finished)) while the sound has a say |
| `sound_wait_ms` | 2000 | words judged finished that the sound keeps calling unfinished are answered after this much quiet |

On eot-bench v1.0 at 2% cut-offs, "and" waited 1248 ms (en) / 1050 ms (zh), against 1552 / 1119 for the words alone and
1546 / 1265 for "or". Every reading and every turn it held back is in the call log (`judge` purpose `sound`, and
`end_of_turn` with `go: held`), for tuning the lines on your own calls.

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

### Tested knobs (off by default)

| field | tested at | effect | trade-off |
|---|---|---|---|
| `not_for_me` | True | a "not said to me" choice in the turn and floor questions; side remarks and background voices are let pass | never offered before the first answer |
| `far_db` | 10 | a voice this many dB under the caller's answered words is someone else's | a quiet caller can be dropped; pair it with the voiceprint |

## Symptom → what to change

| what you hear | try first | then |
|---|---|---|
| the agent jumps in while the user is still thinking | the sound model (`[sound]` extra, `sound_rule="and"`) | the manner: "lets a thinking pause run"; `patient` pace `max_wait_ms`, or an `end_of_turn` threshold |
| the user waits too long for an answer | `normal` pace `max_wait_ms` down | `turn_reask_ms` earlier |
| an "mm-hm" stops the agent mid-sentence | the manner: "goes on through mm-hms" | `overlap_ask_ms` up (1000 was tested), `yield_p` up |
| the agent talks over a real interruption | `overlap_ask_ms` down | `yield_p` down, a `floor` threshold lower |
| too many listening sounds | the manner: "listens mostly in silence" | `listen_gap_s` up, or a `listen` threshold |
| a listening sound comes out as a whole sentence | `listen_max_words` down (3 was tested) | |
| answers a voice in the background | the voiceprint (`[voiceprint]` extra) | `not_for_me=True`, `far_db=10` |
| "are you there?" too soon, or hangs up too soon | `check_min_quiet_s`, `hangup_min_quiet_s` up | the `quiet` policy to a threshold |

Every decision is logged with the state Jev read and the probabilities it gave, so before changing a number, look at
the moment: `jev-interaction replay runs/*.jsonl --purpose floor` re-asks the recorded questions.
