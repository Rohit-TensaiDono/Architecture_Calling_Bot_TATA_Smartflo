from flask import Flask, request, jsonify, render_template, send_file
import uuid
import io

from pydub import AudioSegment

from solar_webhook import handle_user_input
from smartflo_server import transcribe_mulaw, audio_converter

# optional translation
try:
    from deep_translator import GoogleTranslator
    def translate_to_english(text):
        return GoogleTranslator(source='auto', target='en').translate(text)
except:
    def translate_to_english(text):
        return text


app = Flask(__name__)

sessions = {}


@app.route("/")
def home():
    return render_template("voice_ui.html")


@app.route("/step", methods=["POST"])
def step():
    audio_file = request.files.get("audio")
    session_id = request.form.get("session_id")

    if not session_id:
        session_id = str(uuid.uuid4())

    # INIT SESSION
    if session_id not in sessions:
        sessions[session_id] = {
            "state": "STATE_1",
            "retries": 0,
            "data": {}
        }

    session = sessions[session_id]

    # 🚨 HARD STOP (MOST IMPORTANT FIX)
    if session.get("state") in ("STATE_6", "ENDED"):
        print(f"[INFO] Ignoring request — session ended ({session_id})")

        return jsonify({
            "session_id": session_id,
            "end": True
        })

    try:
        audio_bytes = audio_file.read()

        # 🔒 ignore tiny audio
        if len(audio_bytes) < 2000:
            return jsonify({
                "session_id": session_id,
                "audio": "/audio?path=static/pre_audio/NO_SPEECH_RETRY.wav",
                "end": False
            })

        audio = AudioSegment.from_file(
            io.BytesIO(audio_bytes),
            format="webm"
        )

        # → WAV
        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_bytes = wav_io.getvalue()

        # → MULAW
        mulaw = audio_converter.wav_to_mulaw(wav_bytes)

        # → STT
        user_text = transcribe_mulaw(mulaw)
        print("[USER]:", user_text)

        # 🔁 NO SPEECH
        if not user_text or len(user_text.strip()) < 2:
            return jsonify({
                "session_id": session_id,
                "audio": "/audio?path=static/pre_audio/NO_SPEECH_RETRY.wav",
                "end": False
            })

        # → BOT
        response = handle_user_input(session, user_text)

        bot_text = response.get("text", "")
        audio_path = response.get("audio_path", "")
        end_call = response.get("end", False)  # ✅ FIXED

        # → TRANSLATION
        user_en = translate_to_english(user_text)
        bot_en = translate_to_english(bot_text)

        # 🚨 FINAL END GUARD
        if end_call:
            session["state"] = "ENDED"

        return jsonify({
            "session_id": session_id,
            "user_text": user_text,
            "user_en": user_en,
            "bot_text": bot_text,
            "bot_en": bot_en,
            "audio": f"/audio?path={audio_path}",
            "end": end_call
        })

    except Exception as e:
        print("❌ ERROR:", e)
        return jsonify({"error": str(e)})   

@app.route("/audio")
def serve_audio():
    path = request.args.get("path")
    return send_file(path, mimetype="audio/wav")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)