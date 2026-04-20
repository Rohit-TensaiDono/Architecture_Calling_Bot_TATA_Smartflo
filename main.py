from flask import Flask, request, jsonify, send_from_directory
import uuid

from solar_webhook import handle_user_input
from smartflo_server import transcribe_mulaw

app = Flask(__name__)

# 🔴 IMPORTANT: replace this every time ngrok restarts
BASE_URL = "https://yard-ladies-nuclei.ngrok-free.dev"

sessions = {}


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

        # → STT
        user_text = transcribe_mulaw(mulaw_bytes)
        print("[USER]:", user_text)

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


# ✅ THIS SERVES YOUR AUDIO FILES PUBLICLY
@app.route("/static/<path:filename>")
def serve_static(filename):
    return send_from_directory("static", filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)