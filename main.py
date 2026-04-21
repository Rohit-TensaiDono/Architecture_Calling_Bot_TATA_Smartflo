import uuid
import requests
import os
import json
import base64
import asyncio

from fastapi import FastAPI, Request, WebSocket
from fastapi.staticfiles import StaticFiles

from solar_webhook import handle_user_input
from smartflo_server import transcribe_mulaw
from smartflo_audio import audio_converter

app = FastAPI()

BASE_URL = os.getenv("BASE_URL", "https://your-ngrok-url")

SMARTFLO_API_KEY = os.getenv("SMARTFLO_API_KEY")
SMARTFLO_CALLER_ID = os.getenv("SMARTFLO_CALLER_ID")

SMARTFLO_URL = "https://api-smartflo.tatateleservices.com/v1/click_to_call_support"

sessions = {}

# =========================
# 📞 CALL TRIGGER
# =========================
@app.post("/call")
async def trigger_call(request: Request):
    data = await request.json()
    number = data.get("number")

    if not number:
        return {"error": "number required"}

    payload = {
        "async": 1,
        "customer_number": number,
        "customer_ring_timeout": 15,
        "caller_id": SMARTFLO_CALLER_ID,
        "api_key": SMARTFLO_API_KEY
    }

    response = requests.post(SMARTFLO_URL, json=payload)
    return response.json()


# =========================
# STATIC
# =========================
app.mount("/static", StaticFiles(directory="static"), name="static")


# =========================
# WEBSOCKET
# =========================
@app.websocket("/ws/tata-tele")
async def tata_tele_ws(websocket: WebSocket):
    await websocket.accept()
    print("🔗 Smartflo connected")

    stream_sid = None
    session_id = None

    bot_speaking = False
    listening_enabled = False
    is_processing = False

    buffer = b""
    last_process_time = 0

    async def send_audio(text, final=False):
        nonlocal bot_speaking, listening_enabled

        bot_speaking = True
        listening_enabled = False

        try:
            response = handle_user_input(
                sessions[session_id],
                None if text == "__GREETING__" else text
            )

            audio_path = response.get("audio_path")

            if not audio_path:
                return

            with open(audio_path, "rb") as f:
                wav_bytes = f.read()

            mulaw_audio = audio_converter.wav_to_mulaw(wav_bytes)

            mulaw_audio = (b"\xff" * 1500) + mulaw_audio
            chunk_size = 1600

            for i in range(0, len(mulaw_audio), chunk_size):
                chunk = mulaw_audio[i:i + chunk_size]

                msg = {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {
                        "payload": base64.b64encode(chunk).decode()
                    }
                }

                await websocket.send_text(json.dumps(msg))

                try:
                    await asyncio.wait_for(websocket.receive(), timeout=0.01)
                except:
                    pass

            # allow playback to finish
            await asyncio.sleep(len(mulaw_audio) / 8000 + 0.4)

        finally:
            bot_speaking = False
            listening_enabled = True   # 🔥 ONLY NOW we listen

    try:
        while True:
            msg = await websocket.receive()

            if "text" not in msg:
                continue

            data = json.loads(msg["text"])
            event = data.get("event")

            # ================= START =================
            if event == "start":
                start_data = data.get("start", {})
                stream_sid = start_data.get("streamSid")
                session_id = stream_sid

                customer_number = (
                    start_data.get("to")
                    or start_data.get("from")
                    or "unknown"
                )

                print(f"📞 Call started | {customer_number}")

                sessions[session_id] = {
                    "state": "STATE_1",
                    "data": {},
                    "number": customer_number
                }

                await send_audio("__GREETING__")
                continue

            # ================= MEDIA =================
            if event == "media":

                # 🔥 HARD CONTROL
                if not listening_enabled or bot_speaking or is_processing:
                    continue

                payload = data["media"].get("payload")
                if not payload:
                    continue

                audio_chunk = base64.b64decode(payload)
                buffer += audio_chunk

                now = asyncio.get_event_loop().time()

                # 🔥 TIME + COOLDOWN CONTROL
                if len(buffer) > 2000 and (now - last_process_time) > 1.2:
                    temp = buffer
                    buffer = b""
                    last_process_time = now

                    is_processing = True
                    listening_enabled = False  # stop listening while processing

                    try:
                        loop = asyncio.get_event_loop()

                        user_text = await loop.run_in_executor(
                            None, transcribe_mulaw, temp
                        )

                        print("🗣 USER:", user_text)

                        # 🔥 ignore noise / fragments
                        if not user_text or len(user_text.split()) < 2:
                            print("⚠️ Ignoring short/empty input")
                            listening_enabled = True
                            continue

                        response = handle_user_input(sessions[session_id], user_text)

                        bot_text = response.get("text", "")
                        is_end = response.get("end", False)

                        await send_audio(bot_text, final=is_end)

                        if is_end:
                            print("📴 Ending call")
                            await websocket.close()
                            break

                    finally:
                        is_processing = False

                continue

            # ================= STOP =================
            if event == "stop":
                print("📴 Call stopped")
                break

    except Exception as e:
        print("❌ WS ERROR:", e)

    finally:
        try:
            await websocket.close()
        except:
            pass

        if session_id in sessions:
            del sessions[session_id]

        print("🧹 Session cleaned")


