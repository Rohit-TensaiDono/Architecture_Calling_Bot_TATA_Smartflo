"""
SmartFlo FastAPI Server — Tata Telebusiness Outbound Bot Calling
Port: 5002  (Flask bot runs on 5001)

Routes:
  GET  /                       — health check
  GET  /sessions               — list active streaming sessions
  POST /initiate-call          — trigger Click-to-Call via SmartFlo API
  WS   /ws/tata-tele           — SmartFlo bi-directional audio stream

SmartFlo WebSocket Protocol:
  IN:  connected → start → media (audio chunks) → stop
  OUT: media (base64 mu-law audio chunks)

Audio Pipeline (incoming call audio):
  SmartFlo mu-law → WAV → Google STT → text
  → ask_instant_ai() (solar_webhook.py bot logic)
  → text → Sarvam TTS → WAV → mu-law → SmartFlo

Requirements (install):
  pip install fastapi uvicorn pydub websockets requests audioop-lts
"""

import os
import asyncio
import json
import subprocess
import base64
import speech_recognition as sr
import requests

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from dotenv import load_dotenv

# ── SmartFlo audio utilities (same folder) ──────────────────────────────────
from smartflo_audio import smartflo_service, audio_converter, SmartfloAudioConverter

# ── Reuse the bot logic and TTS from solar_webhook ──────────────────────────
# Import only the pure functions / state map; not the Flask app itself.
import solar_webhook as bot_module

load_dotenv()

# ---------------------------------------------------------------------------
# Config from .env
# ---------------------------------------------------------------------------
SMARTFLO_API_URL   = os.getenv("SMARTFLO_API_URL",   "https://cloudphone.tatateleservices.com")
# REST API uses /api prefix: /api/v1/click_to_call works; /v1/click_to_call returns HTML 404
SMARTFLO_API_BASE  = os.getenv("SMARTFLO_API_BASE",  "/api")
SMARTFLO_USERNAME  = os.getenv("SMARTFLO_USERNAME",  "")
SMARTFLO_PASSWORD  = os.getenv("SMARTFLO_PASSWORD",  "")
# Static API token from SmartFlo portal (Settings -> API Access).
# If set, this is used directly and no login call is made.
SMARTFLO_API_TOKEN = os.getenv("SMARTFLO_API_TOKEN", "")
# DID / virtual number that SmartFlo shows to the customer on outbound calls
SMARTFLO_CALLER_ID = os.getenv("SMARTFLO_CALLER_ID", "")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="SmartFlo Bot Server", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Template setup
templates = Jinja2Templates(directory="templates")

# Static files setup
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------------------------------------------------------------
# SmartFlo Auth helpers
# ---------------------------------------------------------------------------

def get_smartflo_token() -> str:
    """
    Return a SmartFlo Bearer token.
    Strategy:
      1. Use SMARTFLO_API_TOKEN from .env if set (recommended — static token
         generated in SmartFlo portal under Settings → API Access / Tokens).
      2. Fall back to dynamic login via POST /v1/auth/login.
    """
    # ── Strategy 1: static token ──────────────────────────────────────────
    if SMARTFLO_API_TOKEN:
        print(f"[SmartFlo] Using static API token: {SMARTFLO_API_TOKEN[:12]}…")
        return SMARTFLO_API_TOKEN

    # ── Strategy 2: dynamic login ─────────────────────────────────────────
    for path in ("/v1/auth/login", "/v1/auth/token"):
        try:
            resp = requests.post(
                f"{SMARTFLO_API_URL}{path}",
                json={"username": SMARTFLO_USERNAME, "password": SMARTFLO_PASSWORD},
                timeout=10,
            )
            if not resp.ok:
                print(f"[SmartFlo] {path} → {resp.status_code}, trying next…")
                continue
            data  = resp.json()
            token = (data.get("token")
                     or data.get("access_token")
                     or data.get("data", {}).get("token", ""))
            if token:
                print(f"[SmartFlo] Auth token obtained via {path}: {token[:12]}…")
                return token
        except Exception as e:
            print(f"[SmartFlo] {path} error: {e}")

    print("[SmartFlo] ⚠️  Could not obtain auth token. Set SMARTFLO_API_TOKEN in .env")
    return ""

