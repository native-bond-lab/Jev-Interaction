---
title: Jev-Interaction
emoji: 🎙️
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 8080
pinned: false
license: apache-2.0
short_description: Full-duplex voice, turn-taking judged by Jev
---

# Jev-Interaction on Hugging Face Spaces

End-to-end interactive instinct, from a cascade you can read.
Source: https://github.com/native-bond-lab/Jev-Interaction

Without keys the page runs its built-in simulated call (demo mode). To make real calls, add these as Space secrets:

| secret | value |
|---|---|
| `JEV_API_KEY` | your Jev key |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | any OpenAI-compatible endpoint |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | speech (or `ASR_PROVIDER` / `TTS_PROVIDER` = `dashscope` with `DASHSCOPE_API_KEY`) |
| `MAX_CONCURRENT_CALLS` | e.g. `2`: every call is billed to the keys above |
| `MAX_CALL_SECONDS` | e.g. `180` |
| `JEV_RECORD_CALLS` | `0`: keep no call logs of your visitors |
