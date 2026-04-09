import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
from datetime import datetime, date

from flask import Flask, render_template, request, jsonify
import speech_recognition as sr
from gtts import gTTS
import os
import uuid
import subprocess
import re
import requests
from dotenv import load_dotenv
import google.generativeai as genai
from sarvamai import SarvamAI
import base64

load_dotenv()

# ── Database (conversation logger) ────────────────────────────────────────────
from db import db

sarvam_client = SarvamAI(
    api_subscription_key="sk_1egy7shz_foVYeKo9OrfrtR454ZagxTyw",
)

app = Flask(__name__)
os.makedirs("static", exist_ok=True)

# Gemini AI setup (lightweight fallback for intent detection)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
gemini_model = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-2.5-flash-lite")

gemini_tokens = {"input": 0, "output": 0}

def track_tokens_usage(resp):
    try:
        if resp and hasattr(resp, "usage_metadata"):
            gemini_tokens["input"] += resp.usage_metadata.prompt_token_count
            gemini_tokens["output"] += resp.usage_metadata.candidates_token_count
    except Exception as e:
        print(f"Token tracking error: {e}")

def _gemini_yes_no(question):
    """Ultra-lightweight Gemini call (~20 tokens). Returns True/False/None."""
    if not gemini_model:
        return None
    try:
        resp = gemini_model.generate_content(
            question,
            generation_config=genai.GenerationConfig(max_output_tokens=3, temperature=0)
        )
        track_tokens_usage(resp)
        answer = resp.text.strip().lower()
        if "yes" in answer or "haa" in answer:
            return True
        if "no" in answer:
            return False
        return None
    except Exception as e:
        print(f"Gemini fallback error: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# NEW BOT FLOW — Mierae Solar UP Script (High-Converting Final Version)
# ─────────────────────────────────────────────────────────────────────────────

# State mapping for sessions
sessions = {}

# ── State Texts ───────────────────────────────────────────────────────────────

STATE_1_GREETING = (
    "नमस्ते! मैं Mierae Solar से Dipti बोल रही हूँ। "
    "आप अपने घर पर सोलर लगवाकर एक लाख आठ हज़ार रुपये तक की सरकारी सब्सिडी पा सकते हैं, "
    "और हर महीने चार हज़ार रुपये तक का बिजली बिल बचा सकते हैं। "
    "क्या आप सोलर के बारे में फ्री जानकारी लेना चाहेंगे?"
)

STATE_1_NO_END = (
    "कोई बात नहीं! अगर आप कभी सोलर के बारे में जानकारी लेना चाहें तो "
    "हमें इसी नंबर पर कॉल करें। "
    "Thank you for your time. Have a great day"
)

STATE_2_PROPERTY = (
    "बहुत अच्छा! सबसे पहले बताएँ, आपकी प्रॉपर्टी किस टाइप की है? "
    "क्या यह एक इंडिपेंडेंट हाउस है, अपार्टमेंट है, या कमर्शियल प्रॉपर्टी है?"
)

STATE_3_BILL = (
    "आपका औसत मासिक बिजली का बिल कितना आता है? "
    "क्या यह एक हज़ार से दो हज़ार के बीच है, "
    "दो हज़ार से पाँच हज़ार के बीच है, "
    "या पाँच हज़ार से ज़्यादा है?"
)

STATE_4_TIMELINE = (
    "आप सोलर इंस्टॉलेशन कब तक करवाना चाहते हैं? "
    "क्या एक महीने के अंदर, एक से तीन महीने के अंदर, "
    "या अभी सिर्फ़ एन्क्वायरी कर रहे हैं?"
)

STATE_5_PAYMENT = (
    "आप पेमेंट कैसे करना prefer करेंगे? "
    "फुल पेमेंट, या बैंक लोन?"
)

STATE_6_CLOSING = (
    "धन्यवाद! आपकी डिटेल्स successfully receive हो गई हैं। "
    "हमारी टीम आपको जल्दी ही contact करेगी और free home visit schedule करेगी। "
    "इस visit के दौरान, हमारे expert engineer आपकी property inspect करके "
    "best solar solution suggest करेंगे। "
    "Thank you for choosing Mierae Solar. Have a great day"
)

STATE_DISCONNECT = "धन्यवाद। कॉल समाप्त हो चुकी है। Thank you!"

# ── Retry / Error Messages ────────────────────────────────────────────────────
MAX_RETRIES = 3
MAX_NO_SPEECH = 3
RETRY_PREFIX = "मुझे लगता है आपकी बात सही से समझ नहीं आई। "
END_MISUNDERSTAND = (
    "कोई बात नहीं। अगर आप बाद में बात करना चाहें तो "
    "कृपया हमें 9070607050 पर कॉल करें। Thank you! Have a nice day."
)
NO_SPEECH_END = (
    "लगता है आपकी आवाज़ नहीं आ पा रही है। "
    "कृपया बाद में हमें 9070607050 पर कॉल करें। Thank you! Have a nice day."
)

RETRY_QUESTIONS = {
    "STATE_1": "क्या आप सोलर के बारे में फ्री जानकारी लेना चाहेंगे?",
    "STATE_2": "आपकी प्रॉपर्टी किस टाइप की है — इंडिपेंडेंट हाउस, अपार्टमेंट, या कमर्शियल?",
    "STATE_3": "आपका मासिक बिजली बिल कितना आता है?",
    "STATE_4": "सोलर इंस्टॉलेशन कब तक करवाना चाहते हैं?",
    "STATE_5": "पेमेंट फुल पेमेंट से करेंगे या बैंक लोन से?",
}

# ── Pre-recorded audio mapping ────────────────────────────────────────────────
PRE_RECORDED_AUDIO = {
    STATE_1_GREETING:  "static/pre_audio/STATE_1_GREETING.wav",
    STATE_1_NO_END:    "static/pre_audio/STATE_1_NO_END.wav",
    STATE_2_PROPERTY:  "static/pre_audio/STATE_2_PROPERTY.wav",
    STATE_3_BILL:      "static/pre_audio/STATE_3_BILL.wav",
    STATE_4_TIMELINE:  "static/pre_audio/STATE_4_TIMELINE.wav",
    STATE_5_PAYMENT:   "static/pre_audio/STATE_5_PAYMENT.wav",
    STATE_6_CLOSING:   "static/pre_audio/STATE_6_CLOSING.wav",
    STATE_DISCONNECT:  "static/pre_audio/STATE_DISCONNECT.wav",
    
    # Retry / Error pre-recordings
    END_MISUNDERSTAND: "static/pre_audio/END_MISUNDERSTAND.wav",
    NO_SPEECH_END:     "static/pre_audio/NO_SPEECH_END.wav",
    RETRY_PREFIX + "कृपया दोबारा बोलें।": "static/pre_audio/NO_SPEECH_RETRY.wav",
}

# Auto-add retry questions to pre-recorded mapping
for state_key, q_text in RETRY_QUESTIONS.items():
    full_retry_text = RETRY_PREFIX + q_text
    PRE_RECORDED_AUDIO[full_retry_text] = f"static/pre_audio/{state_key}_RETRY.wav"

# ─────────────────────────────────────────────────────────────────────────────
# Intent helpers
# ─────────────────────────────────────────────────────────────────────────────

def is_positive(text):
    text = text.lower()
    negatives_exact = {"no", "nahi", "na", "mat", "busy", "rakho", "नहीं", "ना", "मत", "बिजी"}
    negatives_substring = ["not interested", "bad me", "रहने दो", "बंद करो", "zarurat nahi", "ज़रूरत नहीं"]
    positives_exact = {
        "yes", "haa", "ha", "ji", "haan", "ok", "okay", "sure", "theek", "bilkul",
        "हाँ", "हां", "जी", "ठीक", "बिल्कुल", "चलो", "सही",
        "samjha", "samjhao", "batao", "bataiye", "bolo", "boliye",
        "sunao", "karo", "kariye", "kar", "do", "dijiye", "de",
        "chalo", "chaliye", "zaroor", "jaroor", "please",
        "समझा", "समझाओ", "बताओ", "बताइए", "बोलो", "बोलिए",
        "सुनाओ", "करो", "करिए", "दो", "दीजिए", "दे",
        "चलिए", "ज़रूर", "जरूर", "लगवाना", "चाहिए", "चाहते",
        "chahiye", "chahte", "lagwana",
    }

    for sub in negatives_substring:
        if sub in text:
            return False

    words = text.replace(".", " ").replace(",", " ").replace("।", " ").replace("?", " ").split()
    has_negative = any(w in negatives_exact for w in words)
    has_positive = any(w in positives_exact for w in words)

    if has_negative and not has_positive:
        return False
    if has_positive and not has_negative:
        return True

    result = _gemini_yes_no(
        f"The bot asked a yes/no question. Is this user reply expressing agreement, willingness, or requesting to proceed? "
        f"Note: requests like 'explain', 'tell me', 'do it' mean YES. Reply only YES or NO: {text}"
    )
    if result is not None:
        return result
    return True


def _detect_property_type(text):
    """Returns 'independent', 'apartment', 'commercial', or None."""
    text = text.lower()
    independent_kw = [
        "independent", "house", "ghar", "मकान", "घर", "kothi", "kothi",
        "bungalow", "villa", "plot", "खुद का घर",
    ]
    apartment_kw = [
        "apartment", "flat", "flats", "अपार्टमेंट", "फ्लैट", "society",
        "society", "floor", "building",
    ]
    commercial_kw = [
        "commercial", "shop", "office", "dukan", "दुकान", "ऑफिस",
        "factory", "godown", "warehouse", "mall", "showroom",
    ]
    for kw in independent_kw:
        if kw in text:
            return "independent"
    for kw in apartment_kw:
        if kw in text:
            return "apartment"
    for kw in commercial_kw:
        if kw in text:
            return "commercial"

    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"User replied to 'what type of property do you have?' in English/Hindi/Hinglish: \"{text}\"\n"
                "Reply ONLY one word: INDEPENDENT, APARTMENT, or COMMERCIAL. If unclear, reply UNCLEAR.",
                generation_config=genai.GenerationConfig(max_output_tokens=5, temperature=0)
            )
            track_tokens_usage(resp)
            ans = resp.text.strip().upper()
            if "INDEPENDENT" in ans:
                return "independent"
            if "APARTMENT" in ans:
                return "apartment"
            if "COMMERCIAL" in ans:
                return "commercial"
        except Exception as e:
            print(f"Property detect error: {e}")
    return None


