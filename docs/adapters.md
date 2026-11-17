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

`Session.close()` also awaits a responder's optional `aclose()` to release a persistent HTTP client. Share a responder
only if its lifetime is managed accordingly. When using `OpenAICompatResponder` directly, close it in a `finally`
block with `await responder.aclose()`. A `lines()` iterator with optional `aclose()` is closed on early consumption
(for example, one listening sound). Both hooks remain optional for custom adapters.

The web server owns synthesizers per call/persona and awaits their optional `aclose()` on call end, including
earlier personas whose queued lines retained their original voice. Direct users of a synthesizer with a persistent
client should close it in a `finally` block too. Its `audio()` iterator is closed on cancellation or early return.
The server calls an optional synchronous `start_warmup()` hook before awaiting ASR setup and when creating a new
persona's synthesizer. This hook must return promptly, own its background work, contain network failures and cancel
that work in `aclose()`; it must not delay real speech. These lifecycle hooks are optional, not protocol requirements.

ElevenLabs uses one bounded HTTP pool per adapter. Its warmup fully consumes a GET of `/v1/models` on the synthesis
origin with the existing API key, without a synthesis request; redirects are not followed. It times out after eight seconds, limits metadata to 256 KiB,
and is cancelled if formal synthesis arrives first. Only completed and still-live connections can be reused;
constructing an `AsyncClient` alone does not establish one. `ELEVENLABS_TTS_REUSE_CONNECTION=0` or
`ELEVENLABS_TTS_PREWARM=0` can disable the respective behavior.

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

Automatic replies retain the original awaited `Session.start()`, `respond()`, handover, stop and tick behavior.
The turn/floor/quiet/cut-in decisions are unchanged from the initial code. Newline segmentation remains the default;
`LLM_CHUNK_MODE=first_sentence` is an optional experiment that changes chunk boundaries, excluded from the current
latency-only changes. No partial-transcript generation or earlier Jev decision is enabled.

The browser prefers AudioWorklet capture, with ScriptProcessor(1024) fallback (`?mic=script` forces the fallback).
Both retain 200 ms / 16 kHz / PCM16 input frames. Audio element release aborts fallback downloads and releases blob
URLs on interruption and hangup. `tools/check_voice_browser.cjs` checks both modes in a real local browser with a
fake microphone and local WAV; it does not measure physical device latency.
