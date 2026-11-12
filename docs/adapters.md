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
], label="My ASR", docs="my-asr.example.com/keys", key_pattern=r"^myasr_")
```

Then `ASR_PROVIDER=my-asr`. `docs` is where the setup page sends people for a key; `key_pattern` lets it recognise a
pasted key.

A synthesizer also says how the language model should write for its voices, with `speech`: `"plain"` (spoken words
only), `"audio_tags"` (inline tags such as `[laughs]`, as ElevenLabs v3/v4 perform them), or a style of its own:

```python
registry.register_style("my_ssml", "Wrap emphasis in <emphasis> tags; write nothing else that is not spoken.")
registry.register("tts", "my-tts", make_my_tts, [...], speech=lambda: "my_ssml")
```

The style can depend on settings (ElevenLabs returns `audio_tags` only for v3/v4 models). The session puts the
paragraph into the responder's system prompt (`{speech}` in `prompts/system.md`). From a separate package, expose a function through the entry-point group
`jev_interaction.adapters` and it is registered on first use:

```toml
[project.entry-points."jev_interaction.adapters"]
my_asr = "my_package.jev:register"   # def register(registry): registry.register("asr", "my-asr", ...)
```

## Test it

`jev_interaction.testing` has a fake of every node (judge, recognizer, responder, VAD, synthesizer) and
`scripted_session()`; swap one fake for yours and drive the call. Pure message builders (as in `dashscope_asr.py`) can be tested without a network.
