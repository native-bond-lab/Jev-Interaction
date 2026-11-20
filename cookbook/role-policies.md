# Role policies: how a persona behaves on a call

A profile is one YAML file. Two readers use it:

| field | read by | it decides |
|---|---|---|
| `prompt` | the language model | what the agent says |
| `task`, `manner` | Jev, at every moment | how the agent behaves: listening sounds, how long a pause stands, whether it yields, whether it speaks into a silence |
| `policies` | the session | how Jev's probabilities become an action |

The same moment ("the user stopped mid-sentence") is judged differently for a tutor and for a support line because Jev
reads the manner with it. That is the role policy: turn-taking written per persona, in plain words, with no training.

Use a profile by id from the built-in set, or by path:

```bash
mkdir -p profiles && cp cookbook/profiles/*.yaml profiles/    # ./profiles wins over the built-in ones
jev-interaction serve
```

```python
Profile.load("support")                        # built-in
Profile.load("cookbook/profiles/order_taker.yaml")
```

## Writing the manner

Jev reads the manner as a description of a person on the phone. Write it that way.

- **Cover the five moments.** While the user talks (listening sounds, or none). When they pause mid-sentence (wait, or
  react). When they talk over the agent (stop at once, finish the sentence, or go on). When the agent leads (cut in on
  rambling, or let them finish). When the line goes quiet (wait, check, fill it, hang up).
- **Say what the persona does, not rules.** "Waits through pauses while the guest checks a confirmation email" gives Jev
  the reason, so it recognises the case. "Never respond within 2 seconds" gives it nothing to recognise.
- **Change with the mood.** A persona can behave differently in each pace: "When the user is upset she gives them room:
  long pauses stand, she says little. When she is telling a story she goes on through their mm-hms." Jev judges the
  pace and the manner together.
- **Keep the prompt and the manner apart.** Facts, voice and what to say go in `prompt`; timing and floor behaviour go
  in `manner`. Both name the same habits when they meet: if the manner says "says each item back", the prompt says how
  ("two sourdough").

Short manners work. The built-in support line is four sentences:

```yaml
manner: >
  Listens without little sounds except a short "okay" when the caller lists details. Waits for the caller to finish a
  sentence even through long pauses (they may be reading a number). Stops at once when the caller talks over it. If the
  line goes quiet while the caller is doing a step, waits; after a long silence asks once whether they are still there.
```

## Policies

Jev gives a probability for every choice. A policy turns them into an action, per decision.

| policy | does | use it for |
|---|---|---|
| `threshold` | acts only when a choice reaches `default` (or its own entry in `thresholds`); otherwise `fallback` | the default for every decision: the same moment goes the same way, and the bar is a number you can tune against recorded calls |
| `sample` | draws against the probabilities: the same moment goes a little differently each time | if you want chance in a decision. Nothing shipped uses it: a draw speaks into one unfinished sentence in ten when Jev says 0.1 |
| `argmax` | always the likeliest choice | when you want no randomness and no bar |

The decisions you can set: `end_of_turn`, `listen`, `floor`, `cut_in`, `quiet`, `who`. Anything you leave out uses the
`Config` default: a threshold of 0.5 for each (`floor` takes its bar for stopping from the pace).

```yaml
policies:
  end_of_turn: {type: threshold, default: 0.7}     # answer only when Jev is 70 % sure they finished
  listen: {type: threshold, default: 0.6}          # a little slower to put a sound in
  floor: {type: threshold, default: 0.35, fallback: carry_on}   # yields sooner than the pace says
  quiet: argmax
```

### Patterns that work

| product | end_of_turn | listen | floor | quiet | why |
|---|---|---|---|---|---|
| support line | threshold 0.7 | threshold 0.8 | threshold 0.5 | argmax | predictable; no chatter |
| interviewer | threshold 0.6 | (silent manner) | default | default | lets answers run |
| tutor | default | default | default | default | the manner does the work: patient, encouraging |
| character, every decision open | default | default | default | default | everything waits for Jev to be sure; the manner and the paces carry the character |

Our own characters run on the defaults. Drawing a decision made a character feel lively in a demo and erratic over a
long call, so nothing is drawn any more: what varies from one moment to the next is when a thing may happen (the
quiet marks and the gap between listening sounds are jittered), not whether a sure thing is done.

## Turn-taking

The questions Jev is asked are the same whoever the agent is; a persona changes the thresholds and the timing, on top
of the pace the call is in (`Profile.turn_taking`, applied in `Session.params`):

```yaml
turn_taking: {yield_shift: 0.15, cut_in: always, lead_scale: 0.6}    # a dominant character
turn_taking: {yield_shift: -0.15, cut_in: never, lead_scale: 1.6}    # a submissive one
```