def initiate_click_to_call(customer_number: str, caller_id: str | None = None) -> dict:
    """
    Trigger an outbound call via SmartFlo Click-to-Call API.
    POST /v1/click_to_call
    """
    token = get_smartflo_token()
    if not token:
        return {"success": False, "error": "Could not obtain SmartFlo auth token"}

    # Normalise numbers -- strip leading '+' that SmartFlo doesn't accept
    did = (caller_id or SMARTFLO_CALLER_ID).lstrip("+")
    customer_number = customer_number.lstrip("+")

    payload = {
        "agent_number":       did,           # DID / caller-ID shown to customer
        "destination_number": customer_number,
    }

    print(f"[SmartFlo] Initiating Click-to-Call: agent={did} -> customer={customer_number}")
    try:
        resp = requests.post(
            f"{SMARTFLO_API_URL}{SMARTFLO_API_BASE}/v1/click_to_call",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
        raw = resp.text.strip()
        print(f"[SmartFlo] Click-to-Call response ({resp.status_code}): {raw[:200]}")

        # SmartFlo may return an empty body on success (2xx) or on some errors
        if not raw:
            if resp.ok:
                return {"success": True,  "status_code": resp.status_code, "data": {"message": "Call initiated (empty response)"}}
            else:
                return {"success": False, "status_code": resp.status_code, "error": f"HTTP {resp.status_code} with empty body"}

        # Try JSON parse; fall back to raw text
        try:
            data = resp.json()
        except Exception:
            data = {"raw": raw}

        return {"success": resp.ok, "status_code": resp.status_code, "data": data}

    except Exception as e:
        print(f"[SmartFlo] Click-to-Call error: {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Audio cache for pre-recorded messages
# ---------------------------------------------------------------------------
PRE_MU_LAW_CACHE = {}

def get_pre_recorded_mulaw(text: str) -> bytes:
    """Check if text exists in pre-recorded audio mapping and return as mu-law."""
    if text in PRE_MU_LAW_CACHE:
        return PRE_MU_LAW_CACHE[text]
    
    wav_path = getattr(bot_module, "PRE_RECORDED_AUDIO", {}).get(text)
    if wav_path and os.path.exists(wav_path):
        try:
            with open(wav_path, "rb") as f:
                wav_bytes = f.read()
            mulaw_data = audio_converter.wav_to_mulaw(wav_bytes)
            if mulaw_data:
                PRE_MU_LAW_CACHE[text] = mulaw_data
                return mulaw_data
        except Exception as e:
            print(f"[SmartFlo] Error loading pre-recorded audio: {e}")
    return b""


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

_recognizer = sr.Recognizer()

# Sarvam AI STT client (reuse from bot_module — same API key)
_sarvam_client = bot_module.sarvam_client


def transcribe_mulaw(mulaw_data: bytes) -> str:
    """Convert mu-law audio → WAV → text via Sarvam AI STT (primary) or Google STT (fallback)."""
    wav_bytes = audio_converter.mulaw_to_wav_bytes(mulaw_data)
    if not wav_bytes:
        return ""

    # ── 1. Primary: Sarvam AI STT (saaras:v3 — best for Indian languages) ──
    try:
        import io
        response = _sarvam_client.speech_to_text.transcribe(
            file=("audio.wav", io.BytesIO(wav_bytes)),
            model="saaras:v3",
            language_code="hi-IN",
        )
        text = (response.transcript or "").strip()
        if text:
            print(f"[Sarvam STT] '{text}'")
            return text
        print("[Sarvam STT] Empty transcript — trying Google fallback")
    except Exception as e:
        print(f"[Sarvam STT] Error: {e} — trying Google fallback")

    # ── 2. Fallback: Google free STT ──
    try:
        import io
        with sr.AudioFile(io.BytesIO(wav_bytes)) as src:
            audio_data = _recognizer.record(src)
        text = _recognizer.recognize_google(audio_data, language="hi-IN")
        print(f"[Google STT Fallback] '{text}'")
        return text
    except sr.UnknownValueError:
        print("[Google STT Fallback] No speech detected")
        return ""
    except Exception as e:
        print(f"[Google STT Fallback] Error: {e}")
        return ""


def tts_to_mulaw(text: str) -> bytes:
    """
    Convert text → WAV (Sarvam TTS from bot_module) → mu-law for SmartFlo.
    Synchronous wrapper around Sarvam TTS.
    Prioritizes pre-recorded static files if available.
    """
    # 1. Check pre-recorded cache/files first
    pre_audio = get_pre_recorded_mulaw(text)
    if pre_audio:
        print(f"[SmartFlo] Using static pre-recorded audio for: {text[:40]}…")
        return pre_audio

    # 2. Dynamic TTS generation (Sarvam AI)
    import tempfile, os as _os
    tmp_wav = tempfile.mktemp(suffix=".wav")
    try:
        bot_module.text_to_speech_hi(text, tmp_wav)
        with open(tmp_wav, "rb") as f:
            wav_bytes = f.read()
        mulaw_data = audio_converter.wav_to_mulaw(wav_bytes)
        return mulaw_data
    except Exception as e:
        print(f"[TTS→mu-law] Error: {e}")
        return b""
    finally:
        try:
            _os.remove(tmp_wav)
        except:
            pass


async def send_audio_to_smartflo(
    websocket: WebSocket,
    stream_sid: str,
    text: str,
    speaking_flag: list,
    session_id: str = None,
    final: bool = False,
    prepend_silence_s: float = 0.0,
):
    """
    Generate TTS audio for 'text', convert to mu-law chunks, and stream to SmartFlo.

    speaking_flag is set TRUE immediately (before TTS generation) so media frames
    are seen as 'bot speaking' by the media handler and dropped.

    After streaming, we ACTIVELY DRAIN the WebSocket receive queue for the entire
    estimated playback duration + 0.8s. This is critical: asyncio.sleep() would
    block the while-True loop so all SmartFlo frames accumulate in the OS buffer
    and flood in the moment the sleep ends (causing false MAX_NO_SPEECH). By
    reading and discarding within this function we keep the buffer empty.
    """
    speaking_flag[0] = True   # ── mute incoming audio immediately ──
    try:
        loop = asyncio.get_event_loop()
        mulaw_data = await loop.run_in_executor(None, tts_to_mulaw, text)

        if not mulaw_data:
            print(f"[SmartFlo] TTS produced no audio for: {text[:40]}")
            return

        # Prepend mu-law silence (0xFF) to allow the telecom network path to establish
        # without clipping the first spoken word.
        if prepend_silence_s > 0:
            silence_bytes = b"\xFF" * int(8000 * prepend_silence_s)
            mulaw_data = silence_bytes + mulaw_data

        # Stream in 200ms chunks (1600 bytes @ 8kHz mu-law)
        chunk_size = 1600
        for i in range(0, len(mulaw_data), chunk_size):
            chunk = mulaw_data[i: i + chunk_size]
            response = smartflo_service.create_media_response(stream_sid, chunk)
            await websocket.send_json(response)
            # Drain any incoming media that arrived while we were sending this chunk
            try:
                raw = await asyncio.wait_for(websocket.receive(), timeout=0.001)
            except asyncio.TimeoutError:
                pass

        print(f"[SmartFlo] Sent {len(mulaw_data)//1000}KB audio: {text[:50]}…")

        estimated_playback_s = len(mulaw_data) / 8000.0

        if final:
            # Final message — SmartFlo buffers audio server-side, but we MUST wait 
            # for the full playback to complete before closing the WebSocket, 
            # otherwise the call cuts off early.
            await asyncio.sleep(estimated_playback_s + 0.5)
            print(f"[SmartFlo] Final audio playback complete ({estimated_playback_s:.1f}s) — closing stream")
        else:
            # ── Active drain loop ────────────────────────────────────────────
            # Read and discard ALL incoming WebSocket messages for the estimated
            # playback duration (+ 0.8s safety buffer). This keeps the buffer
            # empty so stale silence frames don't trigger false MAX_NO_SPEECH.
            drain_until = loop.time() + estimated_playback_s + 0.8
            drained = 0
            while loop.time() < drain_until:
                try:
                    await asyncio.wait_for(websocket.receive(), timeout=0.05)
                    drained += 1
                except asyncio.TimeoutError:
                    pass
            print(f"[SmartFlo] Drained {drained} stale frames during playback")

    finally:
        speaking_flag[0] = False  # ── unmute incoming audio ──
        print("[SmartFlo] Listening resumed")


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def health():
    return {
        "status": "ok",
        "service": "SmartFlo Bot Server",
        "active_streams": smartflo_service.get_active_sessions_count(),
    }


@app.get("/sessions")
async def list_sessions():
    return {
        "count": smartflo_service.get_active_sessions_count(),
        "sessions": smartflo_service.get_all_sessions(),
    }


@app.post("/initiate-call")
async def initiate_call(body: dict):
    """
    Trigger a single outbound call via SmartFlo Click-to-Call.
    Body: {
        "customer_number": "91XXXXXXXXXX",   # required — number to call
        "caller_id": "918045XXXXXX"           # optional — DID shown to customer
    }
    """
    customer_number = body.get("customer_number", "")
    caller_id       = body.get("caller_id", "")

    if not customer_number:
        return {"success": False, "error": "customer_number is required"}

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, initiate_click_to_call, customer_number, caller_id
    )
    return result


@app.post("/bulk-dial")
async def bulk_dial(body: dict):
    """
    Dial multiple customers sequentially with a configurable delay.
    Body: {
        "numbers":   ["91XXXXXXXXXX", ...],  # list of customer numbers
        "caller_id": "918045XXXXXX",         # DID shown to customers
        "delay":     5                        # seconds between calls (default 5)
    }
    Returns immediately with job_id; calls are fired in background.
    """
    numbers   = body.get("numbers", [])
    caller_id = body.get("caller_id", "")
    delay     = max(1, int(body.get("delay", 5)))  # minimum 1s

    if not numbers:
        return {"success": False, "error": "numbers list is required"}

    import uuid as _uuid
    job_id = str(_uuid.uuid4())[:8]

    async def _run_bulk():
        print(f"[BulkDial:{job_id}] Starting — {len(numbers)} numbers, {delay}s delay")
        ok = 0; fail = 0
        loop = asyncio.get_event_loop()
        for i, num in enumerate(numbers):
            try:
                result = await loop.run_in_executor(
                    None, initiate_click_to_call, num, caller_id
                )
                if result.get("success"):
                    ok += 1
                    print(f"[BulkDial:{job_id}] {i+1}/{len(numbers)} ✅ {num}")
                else:
                    fail += 1
                    print(f"[BulkDial:{job_id}] {i+1}/{len(numbers)} ❌ {num} — {result.get('error')}")
            except Exception as e:
                fail += 1
                print(f"[BulkDial:{job_id}] {i+1}/{len(numbers)} ❌ {num} — {e}")

            if i < len(numbers) - 1:
                await asyncio.sleep(delay)

        print(f"[BulkDial:{job_id}] Done — {ok} ok / {fail} failed")

    asyncio.create_task(_run_bulk())
    return {"success": True, "job_id": job_id, "queued": len(numbers), "delay_s": delay}


@app.get("/outbound", response_class=HTMLResponse)
async def outbound_dashboard(request: Request):
    """Serve the outbound call management dashboard."""
    return templates.TemplateResponse("outbound_dashboard.html", {"request": request})


# ---------------------------------------------------------------------------
# SmartFlo Dialer Campaign proxy helpers
# ---------------------------------------------------------------------------

def _smartflo_request(method: str, path: str, body: dict | None = None) -> dict:
    """
    Authenticated request to SmartFlo REST API.
    method : 'GET' | 'POST' | 'PUT' | 'DELETE'
    path   : e.g. '/v1/dialer/campaign' (no base URL)
    body   : JSON payload for POST/PUT, None otherwise
    Returns a dict with keys: success, status_code, data (or error)
    """
    token = get_smartflo_token()
    if not token:
        return {"success": False, "error": "Could not obtain SmartFlo auth token"}

    url     = f"{SMARTFLO_API_URL}{SMARTFLO_API_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = requests.request(method, url, json=body, headers=headers, timeout=15)
        data = resp.json() if resp.content else {}
        print(f"[SmartFlo] {method} {path} → {resp.status_code}")
        return {"success": resp.ok, "status_code": resp.status_code, "data": data}
    except Exception as e:
        print(f"[SmartFlo] {method} {path} error: {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Dialer Campaign CRUD endpoints  (proxy → SmartFlo /v1/dialer/campaign)
# ---------------------------------------------------------------------------

@app.get("/campaigns")
async def list_campaigns():
    """List all dialer campaigns from SmartFlo."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _smartflo_request, "GET", "/v1/dialer/campaign", None)
    return result


@app.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str):
    """Fetch a specific dialer campaign by ID."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, _smartflo_request, "GET", f"/v1/dialer/campaign/{campaign_id}", None
    )
    return result


@app.post("/campaigns")
async def create_campaign(body: dict):
    """
    Create a new dialer campaign.
    Pass the full SmartFlo campaign payload as JSON body.
    Typical fields (confirm in your SmartFlo portal):
      name, caller_id, dialer_type, list_id, ...
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, _smartflo_request, "POST", "/v1/dialer/campaign", body
    )
    return result


@app.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, body: dict):
    """Update an existing dialer campaign."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, _smartflo_request, "PUT", f"/v1/dialer/campaign/{campaign_id}", body
    )
    return result