def _detect_bill_range(text):
    """Returns 'low' (1k-2k), 'mid' (2k-5k), 'high' (5k+), or None."""
    text_lower = text.lower()
    text_no_commas = re.sub(r'(\d),(\d)', r'\1\2', text_lower)
    text_no_commas = re.sub(r'(\d),(\d)', r'\1\2', text_no_commas)

    nums = re.findall(r'\d+', text_no_commas)
    if nums:
        amount = int(nums[0])
        if amount >= 5000:
            return "high"
        elif amount >= 2000:
            return "mid"
        elif amount >= 1000:
            return "low"
        elif amount == 0:
            return "low"

    high_kw = ["5000", "paanch hazar", "पाँच हज़ार", "पाँच हजार", "zyada", "ज़्यादा", "adhik", "अधिक"]
    mid_kw = ["2000", "3000", "4000", "do hazar", "teen hazar", "char hazar",
              "दो हज़ार", "तीन हज़ार", "चार हज़ार"]
    low_kw = ["1000", "ek hazar", "एक हज़ार", "kam", "कम", "thoda", "थोड़ा"]

    for kw in high_kw:
        if kw in text_lower:
            return "high"
    for kw in mid_kw:
        if kw in text_lower:
            return "mid"
    for kw in low_kw:
        if kw in text_lower:
            return "low"

    # Gemini fallback
    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"User answered electricity bill amount in English/Hindi/Hinglish: \"{text}\"\n"
                "Reply ONLY: LOW (₹1000-2000), MID (₹2000-5000), HIGH (₹5000+), or UNCLEAR.",
                generation_config=genai.GenerationConfig(max_output_tokens=5, temperature=0)
            )
            track_tokens_usage(resp)
            ans = resp.text.strip().upper()
            if "HIGH" in ans:
                return "high"
            if "MID" in ans:
                return "mid"
            if "LOW" in ans:
                return "low"
        except Exception as e:
            print(f"Bill range detect error: {e}")
    return None


