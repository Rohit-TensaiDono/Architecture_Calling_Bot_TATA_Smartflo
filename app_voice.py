from flask import Flask, request, jsonify, send_file, render_template
import uuid
import io

from pydub import AudioSegment

from smartflo_server import transcribe_mulaw, audio_converter
from solar_webhook import handle_user_input

app = Flask(__name__)
sessions_ui = {}


# ── HOME ─────────────────────────────
@app.route("/")
def index():
    return render_template("voice.html")


# ── VOICE API ─────────────────────────
@app.route("/voice", methods=["POST"])
def voice():
    audio_file = request.files["audio"]
    session_id = request.form.get("session_id")

    if not session_id:
        session_id = str(uuid.uuid4())

    if session_id not in sessions_ui:
        sessions_ui[session_id] = {}

    session = sessions_ui[session_id]

    try:
        # ── READ RAW AUDIO (WEBM) ─────────
        audio_bytes = audio_file.read()

        # ── CONVERT WEBM → WAV ────────────
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="webm")

        wav_io = io.BytesIO()
        audio.export(wav_io, format="wav")
        wav_data = wav_io.getvalue()

        # ── WAV → MULAW ───────────────────
        mulaw = audio_converter.wav_to_mulaw(wav_data)

        # ── STT ───────────────────────────
        user_text = transcribe_mulaw(mulaw)

        if not user_text:
            return jsonify({"error": "No speech detected"})

        # ── BOT ───────────────────────────
        response = handle_user_input(session, user_text)

        bot_text = response["text"]
        bot_audio_path = response["audio_path"]

        return jsonify({
            "session_id": session_id,
            "user_text": user_text,
            "bot_text": bot_text,
            "audio_url": f"/audio?path={bot_audio_path}"
        })

    except Exception as e:
        print("❌ Voice pipeline error:", e)
        return jsonify({"error": str(e)})


# ── AUDIO SERVE ───────────────────────
@app.route("/audio")
def audio():
    path = request.args.get("path")
    return send_file(path, mimetype="audio/wav")


# ── RUN ───────────────────────────────
if __name__ == "__main__":
    app.run(port=5000, debug=True)