# Unnati Land & Infra — Voice Bot Technical Architecture Document

**Project:** `tgunnativoicebot`
**Language:** Python (FastAPI + Flask hybrid)
**Telecom Provider:** Tata SmartFlo (CloudPhone)
**Bot Language:** Telugu (te-IN)
**Deployment:** AWS EC2 via Docker + ECR

---

## 1. High-Level Architecture Overview

This is an **outbound AI voice bot** that cold-calls potential land buyers, conducts a scripted Telugu-language conversation, qualifies them as leads, and logs everything to a database. It does not use a large language model for conversation flow — the conversation is a **deterministic finite state machine (FSM)** driven by keyword/intent detection. Gemini LLM is only called as a lightweight tiebreaker when keyword matching fails.

**The system has three runtime layers:**

1. **Telecom Layer** — Tata SmartFlo handles actual phone infrastructure: call origination, SIP trunk, audio streaming over WebSocket.
2. **Server Layer** — FastAPI server (`smartflo_server.py`) manages the WebSocket connection, audio conversion pipeline, and REST API for initiating calls.
3. **Bot Logic Layer** — `solar_webhook.py` contains the entire conversation brain: state machine, intent detection, TTS, database logging.

**Data flow for a single call (end to end):**

```
Your server calls SmartFlo REST API (Click-to-Call)
    → SmartFlo dials customer phone
    → Customer answers
    → SmartFlo opens WebSocket to your server (/ws/tata-tele)
    → SmartFlo streams customer voice as mu-law audio chunks
    → Your server buffers audio → silence detected → sends to STT
    → STT returns Telugu text
    → State machine processes text → returns bot response text
    → Text sent to TTS → WAV audio → converted to mu-law
    → mu-law chunks streamed back to SmartFlo → played to customer
    → Loop continues until state machine reaches ENDED
    → WebSocket closed → SmartFlo drops the call
    → Call data written to SQLite DB → webhook fired to external CRM
```

---

## 2. File-by-File Breakdown

### 2.1 `smartflo_server.py` — The Main Server (FastAPI, Port 8080)

**Role:** Entry point for everything. Handles call initiation, WebSocket audio streaming, bulk dialing, and campaign management.

**Framework:** FastAPI (async, ASGI). Note: `solar_webhook.py` also spawns a Flask app on `__main__`, but in production only the FastAPI server runs.

**Key responsibilities:**

- Accepting SmartFlo WebSocket connections and managing their full lifecycle (connect → stream → disconnect)
- Routing outbound calls via SmartFlo Click-to-Call REST API
- Managing bulk dial jobs via `BatchCallManager`
- Serving a pre-recorded audio cache to avoid TTS latency on known phrases
- Converting between audio formats (mu-law ↔ WAV ↔ PCM) for the STT/TTS pipeline
- Bridging bot logic: it calls `solar_webhook.ask_instant_ai()` as a pure function, so the conversation logic lives in one place regardless of which transport layer (Flask test route or WebSocket) is used

**Critical design decisions:**

- `bot_speaking = [False]` — a mutable list used as a flag. While the bot is playing audio back to the caller, incoming audio frames are discarded. This is the echo suppression mechanism. It is passed into `send_audio_to_smartflo()` and toggled there.
- Runs an "active drain loop" after sending audio: instead of `asyncio.sleep()` (which would block the event loop and cause audio frames to pile up in the OS buffer), it actively reads and discards WebSocket messages for the estimated playback duration. This prevents stale silence frames from falsely triggering `MAX_NO_SPEECH` logic.
- TTS is run in a thread pool executor (`loop.run_in_executor`) so it doesn't block the async event loop while Sarvam AI generates audio.

---

### 2.2 `solar_webhook.py` — Bot Brain + Flask Test Server

**Role:** Contains the entire conversation logic. Also doubles as a standalone Flask server for browser-based testing.

**This file has two distinct parts:**

**Part A: Bot logic (pure functions, used by both Flask routes and FastAPI WebSocket handler)**