def _detect_timeline(text):
    """Returns '1month', '1to3months', 'enquiry', or None."""
    text_low = text.lower()
    immediate_kw = [
        "1 mahine", "ek mahine", "1 month", "one month", "jaldi",
        "turant", "abhi", "तुरंत", "अभी", "एक महीने", "जल्दी",
    ]
    medium_kw = [
        "2", "3", "do mahine", "teen mahine", "2-3", "2 se 3", "1 se 3",
        "do teen", "दो-तीन", "दो तीन", "teens",
    ]
    enquiry_kw = [
        "enquiry", "planning", "future", "soch", "baad mein", "dekhenge",
        "पूछताछ", "एन्क्वायरी", "सोच", "बाद में", "देखेंगे", "sirf",
    ]

    for kw in immediate_kw:
        if kw in text_low:
            return "1month"
    for kw in medium_kw:
        if kw in text_low:
            return "1to3months"
    for kw in enquiry_kw:
        if kw in text_low:
            return "enquiry"

    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"User answered solar installation timeline in English/Hindi/Hinglish: \"{text}\"\n"
                "Reply ONLY: 1MONTH (within 1 month), 1TO3MONTHS (1-3 months), ENQUIRY (just enquiry/future), or UNCLEAR.",
                generation_config=genai.GenerationConfig(max_output_tokens=5, temperature=0)
            )
            track_tokens_usage(resp)
            ans = resp.text.strip().upper()
            if "1MONTH" in ans:
                return "1month"
            if "1TO3MONTHS" in ans:
                return "1to3months"
            if "ENQUIRY" in ans:
                return "enquiry"
        except Exception as e:
            print(f"Timeline detect error: {e}")
    return None


