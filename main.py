from flask import Flask, request, jsonify, send_from_directory
import uuid
import requests
import os

from solar_webhook import handle_user_input
from smartflo_server import transcribe_mulaw

app = Flask(__name__)

# 🔴 UPDATE THIS EVERY TIME NGROK RESTARTS
BASE_URL = "https://yard-ladies-nuclei.ngrok-free.dev"

# 🔐 USE ENV VARIABLES (recommended)
SMARTFLO_API_KEY = os.getenv("SMARTFLO_API_KEY", "YOUR_API_KEY")
SMARTFLO_CALLER_ID = os.getenv("SMARTFLO_CALLER_ID", "918065254018")

SMARTFLO_URL = "https://api-smartflo.tatateleservices.com/v1/click_to_call_support"

sessions = {}


# =========================
# 📞 OUTBOUND CALL TRIGGER
# =========================
@app.route("/call", methods=["POST"])
def trigger_call():
    try:
        data = request.json
        number = data.get("number")

        if not number:
            return {"error": "number required"}, 400

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

        return jsonify(response.json())

    except Exception as e:
        print("❌ CALL ERROR:", e)
        return jsonify({"error": str(e)})


# =========================
# 🎤 WEBHOOK (BOT ENGINE)
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    print("🔥 WEBHOOK HIT")

    try:
        form = request.form
        files = request.files

        print("FORM:", form)
        print("FILES:", files)

        session_id = form.get("call_id") or str(uuid.uuid4())

        # INIT SESSION
        if session_id not in sessions:
            sessions[session_id] = {
                "state": "STATE_1",
                "retries": 0,
                "data": {}
            }

        session = sessions[session_id]

        print("STATE:", session["state"])

        # 🎯 FIRST CALL (NO AUDIO)
        if "audio" not in files:
            response = handle_user_input(session, None)

            audio_path = response.get("audio_path", "")
            full_audio_url = f"{BASE_URL}/{audio_path}"

            return jsonify({
                "audio": full_audio_url,
                "end": response.get("end", False)
            })

        # 🎧 AUDIO RECEIVED
        audio_file = files["audio"]
        mulaw_bytes = audio_file.read()

        print("Audio bytes size:", len(mulaw_bytes))

        # → STT
        user_text = transcribe_mulaw(mulaw_bytes)
        print("[USER]:", user_text)

        # 🔁 NO SPEECH HANDLING
        if not user_text or len(user_text.strip()) < 2:
            retry_audio = f"{BASE_URL}/static/pre_audio/NO_SPEECH_RETRY.wav"
            return jsonify({
                "audio": retry_audio,
                "end": False
            })

        # → BOT LOGIC
        response = handle_user_input(session, user_text)

        audio_path = response.get("audio_path", "")
        full_audio_url = f"{BASE_URL}/{audio_path}"

        if response.get("end"):
            session["state"] = "ENDED"

        return jsonify({
            "audio": full_audio_url,
            "end": response.get("end", False)
        })

    except Exception as e:
        print("❌ ERROR:", e)
        return jsonify({"error": str(e)})


# =========================
# 🔊 SERVE AUDIO FILES
# =========================
@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory("static", filename)


# =========================
# 🚀 START SERVER
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)