- `ask_instant_ai(session_id, user_text, is_start)` — the single entry point to the state machine
- `sessions` dict — in-memory store of all active call sessions, keyed by session ID (which is the WebSocket stream SID)
- All state handler functions (`handle_state_1` through `handle_state_7`, `handle_disconnect`)
- Intent detection functions: `is_positive()`, `_detect_property_type()`, `_detect_timeline()`, `_detect_payment()`
- Translation helper: `_translate_to_english()` — translates Telugu responses to English for DB storage
- `text_to_speech_te()` — TTS function (Sarvam AI primary, gTTS fallback)

**Part B: Flask routes (for browser testing only)**

- `GET /solar_test` — serves a test HTML page
- `POST /start_call` — starts a bot session and returns greeting audio URL
- `POST /webhook` — accepts audio file upload, runs STT, returns bot response + audio URL

**Important note on dual-server architecture:** `solar_webhook.py` defines a Flask `app` but it is NOT run in production. The FastAPI server imports `solar_webhook` as a module and calls its functions directly. The Flask routes exist only for local/browser testing without needing a real phone call.

---

### 2.3 `db.py` — SQLite Conversation Logger

**Role:** Persists every call and every Q&A exchange to a local SQLite database (`solar_calls.db`).

**Tables:**

**`calls`** — one row per phone call session
- `session_id` — UUID, primary key (= WebSocket stream SID)
- `mobile_number` — the DID/agent number (the bot's outgoing number)
- `customer_number` — the actual customer's phone number
- `call_sid` — SmartFlo's internal call identifier
- `call_status` — `ongoing` / `completed` / `dropped` / `not_received` / `max_retries` / `no_speech`
- Lead data: `property_type`, `bill_range`, `timeline`, `payment_pref`

**`conversations`** — one row per Q&A exchange within a call
- `session_id` — foreign key to calls
- `turn` — exchange number (1-based)
- `state` — which FSM state generated this exchange (e.g. `STATE_3`)
- `question` — English-translated version of the bot's question
- `answer` — English-translated version of the customer's reply

**Threading model:** Uses thread-local SQLite connections (`threading.local()`) with WAL (Write-Ahead Logging) mode. WAL allows concurrent reads during writes, which matters because the cleanup loop runs in a background thread while the main async event loop is writing.

**Post-completion webhook:** After marking a call complete, `db.complete_call()` fires an HTTP POST in a background daemon thread to `WEBHOOK_URL` (configured in `.env` as `https://reachoutapi.surefy.co/v1/webhook/voicebot-result`). This sends full call data + Q&A dictionary to an external CRM or backend.

**Stale call cleanup:** A background thread runs every 60 seconds. Any call stuck in `ongoing` status for more than 10 minutes is force-closed as `dropped`. This handles crashes, disconnected WebSockets that didn't trigger the `stop` event, etc.

**Completion listener pattern:** `register_call_completion_listener()` allows external modules (specifically `BatchCallManager`) to subscribe to call completion events. When `complete_call()` runs, it iterates all registered listeners. This is how the batch dialer knows a call slot has freed up.

---

### 2.4 `batch_manager.py` — Concurrent Batch Dialing Engine

**Role:** Manages dialing large lists of numbers efficiently across multiple agent DIDs (caller IDs), tracking each contact's lifecycle.

**Additional SQLite tables it creates in `solar_calls.db`:**

**`batch_jobs`** — one row per bulk dial job
- `job_id`, `agent_ids` (JSON array), `status`, `total`

**`batch_contacts`** — one row per number in a job
- `customer_number`, `agent_id`, `status` (pending → dialing → active → completed/failed)
- `session_id` — linked once the WebSocket stream starts for that contact
- `call_sid`, `provider_status`, `result_json`

**How batching works:**

1. `create_job()` is called with a list of numbers and a list of agent DIDs
2. `advance()` picks N pending contacts (where N = number of agents) and fires one call per agent simultaneously
3. Each contact transitions: `pending → dialing` (call initiated) → `active` (WebSocket opened, `register_session()` called) → `completed/failed` (call ended, `on_call_completed()` fires)
4. When a contact completes, `kick()` is called again → `advance()` picks the next pending batch
5. This continues until all contacts are processed, then job status becomes `completed`

**Concurrency model:** At any given time, there are at most N concurrent active calls (where N = number of agent DIDs). This prevents SmartFlo rate limiting and ensures each agent DID handles one call at a time.

**Cross-loop threading:** `kick()` checks whether an asyncio event loop is running. If yes, it schedules `advance()` via `asyncio.run_coroutine_threadsafe()` (called from a completion listener which runs in a background thread). If no loop is running, it spawns a new thread with `asyncio.run()`.

---

### 2.5 `dial_guard.py` — Duplicate Call Prevention

**Role:** Prevents the same customer number from being dialed twice within a configurable time window (default 300 seconds / 5 minutes).

**Mechanism:** In-memory dict mapping normalized phone numbers to their last dial timestamp. Before any outbound call, `allow()` is called. If the number was dialed within the TTL, it returns False and the call is suppressed. Entries expire after TTL via lazy cleanup on each `allow()` call.

**Why this matters:** In bulk dialing scenarios, the same number could appear multiple times in the list, or a retry could fire before the original call completes. Without this guard, you'd get duplicate simultaneous calls to the same customer.

---

### 2.6 `smartflo_audio.py` — Audio Format Conversion

**Role:** All audio codec translation happens here. Nothing else in the system touches raw audio bytes directly.

**Format context:**
- SmartFlo sends/receives: `audio/x-mulaw`, 8kHz, mono (G.711 µ-law codec — standard telephony codec)
- STT APIs expect: WAV (PCM 16-bit, 8kHz or 16kHz)
- Sarvam TTS produces: WAV at 22050Hz
- All conversions go through `audioop` (Python stdlib) for the µ-law ↔ PCM step and `pydub` + `ffmpeg` for resampling

**Key conversions:**

- `wav_to_mulaw()` — for TTS output going TO SmartFlo. Uses pydub to resample to 8kHz mono, then `audioop.lin2ulaw()`. Pads to 160-byte boundary (20ms frames at 8kHz — standard VoIP frame size).
- `mulaw_to_wav_bytes()` — for SmartFlo audio going TO STT. Applies 2x gain boost (6dB) before WAV conversion. This helps STT pick up quiet speech in noisy environments.

**Buffer and silence detection (`TataSmartfloService`):**

SmartFlo streams audio continuously in 20ms chunks. The system cannot call STT after every 20ms chunk — that would be absurdly expensive and slow. So audio is buffered:

- Minimum buffer: 12000 bytes = 1.5 seconds — won't process until at least this much audio is received
- Maximum buffer: 64000 bytes = 8 seconds — forced processing regardless of silence
- Silence detection: checks the last 0.8 seconds of buffered audio. Converts mu-law tail to PCM, calculates RMS energy. If RMS < 450 (configurable threshold), treats it as silence = end of speech turn.

This is a simple VAD (Voice Activity Detection) implemented with RMS energy. It is NOT a neural VAD — just energy-based. Works well for phone audio but can be fooled by background noise.

---

### 2.7 `generate_pre_audio.py` — Pre-recorded Audio Generator (Offline Tool)

**Role:** One-time script run offline to generate WAV files for all scripted bot responses. These are stored in `static/pre_audio/` and served from disk during live calls, completely bypassing TTS API calls.

**Why this matters for latency:** The single biggest source of voice bot latency is TTS generation time (typically 500ms–2000ms per request for cloud TTS APIs). By pre-recording all known phrases, latency drops to near-zero for those responses — just disk I/O + mu-law conversion.

**Coverage:** All main state questions, retry messages, error messages, and the greeting (split into Part 1 and Part 2 for faster first-byte delivery).

**TTS settings used for pre-recording:** Sarvam AI `bulbul:v3` model, speaker `simran`, pace `1.085`, 22050Hz sample rate, Telugu (te-IN). Note: The live TTS fallback uses speaker `ritu` and pace `1.2` — slight inconsistency between pre-recorded and dynamic voices.

---

### 2.8 `app_voice.py` — Voice UI Test Server (Flask, Port 5000)

**Role:** A separate Flask server for developer/QA testing via a browser voice interface. Not used in production.

Accepts WebM audio from the browser, converts it to WAV, converts WAV to mu-law, calls `transcribe_mulaw()` (same function the production WebSocket uses), and routes through the bot logic. Optional English translation via `deep_translator`.

This shares the same audio pipeline and bot logic as production, making it a high-fidelity test harness.

---

### 2.9 `app_ui.py` — Simple UI Scaffold

A minimal Flask app shell. Not central to the bot operation.

---

## 3. Conversation State Machine

The bot follows a linear FSM with 7 states. Each state has one question, a set of expected responses, and transitions to the next state.

```
START
  │
  ▼
STATE_1: Greeting + interest check
  "Would you like to know more about Sattva Organic Farms?"
  │
  ├── YES → STATE_2
  └── NO  → STATE_1_NO_END → ENDED
  │
  ▼
STATE_2: Investment purpose detection
  "Are you considering this for investment or a farmhouse?"
  │
  └── any answer → STATE_3 (defaults to "investment" if unclear)
  │
  ▼
STATE_3: Land size + price handling
  "How much land — quarter acre, half acre, or one acre?"
  │
  ├── gave size only → STATE_4
  ├── asked price only → answers price, STAYS in STATE_3
  ├── gave size AND asked price → STATE_4 (STATE_PRICE_AND_PAYMENT response)
  └── neither → retry (up to MAX_RETRIES=3) → ENDED if exhausted
  │
  ▼
STATE_4: Payment preference
  "Full payment or EMI?"
  │
  ├── full/cash → STATE_5
  ├── EMI/loan → STATE_5
  └── unclear → retry
  │
  ▼
STATE_5: Investment timeline
  "Within 1 month, 1–3 months, or just exploring?"
  │
  ├── 1month / 1to3months → STATE_6 (site visit)
  └── enquiry → STATE_7_CLOSING → ENDED (skips site visit)
  │
  ▼
STATE_6: Site visit scheduling
  "Free site visit every Sunday. This Sunday or another date?"
  │
  └── any answer → STATE_7
  │
  ▼
STATE_7: Closing thank you message
  (plays closing, then any further input triggers DISCONNECT)
  │
  ▼
DISCONNECT → ENDED
```

**Error handling within states:**

- `MAX_RETRIES = 3`: If intent detection fails 3 times in the same state, the call ends with `END_MISUNDERSTAND`.
- `MAX_NO_SPEECH = 3`: If STT returns empty 3 times consecutively, the call ends with `NO_SPEECH_END`. Between failures, the bot replays the current state's retry question.
- The retry counter resets on every successful response.

---

## 4. Intent Detection — How the Bot Understands Telugu

The bot understands user responses through three layers, applied in priority order:

**Layer 1: Keyword matching (synchronous, zero latency)**
Hardcoded sets of Telugu, Hindi, English, and Odia keywords for each intent. For example, `is_positive()` contains ~60 exact-match words across four languages. `_detect_payment()` checks for `emi`, `loan`, `లోన్`, `ఈఎంఐ` etc.

**Why multiple languages?** The caller base is Telugu-speaking, but STT often transcribes code-switched speech (Telugu + English words mixed in a single utterance). The bot also handles users who respond in Hindi, which happens with multilingual Indian callers.

**Layer 2: Regex + weighted scoring (synchronous)**
`_detect_timeline()` extracts number patterns (`\d+`), range patterns (`1-3 months`), and normalized Telugu number words (`ఒక` → `one`). Multiple keyword hits accumulate a score; the highest-scoring category wins.

**Layer 3: Gemini LLM (async, ~200ms, only if layers 1+2 fail)**
`gemini-2.5-flash-lite` is called with a 3–5 token output limit. The prompt is tightly constrained: `Reply ONLY: FULL / EMI / UNCLEAR`. Token tracking is maintained in `gemini_tokens` dict for visibility.

**Translation for DB storage:** After each exchange, `_translate_to_english()` sends the Telugu answer through Sarvam AI's translation API (primary) → Google free Translate API (fallback) → raw Telugu storage if both fail. This makes the database readable by non-Telugu-speaking analysts.

---

## 5. API Endpoints

### FastAPI Server (`smartflo_server.py`, Port 8080)

**Health & Monitoring:**
- `GET /` — Returns service status + active WebSocket session count
- `GET /sessions` — Lists all currently active streaming sessions

**Call Initiation:**
- `POST /initiate-call` — Triggers a single outbound call via SmartFlo Click-to-Call
  - Body: `{"customer_number": "91XXXXXXXXXX", "caller_id": "918045XXXXXX"}`
- `POST /bulk-dial` — Creates a batch dial job (smart, concurrent, per-agent)
  - Body: `{"numbers": [...], "agents": [...]}` or `{"numbers": [...], "caller_id": "..."}`
  - Returns immediately with `job_id`; dials run in background
- `POST /bulk-dial-legacy` — Old sequential dialer (deprecated, kept for compatibility)
- `GET /bulk-dial/{job_id}` — Check status of a running batch job

**SmartFlo Campaign Management (proxy endpoints):**
- `GET /campaigns` — List all dialer campaigns
- `GET /campaigns/{campaign_id}` — Get specific campaign
- `POST /campaigns` — Create new campaign
- `PUT /campaigns/{campaign_id}` — Update campaign
- `DELETE /campaigns/{campaign_id}` — Delete campaign

**Testing Endpoints (browser-based test harness):**
- `GET /solar_test` — Serves test UI HTML page
- `POST /start_call` — Starts a bot session, returns greeting + audio URL
- `POST /webhook` — Accepts audio file upload (multipart), returns bot reply + audio URL
- `GET /outbound` — Serves the outbound call management dashboard

**WebSocket:**
- `WS /ws/tata-tele` — SmartFlo bi-directional audio stream (described in Section 6)

**Webhook (incoming from SmartFlo):**
- `POST /webhook/call` — SmartFlo calls this with call disposition after a call ends. Used to mark calls as `not_received` when customer didn't answer (voicemail, busy, rejected etc.)

### Flask Test Server (`solar_webhook.py`, Port 8080 on `__main__`)

Only used for local testing. Routes:
- `GET /solar_test` — Test UI
- `POST /start_call` — Session initialization
- `POST /webhook` — Audio upload + bot response

---

## 6. SmartFlo WebSocket Protocol

SmartFlo opens a WebSocket connection to `/ws/tata-tele` when a call is answered. The protocol is event-based with JSON messages.

**Incoming events from SmartFlo:**

| Event | When | Key fields |
|-------|------|-----------|
| `connected` | WebSocket established | — |
| `start` | Call answered, stream begins | `streamSid`, `callSid`, `customData` (contains numbers) |
| `media` | Every 20ms of audio | `media.payload` (base64 mu-law chunk) |
| `stop` | Call ended by customer or network | `streamSid` |
| `clear` | Platform interruption | — |

**Outgoing messages to SmartFlo:**

All audio sent back is:
```json
{
  "event": "media",
  "streamSid": "...",
  "media": { "payload": "<base64 mu-law bytes>" }
}
```
Streamed in 1600-byte chunks = 200ms of audio at 8kHz.

**Session lifecycle in WebSocket handler:**

1. `connected` → log it, wait
2. `start` → extract customer number + agent DID from `customData` → create DB record → `batch_manager.register_session()` → send greeting audio (split into Part 1 + Part 2 to reduce time-to-first-byte)
3. `media` → accumulate in `TataSmartfloService` buffer → silence detected → STT → bot logic → TTS → stream back
4. `stop` or `WebSocketDisconnect` → mark call `dropped` if not already ended → cleanup session from memory

**Echo suppression:** The `bot_speaking[0]` flag is set True before TTS audio begins streaming and False after playback drain completes. During this window, all incoming `media` frames are discarded (buffer cleared). This prevents the bot's own voice from being picked up by the STT and misinterpreted as user input.

---

## 7. SmartFlo Integration

**Authentication:** Two strategies supported:
1. Static API token from `.env` (`SMARTFLO_API_TOKEN`) — recommended, no login required
2. Dynamic login via `POST /v1/auth/login` — fallback

**Click-to-Call flow:**
```
POST https://api-smartflo.tatateleservices.com/v1/click_to_call_support
{
  "async": 1,
  "customer_number": "91XXXXXXXXXX",
  "customer_ring_timeout": 15,
  "caller_id": "918065252515",
  "api_key": "..."
}
```
`async: 1` means SmartFlo returns immediately; the actual call happens asynchronously. SmartFlo will open a WebSocket to `/ws/tata-tele` when the customer answers.

**Caller ID (DID) management:** Multiple DIDs are supported through the `agents` list in bulk dial requests. The `BatchCallManager` assigns one DID per concurrent call slot.

**Disposition handling:** SmartFlo fires `POST /webhook/call` with call outcome data. If the disposition is in `NOT_RECEIVED_DISPOSITIONS` (voicemail, busy, no_answer, rejected, etc.), the call is marked `not_received` in the DB without counting as a conversation attempt.

---

## 8. LLM Integration

**Model used:** `gemini-2.5-flash-lite` (Google Gemini)

**Usage pattern:** Not a conversational LLM — used only as a lightweight intent classifier. Called only when keyword matching + regex scoring both fail to produce a confident result.

**Prompt patterns:**

For payment detection:
```
User answered payment preference (English/Hindi/Odia/Telugu): "..."
Classify: FULL = full payment / cash, EMI = bank loan / EMI / installment
Reply ONLY: FULL / EMI / UNCLEAR
```

For timeline detection:
```
User answered investment timeline: "..."
Classify: 1MONTH / 1TO3MONTHS / ENQUIRY / UNCLEAR
Reply ONLY one word.
```

**Max output tokens:** Always 3–5. This keeps Gemini call latency under ~200ms and cost near zero.

**Token tracking:** `gemini_tokens = {"input": 0, "output": 0}` accumulates across the session lifetime. Returned in test endpoint responses so you can monitor usage.

**Why Gemini and not a bigger model?** The task is binary/ternary classification with a constrained output space. A small model is faster and cheaper. The keyword matching covers ~90% of real-world responses; Gemini only handles the ambiguous 10%.

---

## 9. TTS Pipeline

**Primary:** Sarvam AI `bulbul:v3` model, Telugu (`te-IN`), speaker `ritu`, pace `1.2`
- API: `sarvam_client.text_to_speech.convert()`
- Returns base64-encoded WAV audio at 22050Hz

**Fallback:** gTTS (Google Text-to-Speech, free tier), Telugu
- Used if Sarvam AI throws any exception

**Priority order for audio playback:**
1. Pre-recorded WAV file from `static/pre_audio/` (fastest — disk read only)
2. Sarvam AI TTS (cloud API, ~500ms–1500ms)
3. gTTS fallback (if Sarvam fails)

**Pre-recorded audio lookup:** The text string of the bot response is used as a key in `PRE_RECORDED_AUDIO` dict. Exact string match only. This is why the `STATE_PRICE_AND_PAYMENT` constant was introduced as a named variable — so its string value is consistent between the dict key and the response returned by `handle_state_3()`.

---

## 10. STT Pipeline

**Primary:** Sarvam AI `saaras:v3` model, Telugu (`te-IN`)
- Used in both the WebSocket handler (live calls) and the browser test endpoint

**Fallback:** Google Speech Recognition (free, via `SpeechRecognition` library)
- `recognize_google(audio_data, language="te-IN")`

**Audio pre-processing before STT:**
- mu-law → PCM via `audioop.ulaw2lin()`
- 2x gain boost (6dB) via `audioop.mul()`
- Wrap in WAV container via `pydub`

**In browser test endpoint only:** Audio arrives as WebM from browser microphone → converted to WAV via ffmpeg → sent to Sarvam or Google STT.

---

## 11. Database & Storage

**Engine:** SQLite (`solar_calls.db`)
**Mode:** WAL (Write-Ahead Logging) — supports concurrent reads during writes
**Location:** Local file in working directory

**Tables summary:**

| Table | Purpose | Key columns |
|-------|---------|------------|
| `calls` | One row per call | session_id, customer_number, call_status, timeline, payment_pref |
| `conversations` | Q&A exchanges | session_id, turn, state, question (EN), answer (EN) |
| `batch_jobs` | Bulk dial job metadata | job_id, agent_ids, status, total |
| `batch_contacts` | Per-number dialing state | customer_number, agent_id, status, session_id |

**External webhook on completion:** After every call completes, `db.complete_call()` fires a POST to `WEBHOOK_URL` with:
```json
{
  "session_id": "...",
  "mobile_no": "918065252515",
  "customer_number": "91XXXXXXXXXX",
  "call_status": "completed",
  "call_id": "...",
  "qa_dict": {
    "Would you like to know more?": "Yes tell me",
    "Investment or farmhouse?": "Investment"
  }
}
```
This goes to `https://reachoutapi.surefy.co/v1/webhook/voicebot-result` — likely an external CRM or lead management system.

---

## 12. Deployment

**Infrastructure:** AWS EC2 instance in `ap-south-1` (Mumbai region)
**Container registry:** AWS ECR
**CI/CD:** GitHub Actions on push to `main` branch

**Deploy pipeline:**
1. GitHub Actions checks out code
2. Configures AWS credentials (from GitHub Secrets)
3. Builds Docker image tagged `tgunnativoicebot`
4. Pushes to ECR
5. SSHs into EC2 and runs `/home/ubuntu/scripts/tgunnativoicebot.sh` which pulls the new image and restarts the container

**Docker setup:**
- Base: `python:3.12-slim`
- System deps: `ffmpeg` (critical — used by pydub for audio resampling), `portaudio19-dev`
- PyTorch installed separately (CPU-only, for Whisper — though Whisper is listed in requirements but not actively used in main path)
- Exposes port 8000
- Entrypoint: `uvicorn smartflo_server:app --host 0.0.0.0 --port 8000`

**Public domain:** `https://tgunnatibot.surefy.co`
This URL must be reachable by SmartFlo to open the WebSocket connection. SmartFlo will attempt `wss://tgunnatibot.surefy.co/ws/tata-tele` when a customer answers.

---

## 13. Notable Design Patterns and Technical Decisions

**State in memory, not DB:** Active session state (`sessions` dict in `solar_webhook.py`) is stored in Python process memory. If the server crashes mid-call, that session state is lost. The DB is written to on completion only (per exchange + on close). This is an intentional tradeoff — SQLite writes on every state transition would add latency to each conversation turn.

**Import-driven module sharing:** `smartflo_server.py` imports `solar_webhook` as `bot_module` and calls `bot_module.ask_instant_ai()`, `bot_module.sessions`, `bot_module.PRE_RECORDED_AUDIO` etc. directly. There is no API layer between them. This means both must run in the same Python process — which they do (single FastAPI server). It also means the Flask `app` object inside `solar_webhook.py` is never started in production (only if `__name__ == "__main__"` which doesn't happen when imported).

**Greeting split into two parts:** The initial greeting is split into `STATE_1_GREETING_PART1` (short — just the intro) and `STATE_1_GREETING_PART2` (longer — pitch content). Part 1 is sent with a 1.2-second silence prepend (to prevent the first word getting clipped by network path establishment). Part 2 starts streaming immediately after. This reduces perceived time-to-first-word for the caller.

**`is_positive()` defaults True:** If neither a positive nor negative keyword is found, `is_positive()` returns `True`. This is intentional: keep the conversation moving rather than retry. The philosophy is that caller silence or ambiguity is better interpreted as tentative interest than as rejection.

**STATE_3 price handling:** A specific bug fix documented in code comments. If a user asks "what's the price?" in State 3 (land size question), the old code would advance to State 4 (payment) without collecting land size. The fix: price-only responses stay in State 3. Size-only or size+price responses advance to State 4.

---