def _detect_payment(text):
    """Returns 'full', 'loan', or None."""
    text_low = text.lower()
    full_kw = [
        "full", "ek baar", "ekbari", "puri", "cash", "नकद",
        "एकसाथ", "पूरी", "फुल",
    ]
    loan_kw = [
        "loan", "emi", "bank", "installment", "किस्त",
        "लोन", "बैंक", "ईएमआई", "क़िस्त",
    ]

    for kw in full_kw:
        if kw in text_low:
            return "full"
    for kw in loan_kw:
        if kw in text_low:
            return "loan"

    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"User answered payment preference for solar in English/Hindi/Hinglish: \"{text}\"\n"
                "Reply ONLY: FULL (full payment / cash) or LOAN (bank loan / EMI) or UNCLEAR.",
                generation_config=genai.GenerationConfig(max_output_tokens=5, temperature=0)
            )
            track_tokens_usage(resp)
            ans = resp.text.strip().upper()
            if "FULL" in ans:
                return "full"
            if "LOAN" in ans:
                return "loan"
        except Exception as e:
            print(f"Payment detect error: {e}")
    return None


def _retry_or_end(session_id, state):
    """Handle retry: re-ask question up to MAX_RETRIES, then end gracefully."""
    retries = sessions[session_id].get("retries", 0) + 1
    sessions[session_id]["retries"] = retries
    if retries >= MAX_RETRIES:
        sessions[session_id]["state"] = "ENDED"
        sessions[session_id]["retries"] = 0
        return END_MISUNDERSTAND
    question = RETRY_QUESTIONS.get(state, "")
    return RETRY_PREFIX + question


