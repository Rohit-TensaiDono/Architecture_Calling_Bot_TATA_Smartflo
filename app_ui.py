from flask import Flask, render_template, request, jsonify
import uuid

from solar_webhook import handle_user_input

app = Flask(__name__)

sessions_ui = {}

# ── HOME PAGE ─────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


# ── CHAT API ─────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_text = data.get("text", "")
    session_id = data.get("session_id")

    if not session_id:
        session_id = str(uuid.uuid4())

    if session_id not in sessions_ui:
        sessions_ui[session_id] = {}

    session = sessions_ui[session_id]

    response = handle_user_input(session, user_text)

    bot_text = response["text"]

    # 🔥 SIMPLE TRANSLATION (quick hack)
    translated = translate_to_english(bot_text)

    return jsonify({
        "session_id": session_id,
        "user_text": user_text,
        "bot_text": bot_text,
        "bot_text_en": translated
    })


# ── BASIC TRANSLATION (TEMP) ─────────────
def translate_to_english(text):
    # You can later replace with Gemini / Google Translate
    return f"[EN] {text}"


if __name__ == "__main__":
    app.run(port=5000, debug=True)