| key | default | does |
|---|---|---|
| `yield_shift` | 0 | added to the pace's `yield_p`, how sure Jev must be that the user wants the floor before the line stops: + harder to stop, - stops sooner (kept within 0.15 to 0.9) |
| `cut_in` | pace | `always`: cuts in and takes the floor back in any pace; `never`: in none; `pace`: as the pace says |
| `lead_scale` | 1 | scales how long a quiet after its own line lasts before it picks the thread up |

What the shipped personas use:

| persona | yield_shift | cut_in | lead_scale | from its manner |
|---|---|---|---|---|
| companion, front desk, order taker | -0.15 | never | 0.7 / 1 / 1 | stops at once when talked over, never cuts in |
| support (en, zh) | -0.15 | never | 1.5 | stops at once, does not fill a quiet |
| puppy (zh) | -0.15 | never | 1.3 | stops the moment you speak, waits a quiet out |
| tutor (en, zh) | +0.1 | never | 1.3 | finishes the sentence when explaining, never rescues the learner |
| chatterbox (zh) | +0.15 | pace | 0.5 | finishes its sentence first, cannot stand a quiet |
| concierge | +0.1 | pace | 1 | carries a description through the guest's mm-hm |
| interviewer (en, zh) | 0 | always | 1 | cuts in when the candidate rambles |
| Vera | +0.15 | always | 1.5 | finishes her sentence, cuts in with a correction, lets a quiet stand |
| Lyra, Kai | 0 | pace | 1 | their manner already moves with the call |

Two personas from our product with the two settings above act alike in everyday moments and differently in 6 of 16
moments of a scene of control, each the way round one would expect (`tools/persona_bench.py`; the README has the
numbers). Check a persona of yours the same way before you rely on it.

## Listening with content (experimental)

Anything the agent puts in while the user talks is one decision. Jev only names the moment:

| moment | means | what happens |
|---|---|---|
| `due` | the user is waiting for it: a piece of a list just landed, or a thing they asked the agent to mark just came up | made when Jev is `listen_due_min` sure (0.5), never left to a draw |
| `fits` | a spot for a small sound that could as well be left out | made when the `listen` policy's bar is reached (0.5), at most every `listen_gap_s` (jittered by `listen_gap_jitter`) |
| `quiet` | stay silent | nothing |
| `answer_due` | they asked something; answer when they finish | nothing now |

What is said comes from the language model, from the same record, so the persona can say an item back, count, or call
something out. Write the habit into both fields: the manner says *when* ("says each item back the moment the caller has
said it"), the prompt says *what* ("in two or three words"). The user can also ask mid-call ("say 'one' every time I
mention the cat"), with no profile change. See [order_taker.yaml](profiles/order_taker.yaml).

## Putting someone else on the line (experimental)

A persona can list who the caller may ask for:

```yaml
cast: [concierge]
```

When the caller asks for one of them and Jev is sure (the `who` decision, a threshold by default), the agent on the
line says so in a few words and the other comes on with their own prompt, manner, policies and voice. The call stays
one record: the new persona reads the other's lines as things heard, never as its own. Naming someone is not asking
for them. Both files must be in a profiles folder so the id resolves. In your own code, `Session(cast=...)` lists
everyone who can be on the line, including the persona the call starts with, so the caller can be handed back. See
[front_desk.yaml](profiles/front_desk.yaml) and [concierge.yaml](profiles/concierge.yaml).

## Voice

A voice per provider in the profile, used when that provider is selected:

```yaml
voices: {dashscope: longcheng_v2, elevenlabs: <voice id>}
```

`TTS_VOICES="front_desk=<id>,concierge=<id>"` overrides it for one deployment.

## The card on the page

```yaml
display: {title: Front desk, title_zh: 酒店前台, tagline: "...", tagline_zh: "...", language: en,
          accent: "#60a5fa", order: 70, group: task, listed: false}
```

`language` is the call's default language; `listed: false` keeps the persona off the list but callable by id (and
reachable through a `cast`).

## Making one on the page

On your own machine (or your own Docker) the page has **New persona** and **Edit** under the cards: the name and card,
`prompt`, `manner`, the three turn-taking choices and the voice for the synthesizer in use. It writes `profiles/<id>.yaml`
in the working folder and keeps every key it does not show (policies, a cast, other voices). Editing a built-in persona
saves your copy under the same id; deleting the copy brings the built-in one back. A public deployment lists personas
and never offers to edit them.

## Checking a persona

- `jev_interaction.testing` runs a whole call with a fake judge, recognizer, responder and voice: no keys.
- Call logs (`runs/*.jsonl`, unless `JEV_RECORD_CALLS=0`) keep every question Jev was asked and its answer.
  `jev-interaction replay runs/*.jsonl --purpose listen` re-asks them, as asked or reworded (`--edit`), so a change
  can be tried against real moments before it ships.
