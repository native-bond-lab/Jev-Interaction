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
| `sample` | draws against the probabilities: the same moment goes a little differently each time | characters, anything that should feel alive |
| `threshold` | acts only when a choice reaches `default` (or its own entry in `thresholds`); otherwise `fallback` | working lines that must be predictable |
| `argmax` | always the likeliest choice | when you want no randomness and no bar |

The decisions you can set: `end_of_turn`, `listen`, `floor`, `cut_in`, `quiet`, `who`. Anything you leave out uses the
`Config` default (sample, except `floor` and `who`, which are thresholds).

```yaml
policies:
  end_of_turn: {type: threshold, default: 0.7}     # answer only when Jev is 70 % sure they finished
  listen: sample
  floor: {type: threshold, default: 0.35, fallback: carry_on}   # yields sooner than the pace says
  quiet: argmax
```

### Patterns that work

| product | end_of_turn | listen | floor | quiet | why |
|---|---|---|---|---|---|
| support line | threshold 0.7 | threshold 0.8 | threshold 0.5 | argmax | predictable; no chatter |
| interviewer | threshold 0.6 | (silent manner) | default | default | lets answers run |
| tutor | sample | sample | default | sample | encouraging, varied |
| character, every decision open | threshold 0.5 | sample | default | argmax | only the small sounds are drawn; taking the turn, breaking a silence and cutting in wait for Jev to be sure |
| playful character | sample | sample | default | sample | the same moment goes differently each time |

The fourth row is how our own characters run: drawing every decision makes a character feel lively in a demo and
erratic over a long call. Drawing only the listening sounds, and asking for confidence before anything that takes the
floor, keeps the life and loses the misfires.

## Listening with content (experimental)

Anything the agent puts in while the user talks is one decision. Jev only names the moment:

| moment | means | what happens |
|---|---|---|
| `due` | the user is waiting for it: a piece of a list just landed, or a thing they asked the agent to mark just came up | made when Jev is `listen_due_min` sure (0.5), never left to a draw |
| `fits` | a spot for a small sound that could as well be left out | drawn by the `listen` policy, at most every `listen_gap_s` |
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
for them. Both files must be in a profiles folder so the id resolves. See
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

## Checking a persona

- `jev_interaction.testing` runs a whole call with a fake judge, recognizer, responder and voice: no keys.
- Call logs (`runs/*.jsonl`, unless `JEV_RECORD_CALLS=0`) keep every question Jev was asked and its answer.
  `jev-interaction replay runs/*.jsonl --purpose listen` re-asks them, as asked or reworded (`--edit`), so a change
  can be tried against real moments before it ships.
