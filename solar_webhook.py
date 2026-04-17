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
    "ନମସ୍କାର! ମୁଁ Mierae Solar ରୁ ଦୀପ୍ତି କହୁଛି। "
    "ଆପଣ ନିଜ ଘରେ ସୋଲାର ଲଗାଇ ଏକ ଲକ୍ଷ ଅଠତିରିଶି ହଜାର ଟଙ୍କା ପର୍ଯ୍ୟନ୍ତ ସରକାରୀ ସବସିଡି ପାଇପାରିବେ, "
    "ଏବଂ ପ୍ରତିମାସ ଚାରି ହଜାର ଟଙ୍କା ପର୍ଯ୍ୟନ୍ତ ବିଦ୍ୟୁତ ବିଲ୍ ବଞ୍ଚାଇପାରିବେ। "
    "ଆପଣ ସୋଲାର ବିଷୟରେ ମାଗଣା ସୂଚନା ନେବାକୁ ଇଚ୍ଛା କରିବେ କି?"
)

STATE_1_NO_END = (
    "କିଛି ନୁହେଁ! ଯଦି ଆପଣ ପରେ ସୋଲାର ବିଷୟରେ ଜାଣିବାକୁ ଚାହାନ୍ତି, "
    "ତେବେ ଏହି ନମ୍ବରରେ ଆମକୁ କଲ୍ କରନ୍ତୁ। "
    "ଧନ୍ୟବାଦ! ଆପଣଙ୍କ ଦିନଟି ଭଲ କଟୁ"
)

STATE_2_PROPERTY = (
    "ଆପଣଙ୍କ ପ୍ରୋପର୍ଟି କଣ ପ୍ରକାରର? "
    "ସ୍ୱତନ୍ତ୍ର ଘର, ଆପାର୍ଟମେଣ୍ଟ, କିମ୍ବା ବ୍ୟବସାୟିକ ପ୍ରୋପର୍ଟି?"
)

STATE_3_BILL = (
    "ଆପଣଙ୍କ ମାସିକ ବିଦ୍ୟୁତ ବିଲ୍ କେତେ ଆସେ?"
)

STATE_4_TIMELINE = (
    "ଆପଣ କେବେ ସୋଲାର ଇନ୍ସଟଲେସନ୍ କରିବାକୁ ଚାହୁଁଛନ୍ତି?"
)

STATE_5_PAYMENT = (
    "ଆପଣ କିପରି ପେମେଣ୍ଟ କରିବେ? ପୁରା ପେମେଣ୍ଟ କିମ୍ବା ବ୍ୟାଙ୍କ ଲୋନ୍?"
)

STATE_6_CLOSING = (
    "ଧନ୍ୟବାଦ! ଆମ ଟିମ୍ ଶୀଘ୍ର ଆପଣଙ୍କୁ ସମ୍ପର୍କ କରିବ।"
)

STATE_DISCONNECT = "ଧନ୍ୟବାଦ। କଲ୍ ସମାପ୍ତ।"


# ── Retry / Error Messages ────────────────────────────────────────────────────
MAX_RETRIES = 3
MAX_NO_SPEECH = 3
RETRY_PREFIX = "ମୁଁ ଠିକ୍ ବୁଝିପାରିନି। "

END_MISUNDERSTAND = "ଦୟାକରି ପରେ କଲ୍ କରନ୍ତୁ। ଧନ୍ୟବାଦ।"

NO_SPEECH_END = "ଆପଣଙ୍କ ଆବାଜ ଆସୁନାହିଁ। ପରେ କଲ୍ କରନ୍ତୁ।"