# ─────────────────────────────────────────────────────────────────────────────
# Main state machine
# ─────────────────────────────────────────────────────────────────────────────

# Maps each state to the question text it asked the user
_STATE_QUESTION_MAP = {
    "STATE_1": STATE_1_GREETING,
    "STATE_2": STATE_2_PROPERTY,
    "STATE_3": STATE_3_BILL,
    "STATE_4": STATE_4_TIMELINE,
    "STATE_5": STATE_5_PAYMENT,
    "STATE_6": STATE_6_CLOSING,
}

_STATE_QUESTION_MAP_EN = {
    "STATE_1": "Hello! I am Dipti speaking from Mierae Solar. By installing solar at your house, you can get a government subsidy of up to 1 lakh 8 thousand rupees, and save your electricity bill up to four thousand rupees every month. Would you like to take free information about solar?",
    "STATE_2": "Very good! Firstly tell me, what type of property do you have? Is it an independent house, apartment, or commercial property?",
    "STATE_3": "What is your average monthly electricity bill? Is it between one thousand and two thousand, between two thousand and five thousand, or more than five thousand?",
    "STATE_4": "When do you want to get the solar installation done? Within one month, within one to three months, or are you just inquiring right now?",
    "STATE_5": "How would you prefer to make the payment? Full payment, or bank loan?",
    "STATE_6": "Thank you! Your details have been successfully received. Our team will contact you shortly and schedule a free home visit. During this visit, our expert engineer will inspect your property and suggest the best solar solution. Thank you for choosing Mierae Solar. Have a great day",
}


def ask_instant_ai(session_id, user_text=None, is_start=False):
    if session_id not in sessions:
        sessions[session_id] = {
            "state": "STATE_1",
            "retries": 0,
            "data": {},
            "turn": 0,           # Q&A exchange counter
        }

    state = sessions[session_id]["state"]

    if is_start:
        return STATE_1_GREETING

    user_text_safe = str(user_text).strip()
    user_text_low = user_text_safe.lower()

    # Helper: log a completed Q&A exchange to DB
    def _log_exchange(answer: str):
        """Log (question asked in this state, user's answer) to the DB."""
        turn = sessions[session_id]["turn"] + 1
        sessions[session_id]["turn"] = turn
        question_text = _STATE_QUESTION_MAP_EN.get(state, state)
        db.add_exchange(session_id, question_text, answer, state, turn)

    # Helper: mark call complete in DB
    def _finish_call(status="completed"):
        lead = sessions[session_id].get("data", {})
        db.complete_call(session_id, lead_data=lead, status=status)

    # ── STATE_1: Opening — interested in solar info? ──────────────────────────
    if state == "STATE_1":
        if is_positive(user_text_low):
            _log_exchange(user_text_safe)
            sessions[session_id]["retries"] = 0
            sessions[session_id]["state"] = "STATE_2"
            return STATE_2_PROPERTY
        else:
            _log_exchange(user_text_safe)
            sessions[session_id]["state"] = "ENDED"
            _finish_call(status="not_interested")
            return STATE_1_NO_END

    # ── STATE_2: Property Type ────────────────────────────────────────────────
    elif state == "STATE_2":
        prop = _detect_property_type(user_text_low)
        if prop is None:
            return _retry_or_end(session_id, "STATE_2")
        _log_exchange(user_text_safe)
        sessions[session_id]["data"]["property_type"] = prop
        sessions[session_id]["retries"] = 0
        sessions[session_id]["state"] = "STATE_3"
        return STATE_3_BILL

    # ── STATE_3: Monthly Bill Range ───────────────────────────────────────────
    elif state == "STATE_3":
        bill = _detect_bill_range(user_text_low)
        if bill is None:
            return _retry_or_end(session_id, "STATE_3")
        _log_exchange(user_text_safe)
        sessions[session_id]["data"]["bill_range"] = bill
        sessions[session_id]["retries"] = 0
        sessions[session_id]["state"] = "STATE_4"
        return STATE_4_TIMELINE

    # ── STATE_4: Timeline ─────────────────────────────────────────────────────
    elif state == "STATE_4":
        timeline = _detect_timeline(user_text_low)
        if timeline is None:
            return _retry_or_end(session_id, "STATE_4")
        _log_exchange(user_text_safe)
        sessions[session_id]["data"]["timeline"] = timeline
        sessions[session_id]["retries"] = 0
        sessions[session_id]["state"] = "STATE_5"
        return STATE_5_PAYMENT

    # ── STATE_5: Payment Preference ───────────────────────────────────────────
    elif state == "STATE_5":
        payment = _detect_payment(user_text_low)
        if payment is None:
            return _retry_or_end(session_id, "STATE_5")
        _log_exchange(user_text_safe)
        sessions[session_id]["data"]["payment"] = payment
        sessions[session_id]["retries"] = 0
        sessions[session_id]["state"] = "STATE_6"
        print(f"[Session {session_id}] Lead Data: {sessions[session_id]['data']}")
        _finish_call(status="completed")
        return STATE_6_CLOSING

    # ── STATE_6: Closing / any further input ─────────────────────────────────
    elif state in ("STATE_6", "ENDED"):
        sessions[session_id]["state"] = "ENDED"
        return STATE_DISCONNECT

    return STATE_1_GREETING


