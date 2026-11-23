[← README](../README.md) · [中文](extending.zh-CN.md)

# Extending

## Add a decision

A decision is one module: when it is asked, what Jev is asked, and what the answer does. Write the question:

```python
# jev_interaction/judge/questions.py
def laugh(name: str) -> dict:
    return {"type": "choice", "instructions": f"The user just made a joke. Would {name}, being who they are, laugh?",
            "criteria": {"laugh": f"{name} finds it funny and laughs", "smile": "a warm word, no laugh", "none": "let it pass"}}
```

then the decision, and register it with a policy:

```python
# jev_interaction/decisions/laugh.py
from .. import speaking
from ..judge import questions as Q
from .base import Decision

speaking.event("laugh", "they made a joke; you laugh, in a few words", answers_user=True, max_tokens=60)


class Laugh(Decision):
    name = policy = "laugh"

    def on_words(self, s):                        # when: new words while the agent is quiet
        if not s.speaking and not s.generating:
            s._spawn(self.ask(s))

    def questions(self, s, ctx):                  # what Jev is asked, about the call so far
        return {"laugh": Q.laugh(s.p.short)}

    async def apply(self, s, answers, ctx):       # what the policy's choice does
        if self.choose(s, answers, "laugh", ctx) == "laugh":
            await s.respond("laugh")
```

```python
register(Laugh())                                 # jev_interaction.decisions; or add it to DECISIONS there
config = Config(policies={**Config().policies, "laugh": ThresholdPolicy(default=0.6)})
```

Nothing else changes: the session offers every registered decision each new segment of words (`on_words`) and each
100 ms tick (`on_tick`), and logs the state, the questions and the answers. `allowed` narrows the choices to what
applies now and `state` adds to what Jev reads; the five built-in decisions in `jev_interaction/decisions/` are the
examples. Replay recorded calls with `jev-interaction replay runs/*.jsonl --purpose laugh` to see where its answers land.

## Layout

```
jev_interaction/
  session.py          one call: its state and its loop (audio in, lines out)
  decisions/          one module per decision: turn · listen · floor · cut_in · quiet
  judge/              Jev client · the question set · the state text
  utterance.py        what the user is saying now: words, length, loudness
  speaking.py         what the responder is told before each kind of line
  policy.py           sample · threshold · argmax
  profile.py          task profiles
  config.py           paces, timings, default policies
  presets.py          recommended · tested · default
  ledger.py           the call's one record, on one clock: turns, their times, what was judged and done
  recorder.py         one JSON line per event, for replay
  tasks.py            background tasks: the agent hands work off (an executor) and keeps talking; sleep is in session.py
  harness.py          the hub a coding agent's connector joins; connectors/ holds Claude Code's side
  local.py            the call on this computer's own microphone and speakers, no page
  adapters/           VAD · recognizer · responder · synthesizer · sound model · voiceprint; registry.py lists the providers
  prompts/            the responder's system prompt; speech/ holds one writing style per kind of voice
  profiles/           the built-in personas
  server/             call server (WebSocket, line audio, profiles, health, settings) and its page (web/)
  replay.py           re-ask the recorded questions, as asked or reworded
  testing.py          fake judge, recognizer, responder, VAD and synthesizer: a call with no keys
  cli.py              `jev-interaction serve` / `init` / `replay`
connectors/           the plugins a harness installs: claude-code/ · deepseek-harness/
scripts/setup.sh      one-click local setup (--china: domestic PyPI mirror)
deploy/huggingface/   Hugging Face Space card; scripts/push_hf_space.sh publishes it
deploy/mainland-china.env  the setup that measured best in mainland China, ready to copy to .env
tools/                judge_bench · persona_bench · draw_policy (docs/policy.svg) and other measurement scripts
cookbook/             stacks · parameters · role policies: recipes, not defaults
docs/                 the policy and architecture diagrams, benchmark charts, the protocol
```
