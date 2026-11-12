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

Without keys the page runs its built-in simulated call (demo mode). To make real calls, add these as Space secrets (`push_hf_space.sh` sets the limits below as variables on the first push):

| secret | value |
|---|---|
| `JEV_API_KEY` | your Jev key |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | any OpenAI-compatible endpoint |
| `ASR_PROVIDER`, `TTS_PROVIDER` | `elevenlabs` or `dashscope` (no default) |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` / `DASHSCOPE_API_KEY` | the keys for the providers you picked |
| `TTS_VOICES` | optional, a voice per persona: `companion=<voice id>,vera=<voice id>` |
| `MAX_CONCURRENT_CALLS` | e.g. `2`: every call is billed to the keys above |
| `MAX_CALL_SECONDS` | e.g. `180` |
| `MAX_CALL_MINUTES_PER_DAY` | e.g. `120`: all calls together, per UTC day |
| `JEV_RECORD_CALLS` | `0`: keep no call logs of your visitors |