RETRY_QUESTIONS = {
    "STATE_1": "ଆପଣ ସୋଲାର ବିଷୟରେ ମାଗଣା ସୂଚନା ନେବାକୁ ଇଚ୍ଛା କରିବେ କି?",
    "STATE_2": "ଆପଣଙ୍କ ପ୍ରୋପର୍ଟି କଣ ପ୍ରକାରର?",
    "STATE_3": "ଆପଣଙ୍କ ବିଦ୍ୟୁତ ବିଲ୍ କେତେ ଆସେ?",
    "STATE_4": "ଆପଣ କେବେ ସୋଲାର ଲଗାଇବେ?",
    "STATE_5": "ପେମେଣ୍ଟ କିପରି କରିବେ?"
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
    text = text.lower().strip()

    # ✅ DEFINE FIRST
    positives_exact = {
        "yes", "haa", "ha", "haan", "ji", "ok", "okay", "sure",
        "हाँ", "हां", "जी",

        # Odia
        "ହଁ", "ହାଁ", "ଠିକ୍", "ଚାହୁଁଛି",

        # conversational intent
        "କୁହ", "କୁହନ୍ତୁ", "କହ", "ବୁଝା",
    }

    negatives_exact = {
        "no", "nahi", "na", "नहीं", "ना",
        "ନା", "ନାହିଁ"
    }

    # ✅ THEN extend
    positives_exact.update([
        "ହ୍ୟାଲୋ", "ନମସ୍କାର", "କେମିତି", "କିଏ", "ଆଜ୍ଞା",
        "hello", "hi"
    ])

    # ── logic ──
    words = text.split()

    has_positive = any(w in positives_exact for w in words)
    has_negative = any(w in negatives_exact for w in words)

    if has_negative and not has_positive:
        return False
    if has_positive:
        return True

    return True

def _detect_property_type(text):
    """Returns 'independent', 'apartment', 'commercial', or None."""
    text = text.lower().strip()

    # ── NORMALIZE TEXT ────────────────────────────────
    text = (
        text.replace(".", " ")
        .replace(",", " ")
        .replace("।", " ")
        .replace("?", " ")
    )

    # ── KEYWORDS ─────────────────────────────────────

    independent_kw = [
        # English
        "independent", "house", "home", "villa", "bungalow", "plot",

        # Hindi
        "ghar", "मकान", "घर", "kothi", "खुद का घर",

        # Odia
        "ଘର", "ସ୍ୱତନ୍ତ୍ର", "ନିଜ ଘର", "ଭିଲା"
    ]

    apartment_kw = [
        # English
        "apartment", "flat", "flats", "building", "society",

        # Hindi
        "अपार्टमेंट", "फ्लैट",

        # Odia
        "ଆପାର୍ଟମେଣ୍ଟ", "ଫ୍ଲାଟ", "ବିଲ୍ଡିଂ"
    ]

    commercial_kw = [
        # English
        "commercial", "shop", "office", "factory", "warehouse", "mall", "showroom",

        # Hindi
        "dukan", "दुकान", "ऑफिस",

        # Odia
        "ଦୋକାନ", "ଅଫିସ", "କମର୍ସିଆଲ", "କାରଖାନା"
    ]

    # ── SCORING MATCH (better than first-match) ───────
    scores = {
        "independent": 0,
        "apartment": 0,
        "commercial": 0
    }

    for kw in independent_kw:
        if kw in text:
            scores["independent"] += 1

    for kw in apartment_kw:
        if kw in text:
            scores["apartment"] += 1

    for kw in commercial_kw:
        if kw in text:
            scores["commercial"] += 1

    # ── DECISION BASED ON MAX SCORE ───────────────────
    best = max(scores, key=scores.get)

    if scores[best] > 0:
        return best

    # ── GEMINI FALLBACK ──────────────────────────────
    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"""
User replied to property type question (English/Hindi/Odia): "{text}"

Classify:
INDEPENDENT = own house
APARTMENT = flat/apartment
COMMERCIAL = shop/office/business

Reply ONLY: INDEPENDENT / APARTMENT / COMMERCIAL / UNCLEAR
""",
                generation_config=genai.GenerationConfig(
                    max_output_tokens=5,
                    temperature=0
                )
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
    text_lower = text.lower().strip()

    # ── NORMALIZE NUMBERS ─────────────────────────────
    text_clean = re.sub(r'(\d),(\d)', r'\1\2', text_lower)

    # Handle "4k", "5k" etc.
    text_clean = re.sub(r'(\d+)\s*k', lambda m: str(int(m.group(1)) * 1000), text_clean)

    # Extract numeric values
    nums = re.findall(r'\d+', text_clean)

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

    # ── KEYWORD MATCHING ─────────────────────────────

    # HIGH (5000+)
    high_kw = [
        # English
        "high", "above 5000", "more than 5000",

        # Hindi
        "paanch hazar", "पाँच हज़ार", "पाँच हजार",
        "zyada", "ज़्यादा", "adhik", "अधिक",

        # Odia
        "ପାଞ୍ଚ ହଜାର", "ଅଧିକ", "ବେଶି"
    ]

    # MID (2000–5000)
    mid_kw = [
        # English
        "2000", "3000", "4000", "around 3", "around 4",

        # Hindi
        "do hazar", "teen hazar", "char hazar",
        "दो हज़ार", "तीन हज़ार", "चार हज़ार",

        # Odia
        "ଦୁଇ ହଜାର", "ତିନି ହଜାର", "ଚାରି ହଜାର"
    ]

    # LOW (1000–2000)
    low_kw = [
        # English
        "1000", "low", "less",

        # Hindi
        "ek hazar", "एक हज़ार", "kam", "कम", "thoda", "थोड़ा",

        # Odia
        "ଏକ ହଜାର", "କମ", "କମ୍", "ଅଳ୍ପ"
    ]

    # ── MATCHING ─────────────────────────────────────
    for kw in high_kw:
        if kw in text_lower:
            return "high"

    for kw in mid_kw:
        if kw in text_lower:
            return "mid"

    for kw in low_kw:
        if kw in text_lower:
            return "low"

    # ── GEMINI FALLBACK (MULTI-LANGUAGE) ─────────────
    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"""
User answered electricity bill in English/Hindi/Odia: "{text}"

Classify into:
LOW = ₹1000–2000
MID = ₹2000–5000
HIGH = ₹5000+

Reply ONLY: LOW / MID / HIGH / UNCLEAR
""",
                generation_config=genai.GenerationConfig(
                    max_output_tokens=5,
                    temperature=0
                )
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
    text_low = text.lower().strip()

    # ── NORMALIZE ────────────────────────────────────
    text_low = (
        text_low.replace(".", " ")
        .replace(",", " ")
        .replace("।", " ")
        .replace("?", " ")
    )

    # ── KEYWORDS ─────────────────────────────────────

    # Immediate (within 1 month)
    immediate_kw = [
        # English
        "1 month", "one month", "within 1 month", "immediately", "urgent", "asap",

        # Hindi
        "1 mahine", "ek mahine", "jaldi", "turant", "abhi", "एक महीने", "तुरंत", "अभी",

        # Odia
        "ଏକ ମାସ", "ତୁରନ୍ତ", "ସତ୍ତ୍ୱର", "ଏବେ", "ଶୀଘ୍ର"
    ]

    # Medium (1–3 months)
    medium_kw = [
        # English
        "2 month", "3 month", "2-3", "1-3 months", "few months",

        # Hindi
        "do mahine", "teen mahine", "2 se 3", "1 se 3",
        "दो महीने", "तीन महीने", "दो-तीन",

        # Odia
        "ଦୁଇ ମାସ", "ତିନି ମାସ", "1-3 ମାସ", "କିଛି ମାସ"
    ]

    # Enquiry / later / planning
    enquiry_kw = [
        # English
        "enquiry", "planning", "future", "later", "not now", "just checking",

        # Hindi
        "soch", "baad mein", "dekhenge", "sirf", "पूछताछ", "बाद में",

        # Odia
        "ପରେ", "ଭବିଷ୍ୟତ", "ଚିନ୍ତା", "ଦେଖିବା", "ଏବେ ନୁହେଁ", "କେବଳ ପଚାରୁଛି"
    ]

    # ── SCORING SYSTEM ───────────────────────────────
    scores = {
        "1month": 0,
        "1to3months": 0,
        "enquiry": 0
    }

    # keyword scoring
    for kw in immediate_kw:
        if kw in text_low:
            scores["1month"] += 1

    for kw in medium_kw:
        if kw in text_low:
            scores["1to3months"] += 1

    for kw in enquiry_kw:
        if kw in text_low:
            scores["enquiry"] += 1

    # ── NUMERIC HANDLING ─────────────────────────────
    # safer: only interpret numbers if "month" or "ମାସ" context exists
    if "month" in text_low or "mahine" in text_low or "ମାସ" in text_low:
        nums = re.findall(r'\d+', text_low)
        if nums:
            num = int(nums[0])
            if num <= 1:
                scores["1month"] += 2
            elif num <= 3:
                scores["1to3months"] += 2

    # ── FINAL DECISION ───────────────────────────────
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best

    # ── GEMINI FALLBACK ──────────────────────────────
    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"""
User answered solar installation timeline (English/Hindi/Odia): "{text}"

Classify:
1MONTH = within 1 month
1TO3MONTHS = within 1–3 months
ENQUIRY = just enquiry / later / not now

Reply ONLY: 1MONTH / 1TO3MONTHS / ENQUIRY / UNCLEAR
""",
                generation_config=genai.GenerationConfig(
                    max_output_tokens=5,
                    temperature=0
                )
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
    text_low = text.lower().strip()

    # ── NORMALIZE ────────────────────────────────────
    text_low = (
        text_low.replace(".", " ")
        .replace(",", " ")
        .replace("।", " ")
        .replace("?", " ")
    )

    # ── KEYWORDS ─────────────────────────────────────

    # FULL PAYMENT
    full_kw = [
        # English
        "full", "full payment", "cash", "one time", "outright",

        # Hindi
        "ek baar", "ekbari", "puri", "नकद", "एकसाथ", "पूरी", "फुल",

        # Odia
        "ପୁରା", "ଏକଥରେ", "ନକଦ", "ସମ୍ପୂର୍ଣ୍ଣ"
    ]

    # LOAN / EMI
    loan_kw = [
        # English
        "loan", "emi", "bank", "installment", "finance",

        # Hindi
        "किस्त", "लोन", "बैंक", "ईएमआई", "क़िस्त",

        # Odia
        "ଲୋନ୍", "ଇଏମଆଇ", "ବ୍ୟାଙ୍କ", "କିଷ୍ତି"
    ]

    # ── SCORING SYSTEM ───────────────────────────────
    scores = {
        "full": 0,
        "loan": 0
    }

    for kw in full_kw:
        if kw in text_low:
            scores["full"] += 1

    for kw in loan_kw:
        if kw in text_low:
            scores["loan"] += 1

    # ── DECISION ─────────────────────────────────────
    if scores["full"] > scores["loan"]:
        return "full"
    if scores["loan"] > scores["full"]:
        return "loan"

    # ── GEMINI FALLBACK ──────────────────────────────
    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"""
User answered payment preference (English/Hindi/Odia): "{text}"

Classify:
FULL = full payment / cash
LOAN = bank loan / EMI

Reply ONLY: FULL / LOAN / UNCLEAR
""",
                generation_config=genai.GenerationConfig(
                    max_output_tokens=5,
                    temperature=0
                )
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

def handle_user_input(session, user_text):
    """
    Wrapper for local testing (voice pipeline).
    Converts session dict → session_id system.
    """

    from db import db  # required for create_call

    # ── SESSION ID ───────────────────────────────
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())

    session_id = session["session_id"]

    # ── INITIALIZE SESSION (ONLY ONCE) ───────────
    is_new_session = False

    if session_id not in sessions:
        sessions[session_id] = {
            "state": "STATE_1",
            "retries": 0,
            "data": {},
            "turn": 0,
            "no_speech": 0
        }

        # ✅ FIX: create DB call entry (prevents FK error)
        db.create_call(session_id, mobile_number="test")

        is_new_session = True

    # ── CALL LOGIC ───────────────────────────────
    if is_new_session or sessions[session_id]["turn"] == 0:
        bot_reply = ask_instant_ai(session_id, is_start=True)
        sessions[session_id]["turn"] = 1
    else:
        bot_reply = ask_instant_ai(session_id, user_text=user_text)

    # ── AUDIO HANDLING ───────────────────────────
    if bot_reply in PRE_RECORDED_AUDIO:
        audio_path = PRE_RECORDED_AUDIO[bot_reply]
    else:
        audio_path = f"static/reply_{session_id}.wav"
        text_to_speech_or(bot_reply, audio_path)

    return {
        "text": bot_reply,
        "audio_path": audio_path
    }


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

def text_to_speech_or(text, output_path):
    try:
        response = sarvam_client.text_to_speech.convert(
            text=text,
            target_language_code="od-IN",
            speaker="ritu",
            pace=1.2,
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
        tts = gTTS(text=text, lang="or")
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
        text_to_speech_or(bot_reply, audio_file)
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
        user_text = r.recognize_google(audio_data, language="or-IN")
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
            text_to_speech_or(NO_SPEECH_END, bot_audio_path)
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
        text_to_speech_or(bot_reply, bot_audio_path)
        audio_url = f"/{bot_audio_path}"

    return jsonify({
        "text": user_text,
        "answer": bot_reply,
        "audio_url": audio_url,
        "tokens": gemini_tokens
    })

if __name__ == "__main__":
    app.run(debug=True, port=8080)
