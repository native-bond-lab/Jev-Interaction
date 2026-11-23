# Writing an adapter

Every node of the pipeline is a small protocol in `jev_interaction/adapters/base.py`. An adapter is any class with
those methods; there is no base class to inherit.

| node | protocol | built in |
|---|---|---|
| VAD | `is_voice(pcm: bytes) -> bool` | `EnergyVAD` |
| recognizer | `connect()`, `send(pcm)`, `segments()` (async iterator of `Segment(text)`), `close()` | ElevenLabs Scribe, Paraformer, any OpenAI-compatible `/audio/transcriptions` endpoint |
| responder | `lines(messages, max_tokens)` (async iterator of spoken lines) | any OpenAI-compatible endpoint |
| synthesizer | `audio(text)` (async iterator of encoded bytes) and `media_type` | ElevenLabs, CosyVoice, any OpenAI-compatible `/audio/speech` endpoint |
| judge | `ask(questions, state) -> {name: {"choice", "probabilities"}}` | Jev; any service with the same protocol through `JEV_URL` / `JEV_MODEL` / `JEV_HEADERS` |
| sound model (optional) | `ready`, `warm()`, `score(pcm) -> p(finished) or None` | SmartTurn v3.2 (`[sound]` extra) |
| voiceprint (optional) | `ready`, `warm()`, `embed(pcm) -> unit vector or None` | ECAPA-TDNN (`[voiceprint]` extra) |

A recognizer should close a segment after a short quiet (about 0.35 s) and send only closed segments: the session
decides turns from those, not from partial words.

No provider is ours to choose for the user: speech recognition and synthesis have no default (`ASR_PROVIDER`,
`TTS_PROVIDER` are asked for), and `openai-compatible` (`adapters/openai_speech.py`) covers whoever serves the OpenAI
audio API, a model on the user's own machine included. Its recognizer cuts clips on pauses and sends each whole, since
that API takes finished clips: no words arrive until the pause.

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

## The sound model and the voiceprint

Two optional local models sit beside the four nodes, with no keys and no setup step: a **sound model** that says from
the voice alone whether the user has finished, and a **voiceprint** that tells the caller from other voices. Each
ships with the one we run (SmartTurn v3.2, ECAPA-TDNN) and takes yours the same way as the nodes above:

```python
from jev_interaction.adapters import registry

class MyTurnModel:
    ready = True
    def warm(self): ...                       # load in the background; `score` returns None until it is ready
    def score(self, pcm: bytes) -> float | None:
        ...                                   # the last seconds from the user, 16 kHz PCM16, the pause included

registry.register("sound", "my-turn", lambda **_: MyTurnModel(), label="My turn model")
registry.register("voiceprint", "my-print", make_my_embedder, label="My voiceprint")   # warm / ready / embed(pcm)
```

Then `JEV_SOUND=my-turn` and `JEV_VOICEPRINT=my-print`; `off` turns either node off, and `/api/health` names the
provider in use. A factory may return None (its package is not installed): the call then runs without that node. In
your own code, pass the object straight to `Session(..., sound=..., embedder=...)`.

What the engine does with them stays the same whichever model you plug in, and is what we tested:

- **The sound has a say in the turn** (`decisions/turn.py`, `Config.sound_rule`). With `"and"`, the default, the turn
  is taken only when the words (Jev's p(finished) at `words_min`) and the sound (`sound_min`, by language) both say
  finished; words judged finished that the sound keeps calling unfinished are answered after `sound_wait_ms`. Each
  reading and each turn it held back is in the call log, so the lines can be tuned on your own calls. The lines were
  set on eot-bench v1.0 for SmartTurn; set your own for another model
  ([parameters](../cookbook/parameters.md#the-sound-of-the-voice)).
- **The voiceprint** starts from about 20 seconds the caller reads before the call (`Session.enroll_sample`), grows
  with every answered utterance, and is cleared when the call ends (`Session.close`). A clear stranger is not
  answered; a doubtful voice is left to the words ([parameters](../cookbook/parameters.md#the-callers-voiceprint)).

## Test it

`jev_interaction.testing` has a fake of every node (judge, recognizer, responder, VAD, synthesizer, sound model, embedder) and
`scripted_session()`; swap one fake for yours and drive the call. Pure message builders (as in `dashscope_asr.py`) can be tested without a network.