# ─────────────────────────────────────────────────────────────────────────────
# TTS & Audio
# ─────────────────────────────────────────────────────────────────────────────

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

def _humanize_text(text):
    """Preprocess Hindi text for friendly, calm delivery."""
    t = text
    t = t.replace("।", "।,  ")
    t = t.replace("?", "?, ")
    t = t.replace("!", "!, ")
    t = t.replace(". ", "., ")
    return t.strip()

def text_to_speech_hi(text, output_path):
    try:
        response = sarvam_client.text_to_speech.convert(
            text=text,
            target_language_code="hi-IN",
            speaker="roopa",
            pace=1.1,
            speech_sample_rate=22050,
            enable_preprocessing=True,
            model="bulbul:v3"
        )
        audio_data = base64.b64decode(response.audios[0])
        with open(output_path, 'wb') as f:
            f.write(audio_data)
        return output_path
    except Exception as e:
        print(f"Sarvam TTS failed: {e}")
        # Google Fallback
        tts = gTTS(text=text, lang="hi")
        tts.save(output_path)
        return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Flask Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/solar_test")
def index():
    return render_template("solar_test.html")

@app.route("/start_call", methods=["POST"])
def start_call():
    session_id = str(uuid.uuid4())
    # Caller mobile number — from form field if browser test sends it
    mobile = request.form.get("mobile_number", "unknown")
    bot_reply = ask_instant_ai(session_id, is_start=True)

    # Register call in DB
    db.create_call(session_id, mobile_number=mobile)

    if bot_reply in PRE_RECORDED_AUDIO:
        audio_url = f"/{PRE_RECORDED_AUDIO[bot_reply]}"
    else:
        print("not found pre recorded audio")
        audio_file = f"static/intro_{session_id}.wav"
        text_to_speech_hi(bot_reply, audio_file)
        audio_url = f"/{audio_file}"

    return jsonify({
        "session_id": session_id,
        "text": bot_reply,
        "audio_url": audio_url,
        "tokens": gemini_tokens
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    session_id = request.form.get("session_id")
    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid or expired session. Please start a new call."}), 400

    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided."}), 400

    file = request.files["audio"]
    user_audio_path = f"static/user_audio_{session_id}.webm"
    file.save(user_audio_path)

    user_text = ""
    try:
        wav_path = f"static/temp_{session_id}.wav"
        ffmpeg_result = subprocess.run(
            ["ffmpeg", "-y", "-i", user_audio_path, "-ac", "1", "-ar", "16000", wav_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        if ffmpeg_result.returncode != 0:
            print(f"[Session {session_id}] ffmpeg conversion failed: {ffmpeg_result.stderr.decode('utf-8', errors='ignore')[-200:]}")
            raise Exception("ffmpeg conversion failed")

        if not os.path.exists(wav_path):
            print(f"[Session {session_id}] WAV file not created after ffmpeg")
            raise Exception("WAV file not created")

        wav_size = os.path.getsize(wav_path)
        webm_size = os.path.getsize(user_audio_path) if os.path.exists(user_audio_path) else 0
        print(f"[Session {session_id}] Audio sizes - WebM: {webm_size}B, WAV: {wav_size}B")

        if wav_size < 5000:
            print(f"[Session {session_id}] WAV file too small ({wav_size}B), likely silence")
            raise Exception("Audio too short or silent")

        r = sr.Recognizer()
        r.energy_threshold = 300
        with sr.AudioFile(wav_path) as source:
            audio_data = r.record(source)
        user_text = r.recognize_google(audio_data, language="en-IN")
        print(f"[Session {session_id}] Transcription: '{user_text}'")

        os.remove(wav_path)
    except sr.UnknownValueError:
        print(f"[Session {session_id}] Google Speech could not understand audio")
        user_text = ""
        try: os.remove(wav_path)
        except: pass
    except sr.RequestError as e:
        print(f"[Session {session_id}] Google Speech API error: {e}")
        user_text = ""
        try: os.remove(wav_path)
        except: pass
    except Exception as e:
        print(f"[Session {session_id}] Transcription error: {e}")
        user_text = ""

    try:
        os.remove(user_audio_path)
    except:
        pass

    if not user_text:
        no_speech_count = sessions[session_id].get("no_speech", 0) + 1
        sessions[session_id]["no_speech"] = no_speech_count
        print(f"[Session {session_id}] No speech detected ({no_speech_count}/{MAX_NO_SPEECH})")

        if no_speech_count >= MAX_NO_SPEECH:
            sessions[session_id]["state"] = "ENDED"
            sessions[session_id]["no_speech"] = 0
            bot_audio_path = f"static/reply_{session_id}.wav"
            text_to_speech_hi(NO_SPEECH_END, bot_audio_path)
            return jsonify({
                "text": "[No speech detected]",
                "answer": NO_SPEECH_END,
                "audio_url": f"/{bot_audio_path}",
                "tokens": gemini_tokens
            })

        return jsonify({
            "text": "[No speech detected]",
            "answer": "मुझे आपकी आवाज़ नहीं आ रही है। कृपया दोहराएँ।",
            "audio_url": "",
            "tokens": gemini_tokens
        })

    # Reset no-speech counter on successful detection
    sessions[session_id]["no_speech"] = 0

    bot_reply = ask_instant_ai(session_id, user_text=user_text)
    print(f"[Session {session_id}] Bot Reply: {bot_reply[:60]}...")

    if bot_reply in PRE_RECORDED_AUDIO:
        audio_url = f"/{PRE_RECORDED_AUDIO[bot_reply]}"
    else:
        bot_audio_path = f"static/reply_{session_id}.wav"
        text_to_speech_hi(bot_reply, bot_audio_path)
        audio_url = f"/{bot_audio_path}"

    return jsonify({
        "text": user_text,
        "answer": bot_reply,
        "audio_url": audio_url,
        "tokens": gemini_tokens
    })

if __name__ == "__main__":
    app.run(debug=True, port=8080)