@app.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str):
    """Delete a dialer campaign."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, _smartflo_request, "DELETE", f"/v1/dialer/campaign/{campaign_id}", None
    )
    return result


@app.get("/solar_test", response_class=HTMLResponse)
async def serve_test_page(request: Request):
    """Serve the solar_test.html template for manual testing."""
    return templates.TemplateResponse("solar_test.html", {"request": request})


@app.post("/start_call")
async def start_call_test():
    """Manual test endpoint: Start a bot session (browser test)."""
    import uuid
    session_id = str(uuid.uuid4())
    bot_reply = bot_module.ask_instant_ai(session_id, is_start=True)
    
    # Use pre-recorded audio if available, otherwise generate TTS
    if bot_reply in bot_module.PRE_RECORDED_AUDIO:
        audio_url = f"/{bot_module.PRE_RECORDED_AUDIO[bot_reply]}"
    else:
        audio_file = f"static/intro_{session_id}.wav"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, bot_module.text_to_speech_hi, bot_reply, audio_file)
        audio_url = f"/{audio_file}"
    
    return {
        "session_id": session_id,
        "text": bot_reply,
        "audio_url": audio_url,
        "tokens": bot_module.gemini_tokens
    }


@app.post("/webhook")
async def webhook_test(
    session_id: str = Form(...),
    audio: UploadFile = File(...)
):
    """Manual test endpoint: Process incoming audio chunk (browser test)."""
    if not session_id or session_id not in bot_module.sessions:
        return JSONResponse({"error": "Invalid or expired session."}, status_code=400)
        
    user_audio_path = f"static/user_audio_{session_id}.webm"
    with open(user_audio_path, "wb") as f:
        f.write(await audio.read())
    
    user_text = ""
    # 1. Transcribe audio — Sarvam AI primary, Google fallback
    try:
        wav_path = f"static/temp_{session_id}.wav"
        # Convert webm to PCM wav format
        import subprocess
        ffmpeg_result = subprocess.run(
            ["ffmpeg", "-y", "-i", user_audio_path, "-ac", "1", "-ar", "16000", wav_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        if ffmpeg_result.returncode != 0:
            raise Exception("ffmpeg conversion failed")
        
        # Read WAV bytes for Sarvam
        with open(wav_path, "rb") as wf:
            wav_bytes = wf.read()

        # Primary: Sarvam AI STT
        try:
            import io
            response = _sarvam_client.speech_to_text.transcribe(
                file=("audio.wav", io.BytesIO(wav_bytes)),
                model="saaras:v3",
                language_code="hi-IN",
            )
            user_text = (response.transcript or "").strip()
            if user_text:
                print(f"[Browser Test] Sarvam STT: '{user_text}'")
        except Exception as e:
            print(f"[Browser Test] Sarvam STT error: {e}")

        # Fallback: Google STT
        if not user_text:
            try:
                import speech_recognition as sr
                r = sr.Recognizer()
                with sr.AudioFile(wav_path) as source:
                    audio_data = r.record(source)
                user_text = r.recognize_google(audio_data, language="hi-IN")
                print(f"[Browser Test] Google STT fallback: '{user_text}'")
            except Exception as e2:
                print(f"[Browser Test] Google STT fallback error: {e2}")

        import os
        os.remove(wav_path)
    except Exception as e:
        print(f"[Browser Test] Transcription error: {e}")
        user_text = ""
        
    try: os.remove(user_audio_path)
    except: pass
    
    if not user_text:
        return {
            "text": "[No speech detected]", 
            "answer": "मुझे आपकी आवाज़ नहीं आ रही है। कृपया दोहराएँ।", 
            "audio_url": "",
            "tokens": bot_module.gemini_tokens
        }

    # 2. Bot Response
    bot_reply = bot_module.ask_instant_ai(session_id, user_text=user_text)
    
    # 3. Audio Response
    if bot_reply in bot_module.PRE_RECORDED_AUDIO:
        audio_url = f"/{bot_module.PRE_RECORDED_AUDIO[bot_reply]}"
    else:
        bot_audio_path = f"static/reply_{session_id}.wav"
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, bot_module.text_to_speech_hi, bot_reply, bot_audio_path)
        audio_url = f"/{bot_audio_path}"
    
    return {
        "text": user_text,
        "answer": bot_reply,
        "audio_url": audio_url,
        "tokens": bot_module.gemini_tokens
    }


# ---------------------------------------------------------------------------
# SmartFlo WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/tata-tele")
async def smartflo_ws(websocket: WebSocket):
    """
    WebSocket handler for Tata SmartFlo bi-directional audio streaming.

    Incoming events  : connected | start | media | stop | clear
    Outgoing messages: { "event": "media", "streamSid": "...", "media": { "payload": "<base64>" } }
    """
    await websocket.accept()
    print("[SmartFlo] WebSocket connection accepted")

    session       = None
    stream_sid    = None
    session_id    = None    # maps to bot_module.sessions dict
    is_processing = False   # prevent concurrent STT/TTS
    bot_speaking  = [False] # mutable flag shared into send_audio_to_smartflo

    try:
        while True:
            message = await websocket.receive()

            if "text" not in message:
                continue  # SmartFlo only sends JSON text frames

            try:
                data = json.loads(message["text"])
            except json.JSONDecodeError:
                print("[SmartFlo] Invalid JSON — skipped")
                continue

            event_type = data.get("event", "")
            if event_type not in ["media"]:  # quiet down the audio chunk logs
                print(f"[SmartFlo WS] Received event: {event_type} | streamSid: {data.get(event_type, {}).get('streamSid', 'N/A')}")

            # ── CONNECTED ──────────────────────────────────────────────
            if event_type == "connected":
                print("[SmartFlo] 'connected' event")
                continue

            # ── START ──────────────────────────────────────────────────
            if event_type == "start":
                start_data = data.get("start", {})
                stream_sid = start_data.get("streamSid", "")
                session    = smartflo_service.create_session(start_data)
                session_id = stream_sid  # use stream_sid as bot session key

                # Split greeting into two parts to reduce initial TTFB (Time To First Byte)
                # First part is short (Greeting), Second part is longer (Subsidy intro)
                part1 = getattr(bot_module, "STATE_1_GREETING_PART1", "")
                part2 = getattr(bot_module, "STATE_1_GREETING_PART2", "")
                
                if part1 and part2:
                    print(f"[SmartFlo] Greeting Part 1: {part1}")
                    # Prepend 1.2s silence to ensure the first word isn't clipped by network delay
                    await send_audio_to_smartflo(websocket, stream_sid, part1, bot_speaking, session_id, prepend_silence_s=1.2)
                    print(f"[SmartFlo] Greeting Part 2: {part2[:60]}…")
                    await send_audio_to_smartflo(websocket, stream_sid, part2, bot_speaking, session_id)
                else:
                    greeting = bot_module.ask_instant_ai(session_id, is_start=True)
                    print(f"[SmartFlo] Greeting (Legacy): {greeting[:60]}…")
                    await send_audio_to_smartflo(websocket, stream_sid, greeting, bot_speaking, session_id, prepend_silence_s=1.2)

                # Flush any echo buffered during greeting
                smartflo_service.get_buffered_audio(stream_sid)
                continue

            # ── MEDIA (incoming caller audio) ──────────────────────────
            if event_type == "media":
                if not session or not stream_sid:
                    continue

                # Discard incoming audio while bot is speaking (echo suppression)
                if bot_speaking[0] or is_processing:
                    # Still drain the SmartFlo buffer to avoid back-pressure
                    session = smartflo_service.get_session(stream_sid)
                    if session:
                        session.audio_buffer = bytes()  # clear any accumulated echo
                    continue

                media_data    = data.get("media", {})
                audio_payload = media_data.get("payload", "")

                # Buffer audio; process only when speech appears complete
                ready_audio = smartflo_service.add_audio_to_buffer(stream_sid, audio_payload)
                if not ready_audio:
                    continue

                is_processing = True
                try:
                    # 1. STT (runs in thread pool — blocking call)
                    loop = asyncio.get_event_loop()
                    user_text = await loop.run_in_executor(
                        None, transcribe_mulaw, ready_audio
                    )

                    if not user_text:
                        print("[SmartFlo] No speech detected")
                        no_speech = bot_module.sessions.get(session_id, {}).get("no_speech", 0) + 1
                        if session_id in bot_module.sessions:
                            bot_module.sessions[session_id]["no_speech"] = no_speech

                        if no_speech >= bot_module.MAX_NO_SPEECH:
                            # Final attempt exhausted — end call
                            if session_id in bot_module.sessions:
                                bot_module.sessions[session_id]["state"] = "ENDED"
                            await send_audio_to_smartflo(websocket, stream_sid, bot_module.NO_SPEECH_END, bot_speaking, session_id, final=True)
                            break
                        else:
                            # Re-ask using RETRY_PREFIX + current-state retry question
                            current_state = bot_module.sessions.get(session_id, {}).get("state", "STATE_1")
                            retry_q = bot_module.RETRY_QUESTIONS.get(current_state, "")
                            retry_msg = bot_module.RETRY_PREFIX + retry_q if retry_q else bot_module.RETRY_PREFIX + "कृपया दोबारा बोलें।"
                            print(f"[SmartFlo] Retry {no_speech}/{bot_module.MAX_NO_SPEECH}: {retry_msg[:50]}…")
                            await send_audio_to_smartflo(websocket, stream_sid, retry_msg, bot_speaking, session_id)
                        continue

                    # Reset no-speech counter on successful transcription
                    if session_id in bot_module.sessions:
                        bot_module.sessions[session_id]["no_speech"] = 0

                    print(f"[SmartFlo] User said: '{user_text}'")

                    # 2. Bot response (pure Python — instant, no async needed)
                    bot_reply = bot_module.ask_instant_ai(session_id, user_text=user_text)
                    print(f"[SmartFlo] Bot reply: '{bot_reply[:60]}…'")

                    # 3. TTS → mu-law → stream back (mutes incoming during playback)
                    # Check if this will be the final message BEFORE sending
                    state_before = bot_module.sessions.get(session_id, {}).get("state", "")
                    is_final_reply = (state_before == "ENDED")
                    await send_audio_to_smartflo(websocket, stream_sid, bot_reply, bot_speaking, session_id, final=is_final_reply)
                    if not is_final_reply:
                        smartflo_service.get_buffered_audio(stream_sid)

                    # 4. If call ended by bot logic, close the stream
                    state = bot_module.sessions.get(session_id, {}).get("state", "")
                    if state == "ENDED":
                        print("[SmartFlo] Bot ended conversation — closing stream")
                        break

                except Exception as e:
                    print(f"[SmartFlo] Processing error: {e}")
                finally:
                    is_processing = False

                continue

            # ── STOP ───────────────────────────────────────────────────
            if event_type == "stop":
                print(f"[SmartFlo] 'stop' event — stream:{stream_sid}")
                break

            # ── CLEAR (interruption from platform) ─────────────────────
            if event_type == "clear":
                print("[SmartFlo] 'clear' event — ignoring (handled by platform)")
                continue

    except WebSocketDisconnect:
        print("[SmartFlo] WebSocket disconnected")
    except Exception as e:
        print(f"[SmartFlo] Unexpected error: {e}")
        try:
            await websocket.close()
        except:
            pass
    finally:
        if stream_sid:
            smartflo_service.end_session(stream_sid)
        if session_id and session_id in bot_module.sessions:
            del bot_module.sessions[session_id]
        # Actively close the WebSocket so SmartFlo drops the call immediately
        try:
            await websocket.close()
        except Exception:
            pass
        print("[SmartFlo] Session cleaned up")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
