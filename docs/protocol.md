# Call protocol

One WebSocket per call at `/ws`. The page (or any client) sends audio and a few JSON messages; the server sends
events. Audio for the agent's lines is fetched over HTTP.

## Client → server

| message | when |
|---|---|
| `{"type": "start", "profile": "companion", "language": "en"}` | first message of the call; `profile` is an id from `/api/profiles`; `language` defaults to the profile's |
| binary frame | 200 ms of 16 kHz mono PCM16 (3200 samples, 6400 bytes), continuously, including while the agent talks |
| `{"type": "playback", "state": "playing" \| "idle"}` | the agent's audio started / the queue ran empty |
| `{"type": "heard", "gen": 7, "text": "..."}` | after `stop`: what was actually played of the reply the last `line` belonged to (its `gen`): the lines that played to the end and the part of the one that was playing, joined by newlines; `""` when none of it played. Without `gen` the text replaces the last reply, and an empty text is ignored |

## Server → client

| event | fields | what the client does |
|---|---|---|
| `line` | `gen, id, text, audio` | queue it; play `audio` (an HTTP URL) in order |
| `listen` | `id, text, kind, audio` | a listening sound ("mm-hm"), or one with content (`kind` `receipt`: a piece said back; `cue`: a mark the caller asked for); play it beside the queue, never queue it |
| `user` | `text, partial` | the caller's words; `partial` while they are still talking |
| `hold` | `gen` | pause the current line (the caller talked over it; the floor decision is pending) |
| `unhold` | `gen` | resume it |
| `stop` | `gen` | drop everything, then reply `heard` |
| `finish_line` | `gen` | drop queued lines, let the current one finish |
| `decision` | `what, action?, go?, probs?, why?, ...` | a turn-taking decision Jev just made (`end_of_turn`, `floor`, `quiet`, `not_for_me`), for display and logs |
| `pace` | `pace, probs` | the call's pace changed (normal, patient, narrate, eager) |
| `error` | `what, text, missing?` | `settings`: required keys are empty (`missing` lists them; the socket closes with 4412); `start`: a provider refused; `judge`: a decision failed, the call falls back and goes on; `responder`: a reply failed or came back empty twice, nothing is said and the call goes on |
| `queue` | `ahead, wait_s` | every line is taken and this caller is held in line: `ahead` callers before them, at most `wait_s` seconds (null when unknown); sent again when either changes. Audio sent meanwhile is ignored |
| `ready` | | a line is free: the call starts now |
| `busy` | `text` | the line itself is full, or today's minutes are used up; the socket closes |
| `hangup` | `why?` | the agent ended the call (or the time limit did) |

`gen` numbers each reply; events for an older `gen` refer to lines that were already replaced.

## HTTP

| route | |
|---|---|
| `GET /tts/{id}` | streamed audio for a `line` or `listen` id |
| `GET /api/profiles` | persona cards: id, path, name, title(_zh), tagline(_zh), language, accent |
| `GET /api/health` | `ready`, `missing` settings, providers |
| `GET /api/settings`, `POST /api/settings`, `POST /api/settings/test` | the settings page; writes only from this server's own page on this machine |

Each call is logged to `runs/call-*.jsonl` (one JSON line per event and judgement, including the state Jev read, the
questions and the answers) for `jev-interaction replay`.
