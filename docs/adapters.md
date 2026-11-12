# Writing an adapter

Every node of the pipeline is a small protocol in `jev_interaction/adapters/base.py`. An adapter is any class with
those methods; there is no base class to inherit.

| node | protocol | built in |
|---|---|---|
| VAD | `is_voice(pcm: bytes) -> bool` | `EnergyVAD` |
| recognizer | `connect()`, `send(pcm)`, `segments()` (async iterator of `Segment(text)`), `close()` | ElevenLabs Scribe, Paraformer |
| responder | `lines(messages, max_tokens)` (async iterator of spoken lines) | any OpenAI-compatible endpoint |
| synthesizer | `audio(text)` (async iterator of encoded bytes) and `media_type` | ElevenLabs, CosyVoice |
| judge | `ask(questions, state) -> {name: {"choice", "probabilities"}}` | Jev |

A recognizer should close a segment after a short quiet (about 0.35 s) and send only closed segments: the session
decides turns from those, not from partial words.

## Register it

The server builds each node from the provider registry (`jev_interaction/adapters/registry.py`). Registering adds the
provider to the server, the health check and the settings page:

```python
from jev_interaction.adapters import registry

def make_my_asr(language="en", **_):
    from my_package.asr import MyASR
    return MyASR(language=language)

registry.register("asr", "my-asr", make_my_asr, [
    registry.Setting("MY_ASR_KEY", "My ASR key", secret=True, required=True),
])
```

Then `ASR_PROVIDER=my-asr`. From a separate package, expose a function through the entry-point group
`jev_interaction.adapters` and it is registered on first use:

```toml
[project.entry-points."jev_interaction.adapters"]
my_asr = "my_package.jev:register"   # def register(registry): registry.register("asr", "my-asr", ...)
```

## Test it

Use the fakes the core tests use as a model: a recognizer whose `segments()` yields from a queue, a judge that
returns fixed probabilities. Pure message builders (as in `dashscope_asr.py`) can be tested without a network.
