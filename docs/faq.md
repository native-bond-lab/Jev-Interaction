[← README](../README.md) · [中文](faq.zh-CN.md)

# Why, and common questions

## Why

| | cascade + turn detector | end-to-end duplex model (Moshi, GPT-4o Realtime, Gemini Live) | Jev-Interaction |
|---|---|---|---|
| when to answer | a trained end-of-turn model, one threshold | learned inside the model; you cannot see or move it | a question Jev answers from the words, the timing and the conversation |
| listening sounds | none, or a fixed clip | whatever the model learned | decided each time: a continuer, a reaction, an echoed word, or nothing |
| being talked over | stop on any voice, or never | learned; on Full-Duplex-Bench v1.5 every one of them stops within 0.7 s for an "mm-hm" | carry on, yield, finish the sentence, take the floor back, or react at once |
| silence | a timeout | the model's habit | go on, check in, wait, or hang up, weighed against how this caller talks |
| a persona or a new task | retrain or re-tune the detector | a prompt changes the words; the timing stays the model's | a task profile: the manner Jev reads and the policy per decision, so the persona changes how it takes turns |
| changing behaviour | collect data, retrain | wait for the vendor, or retrain a very large model | reword a question, replay recorded calls, ship |
| why it did that | a score | not inspectable | every decision logged with the state Jev read and its probabilities |
| model and voice | any | the vendor's model and voices | any language model, any synthesizer and voice |
| long calls | no session cap | a session cap (OpenAI Realtime: 60 min) or audio tokens filling the context (Gemini Live: about 15 min of audio before compression drops or summarizes old turns) | no session cap: each decision and each reply is a fresh request over a text history, about 200 tokens per minute of speech |
| speed | the language model's | the fastest: 0.3–1.5 s to answer after an interruption on Full-Duplex-Bench v1.0 | 1.7 s after an interruption, mostly the language model writing its first line |

## Common questions

**Is Jev a voice-activity detector here?** No. Jev never hears audio. Voice activity, the recognizer, the sound
model and the voiceprint are the ears and give signals; Jev answers small facts about the user and the call, and the
policy turns them into one action per moment ([the policy](policy.md#the-policy)).

**Is Jev required?** The judge is one protocol (`ask(questions, state)`). Jev is what this was built and measured with;
another judge that returns probabilities per choice fits the same slot.

**How long can a call last?** As long as you like. Nothing holds a session open on a model provider: Jev and the
language model are asked turn by turn over a text history, and a minute of speech is about 200 tokens of text against
about 1,500 tokens of audio in a speech-to-speech model (Gemini Live counts 25 tokens per second). The history the
responder sees is windowed, so a very long call keeps its early turns only through a memory or summary you add.

**Does it need a big model for speed?** No. The decisions run in tens of milliseconds. Response speed follows the
language model you plug in.

**What does it cost?** On our measurements, a minute of call audio is a few cents, most of it the language model.
