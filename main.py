import uuid
import requests
import os
import json
import base64
import uuid
import asyncio
import audioop
import wave
import io

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from solar_webhook import handle_user_input
from smartflo_server import transcribe_mulaw

app = FastAPI()

# 🔴 UPDATE EVERY TIME NGROK RESTARTS
BASE_URL = "https://yard-ladies-nuclei.ngrok-free.dev"

SMARTFLO_API_KEY = os.getenv("SMARTFLO_API_KEY", "YOUR_API_KEY")
SMARTFLO_CALLER_ID = os.getenv("SMARTFLO_CALLER_ID", "918065264108")

SMARTFLO_URL = "https://api-smartflo.tatateleservices.com/v1/click_to_call_support"

sessions = {}

def wav_to_mulaw(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes), 'rb') as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        pcm_data = wf.readframes(wf.getnframes())

    # 🔁 Convert to mono if needed
    if n_channels > 1:
        pcm_data = audioop.tomono(pcm_data, sampwidth, 1, 1)

    # 🔁 Resample to 8000 Hz if needed
    if framerate != 8000:
        pcm_data, _ = audioop.ratecv(
            pcm_data, sampwidth, 1, framerate, 8000, None
        )

    # 🔁 Convert PCM → μ-law
    mulaw_data = audioop.lin2ulaw(pcm_data, sampwidth)

    return mulaw_data

# =========================
# 📞 OUTBOUND CALL TRIGGER
# =========================
@app.post("/call")
async def trigger_call(request: Request):
    try:
        data = await request.json()
        number = data.get("number")

        if not number:
            return JSONResponse({"error": "number required"}, status_code=400)

        payload = {
            "async": 1,
            "customer_number": number,
            "customer_ring_timeout": 15,
            "caller_id": SMARTFLO_CALLER_ID,
            "api_key": SMARTFLO_API_KEY
        }

        headers = {
            "accept": "application/json",
            "content-type": "application/json"
        }

        print(f"📞 Calling: {number}")

        response = requests.post(SMARTFLO_URL, json=payload, headers=headers)

        print("📞 Smartflo Response:", response.text)

        return response.json()

    except Exception as e:
        print("❌ CALL ERROR:", e)
        return {"error": str(e)}


# =========================
# 🎤 WEBHOOK (LEGACY / TEST)
# =========================
@app.post("/webhook")
async def webhook(request: Request):
    print("🔥 WEBHOOK HIT")

    try:
        form = await request.form()
        files = form

        session_id = form.get("call_id") or str(uuid.uuid4())

        if session_id not in sessions:
            sessions[session_id] = {
                "state": "STATE_1",
                "retries": 0,
                "data": {}
            }

        session = sessions[session_id]

        # FIRST CALL (NO AUDIO)
        if "audio" not in files:
            response = handle_user_input(session, None)

            audio_path = response.get("audio_path", "")
            return {
                "audio": f"{BASE_URL}/{audio_path}",
                "end": response.get("end", False)
            }

        # AUDIO RECEIVED
        audio_bytes = await files["audio"].read()

        user_text = transcribe_mulaw(audio_bytes)
        print("[USER]:", user_text)

        if not user_text or len(user_text.strip()) < 2:
            return {
                "audio": f"{BASE_URL}/static/pre_audio/NO_SPEECH_RETRY.wav",
                "end": False
            }

        response = handle_user_input(session, user_text)

        if response.get("end"):
            session["state"] = "ENDED"

        return {
            "audio": f"{BASE_URL}/{response.get('audio_path')}",
            "end": response.get("end", False)
        }

    except Exception as e:
        print("❌ ERROR:", e)
        return {"error": str(e)}


# =========================
# 🔊 STATIC FILES
# =========================
app.mount("/static", StaticFiles(directory="static"), name="static")


# =========================
# 🔁 WEBSOCKET STREAMING
# =========================
@app.websocket("/ws/tata-tele")
async def tata_tele_ws(websocket: WebSocket):
    await websocket.accept()
    print("🔗 Smartflo connected (streaming)")

    session_id = str(uuid.uuid4())
    session = {
        "state": "STATE_1",
        "retries": 0,
        "data": {}
    }

    stream_sid = None
    buffer = b""
    bot_speaking = False

    try:
        while True:
            msg = await websocket.receive()

            # 🔴 Disconnect
            if msg["type"] == "websocket.disconnect":
                print("📴 Client disconnected")
                break

            if "text" not in msg or not msg["text"]:
                continue

            data = json.loads(msg["text"])
            event = data.get("event")

            print("📩 EVENT:", event)

            # =========================
            # CONNECT
            # =========================
            if event == "connected":
                continue

            # =========================
            # START
            # =========================
            if event == "start":
                stream_sid = data["streamSid"]
                print("📞 Call started:", stream_sid)
                continue

            # =========================
            # MEDIA (AUDIO IN)
            # =========================
            if event == "media":

                # 🔇 Ignore mic while bot is speaking
                if bot_speaking:
                    continue

                payload = data["media"]["payload"]
                audio_chunk = base64.b64decode(payload)

                print("🎧 chunk:", len(audio_chunk))

                buffer += audio_chunk

                # 🔁 ~1 sec audio
                if len(buffer) >= 8000:
                    user_text = transcribe_mulaw(buffer)
                    print("🗣 USER:", user_text)

                    buffer = b""

                    if not user_text or len(user_text.strip()) < 2:
                        continue

                    # 🤖 BOT RESPONSE
                    response = handle_user_input(session, user_text)
                    audio_path = response.get("audio_path")

                    if audio_path and stream_sid:
                        bot_speaking = True

                        with open(audio_path, "rb") as f:
                            wav_bytes = f.read()

                        # 🔥 Convert WAV → μ-law 8kHz
                        mulaw_audio = wav_to_mulaw(wav_bytes)

                        print("🔊 TTS bytes:", len(mulaw_audio))

                        # 🔇 Add initial silence (prevents clipping)
                        mulaw_audio = (b"\xff" * 8000) + mulaw_audio

                        # 🔁 Send in 20ms frames (160 bytes)
                        chunk_size = 160

                        for i in range(0, len(mulaw_audio), chunk_size):
                            chunk = mulaw_audio[i:i + chunk_size]

                            msg_out = {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {
                                    "payload": base64.b64encode(chunk).decode()
                                }
                            }

                            await websocket.send_text(json.dumps(msg_out))
                            await asyncio.sleep(0.02)  # 🔥 REAL-TIME pacing

                        print("🔊 Sent response audio")

                        bot_speaking = False

                    if response.get("end"):
                        print("🔚 Ending session")
                        await asyncio.sleep(2)  # allow playback to finish
                        break

            # =========================
            # STOP
            # =========================
            if event == "stop":
                print("📴 Call ended by Smartflo")
                break

    except Exception as e:
        print("❌ WebSocket Error:", e)

