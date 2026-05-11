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
    "నమస్కారం, నేను ఉన్నతి ల్యాండ్ అండ్ Infra నుండి దీప్తి మాట్లాడుతున్నాను. "
    "హైదరాబాద్ రింగ్ రోడ్డు కి వంద కిలోమీటర్ల దూరంలో మా సత్వ ఆర్గానిక్ Farms ప్రాజెక్ట్ Early launch offer లో గజం భూమి కేవలం వేయి రూపాయలకే అందుబాటులో ఉంది. "
    "మీ భూమిలో మా కంపెనీ కమర్షియల్ sandalwood farming చేసి సంవత్సరానికి రెండు లక్షల వరకు మరియు పదిహేను సంవత్సరాల్లో నాలుగు కోట్లు వరకు ఆదాయం పొందవచ్చు. "
    "మీరు వివరాలు తెలుసుకోవాలనుకుంటున్నారా?"
)

STATE_1_NO_END = (
    "పర్లేదు, మీకు తరువాత ఆసక్తి ఉంటే ఈ నంబర్‌కు కాల్ చేయండి. "
    "ధన్యవాదాలు!"
)

STATE_2_INVESTMENT_REASON = (
    "మీరు ఈ land ను ఎందుకు consider చేస్తున్నారు? "
    "investment కోసమా లేక farmhouse కోసమా?"
)

STATE_3_PROPERTY = (
    "సుమారుగా ఎంత భూమి కావాలి అనుకుంటున్నారు? "
    "పావు ఎకరం, అర ఎకరం లేదా ఒక ఎకరం?"
)

STATE_4_PAYMENT = (
    "మీరు పూర్తి payment ఎలా చేయాలని అనుకుంటున్నారు? "
    "Full Payment లేదా EMI?"
)

STATE_5_TIMELINE = (
    "మీరు investment ఎప్పటిలో చేయాలని అనుకుంటున్నారు? "
    "ఒక నెలలోపలనా, మూడు నెలల మధ్యనా, లేదా ప్రస్తుతం కేవలం సమాచారం కోసమా?"
)

STATE_6_SITE_VISIT = (
    "ప్రతి సండే ఉచిత సైట్ విజిట్ ఉంటుంది, free pickup facility కూడా ఉంటుంది. "
    "మీకు ఈ సండే సైట్ విజిట్ Arrange చేయాలా లేదా మీకు సౌకర్యమైన తేదీ మరియు సమయం చెప్పండి."
)

STATE_7_CLOSING = (
    "ధన్యవాదాలు! మీ వివరాలు విజయవంతంగా నమోదు అయ్యాయి. "
    "మా టీమ్ త్వరలోనే మీకు కాల్ చేసి site visit ను confirm చేస్తారు. "
    "Site visit లో అన్ని వివరాలను స్పష్టంగా వివరించబడతాయి. "
    "ఉన్నతి ల్యాండ్ అండ్ Infra ను ఎంచుకున్నందుకు ధన్యవాదాలు!"
)

STATE_DISCONNECT = (
    " కాల్ ముగిసింది."
)

# ── Retry / Error Messages ────────────────────────────────────────────────────
MAX_RETRIES = 3
MAX_NO_SPEECH = 3

RETRY_PREFIX = "నేను సరిగ్గా అర్థం చేసుకోలేకపోయాను. "

END_MISUNDERSTAND = "దయచేసి తరువాత మళ్లీ కాల్ చేయండి. ధన్యవాదాలు."

NO_SPEECH_END = "మీ స్వరం వినిపించడం లేదు. దయచేసి తరువాత కాల్ చేయండి."

RETRY_QUESTIONS = {
    "STATE_1": "మీకు వివరాలు తెలుసుకోవాలనుకుంటున్నారా?",
    "STATE_2": "మీరు investment కోసమా లేదా farmhouse కోసమా చూస్తున్నారు?",
    "STATE_3": "పావు ఎకరం, అర ఎకరం లేదా ఒక ఎకరం — ఎంత కావాలి?",
    "STATE_4": "మీరు payment ఎలా చేయాలని అనుకుంటున్నారు?",
    "STATE_5": "మీరు investment ఎప్పుడు చేయాలని అనుకుంటున్నారు?",
    "STATE_6": "మీకు ఈ సండే site visit కావాలా?"
}


# ── Pre-recorded audio mapping ────────────────────────────────────────────────
PRE_RECORDED_AUDIO = {
    STATE_1_GREETING: "static/pre_audio/STATE_1_GREETING.wav",
    STATE_1_NO_END: "static/pre_audio/STATE_1_NO_END.wav",

    STATE_2_INVESTMENT_REASON: "static/pre_audio/STATE_2_INVESTMENT_REASON.wav",
    STATE_3_PROPERTY: "static/pre_audio/STATE_3_PROPERTY.wav",
    STATE_4_PAYMENT: "static/pre_audio/STATE_4_PAYMENT.wav",
    STATE_5_TIMELINE: "static/pre_audio/STATE_5_TIMELINE.wav",
    STATE_6_SITE_VISIT: "static/pre_audio/STATE_6_SITE_VISIT.wav",
    STATE_7_CLOSING: "static/pre_audio/STATE_7_CLOSING.wav",

    STATE_DISCONNECT: "static/pre_audio/STATE_DISCONNECT.wav",

    # Retry / Error pre-recordings
    END_MISUNDERSTAND: "static/pre_audio/END_MISUNDERSTAND.wav",
    NO_SPEECH_END:     "static/pre_audio/NO_SPEECH_END.wav",
    RETRY_PREFIX + "దయచేసి మళ్లీ చెప్పండి.": "static/pre_audio/NO_SPEECH_RETRY.wav",
}

# Auto-add retry questions to pre-recorded mapping
for state_key, q_text in RETRY_QUESTIONS.items():
    full_retry_text = RETRY_PREFIX + q_text
    PRE_RECORDED_AUDIO[full_retry_text] = f"static/pre_audio/{state_key}_RETRY.wav"

# ─────────────────────────────────────────────────────────────────────────────
# Intent helpers
# ─────────────────────────────────────────────────────────────────────────────


def _translate_to_english(text: str) -> str:
    if not text or not text.strip():
        return text

    # ── 1. Sarvam AI translate (auto-detect source language) ─────────────────
    try:
        resp = requests.post(
            "https://api.sarvam.ai/translate",
            json={
                "input": text,
                "source_language_code": "auto",
                "target_language_code": "en-IN",
                "speaker_gender": "Female",
                "mode": "formal",
                "model": "mayura:v1",
                "enable_preprocessing": False,
            },
            headers={
                "api-subscription-key": "sk_1egy7shz_foVYeKo9OrfrtR454ZagxTyw",
                "Content-Type": "application/json",
            },
            timeout=8,
        )
        if resp.ok:
            translated = resp.json().get("translated_text", "").strip()
            if translated:
                print(f"[Sarvam Translate] '{text}' → '{translated}'")
                return translated
        print(f"[Sarvam Translate] Non-OK {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"[Sarvam Translate] Error: {e}")

    # ── 2. Google Translate free fallback (auto-detect as well) ──────────────
    try:
        gt_resp = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text},
            timeout=8,
        )
        if gt_resp.ok:
            data = gt_resp.json()
            translated = "".join(part[0] for part in data[0] if part[0]).strip()
            if translated:
                print(f"[Google Translate Fallback] '{text}' → '{translated}'")
                return translated
    except Exception as e:
        print(f"[Google Translate Fallback] Error: {e}")

    print(f"[Translation] Both providers failed — storing raw: '{text[:50]}'")
    return text

def _log_exchange(session_id, state, answer):
    turn = sessions[session_id]["turn"] + 1
    sessions[session_id]["turn"] = turn

    question_text = _STATE_QUESTION_MAP_EN.get(state, state)

    db.add_exchange(session_id, question_text, _translate_to_english(answer), state, turn)

def check_status_eng():
    try:
        test_inputs = [
            "ନମସ୍କାର",   # Odia
            "नमस्ते",     # Hindi
            "నమస్కారం",  # Telugu
            "ನಮಸ್ಕಾರ"    # Kannada
        ]

        results = []

        for text in test_inputs:
            output = _translate_to_english(text)
            results.append(bool(output and isinstance(output, str)))

        return {
            "translation_pipeline_working": all(results),
            "sarvam_key_present": (os.getenv("SARVAM_API_KEY")),
            "gemini_key_present": (os.getenv("GEMINI_API_KEY")),
            "elevenlabs_key_present": (os.getenv("ELEVENLABS_API_KEY")),
        }

    except Exception as e:
        return {
            "translation_pipeline_working": False,
            "error": str(e)
        }



def _finish_call(session_id, status="completed"):
    lead = sessions[session_id].get("data", {})
    db.complete_call(session_id, lead_data=lead, status=status)



def is_positive(text):
    text = text.lower().strip()

    # ── POSITIVE KEYWORDS ─────────────────────────────
    positives_exact = {
        # English
        "yes", "ok", "okay", "sure", "yeah", "yup", "yep", "fine", "alright",
        "go ahead", "tell me", "please tell", "continue", "proceed", "do it",

        # Hindi
        "haa", "ha", "haan", "ji", "haanji", "theek", "ठीक", "ठीक है",
        "हाँ", "हां", "जी", "बिल्कुल", "ज़रूर", "जरूर",
        "बताओ", "बताइए", "कहिए", "समझाइए", "करो", "कीजिए",

        # Odia
        "ହଁ", "ହାଁ", "ଠିକ୍", "ଠିକ", "ହଁ ଠିକ୍", "ଚାହୁଁଛି",
        "କୁହ", "କୁହନ୍ତୁ", "କହ", "ବୁଝା", "କର", "କରନ୍ତୁ",

        # Telugu
        "అవును", "అవునండి", "సరే", "ఓకే", "ఓకే అండి",
        "కావాలి", "చెప్పండి", "చెప్పు", "వివరించండి",
        "చెప్పండి అండి", "మాట్లాడండి", "చెప్పండి ప్లీజ్",
        "అవును చెప్పండి", "సరే చెప్పండి",

        # Hinglish / mixed
        "haan bolo", "haan batao", "ok bolo", "ok batao",
        "bolo", "batao", "samjhao", "samjha do",
        "haan ji bataiye", "haan ji boliye",
        "ok tell me", "yes tell me", "yes please",
    }
    
    # ── NEGATIVE KEYWORDS ─────────────────────────────
    negatives_exact = {
        # English
        "no", "nope",

        # Hindi
        "nahi", "na", "नहीं", "ना",

        # Odia
        "ନା", "ନାହିଁ",

        # Telugu
        "కాదు", "వద్దు", "అవసరం లేదు"
    }

    # ── GREETING / NEUTRAL (treated as soft positive) ─
    positives_exact.update([
        # English
        "hello", "hi",

        # Hindi
        "नमस्ते",

        # Odia
        "ନମସ୍କାର", "ହ୍ୟାଲୋ",

        # Telugu
        "నమస్కారం", "హలో"
    ])

    # ── TOKEN CHECK ───────────────────────────────────
    words = text.split()

    has_positive = any(w in positives_exact for w in words)
    has_negative = any(w in negatives_exact for w in words)

    # ── DECISION LOGIC ────────────────────────────────
    if has_negative and not has_positive:
        return False

    if has_positive:
        return True

    # fallback: assume positive to keep conversation moving
    return True


def _detect_property_type(text):
    """Now used for intent: returns 'investment' or 'farmhouse'."""
    text = text.lower().strip()

    # Normalize Telugu / Hinglish variations
    text = text.replace("ఫామ్", "farm")
    text = text.replace("ల్యాండ్", "land")

    # Investment intent
    if any(x in text for x in [
        "investment", "invest", "investing",
        "పెట్టుబడి", "ఇన్వెస్ట్", "returns"
    ]):
        return "investment"

    # Farmhouse intent
    if any(x in text for x in [
        "farmhouse", "farm", "land", "agriculture",
        "ఫామ్", "వ్యవసాయం", "ల్యాండ్"
    ]):
        return "farmhouse"

    # Fallback → return None to trigger retry
    return None

def _detect_bill_range(text):
    """Now used for budget: returns 'low', 'mid', 'high'."""
    text = text.lower().strip()

    # Normalize Telugu / Hinglish
    text = text.replace("లాక్స్", "lakh")
    text = text.replace("లక్షలు", "lakh")
    text = text.replace("లక్ష", "lakh")
    text = text.replace("lakhs", "lakh")

    # Strong numeric detection
    if "40" in text or "40 lakh" in text or "forty" in text:
        return "high"

    if "20" in text or "20 lakh" in text or "twenty" in text:
        return "mid"

    if "10" in text or "10 lakh" in text or "ten" in text:
        return "low"

    # Telugu words (extra safety)
    if any(x in text for x in ["నలభై"]):
        return "high"

    if any(x in text for x in ["ఇరవై"]):
        return "mid"

    if any(x in text for x in ["పది"]):
        return "low"

    # 🔁 AI fallback (only if needed)
    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f'User said: "{text}". Classify budget as LOW (10L), MID (20L), HIGH (40L). Reply one word.',
                generation_config=genai.GenerationConfig(max_output_tokens=3, temperature=0)
            )
            ans = resp.text.strip().lower()

            if "low" in ans:
                return "low"
            if "mid" in ans:
                return "mid"
            if "high" in ans:
                return "high"
        except:
            pass

    return None

def _detect_timeline(text):
    """Returns '1month', '1to3months', 'enquiry', or None."""
    text_low = text.lower().strip()

    # Normalize Telugu/Hinglish → English so keyword matching works
    text_low = (
        text_low
        .replace("మంత్", "month")
        .replace("మంథ్", "month")
        .replace("నెల", "month")
        .replace("నెలలు", "month")
        .replace("వన్", "one")
        .replace("ఒన్", "one")
        .replace("ట్వో", "two")
        .replace("త్రీ", "three")
        .replace("ఒక", "one")
        .replace("రెండు", "two")
        .replace("మూడు", "three")
        .replace(".", " ")
        .replace(",", " ")
        .replace("।", " ")
        .replace("?", " ")
    )

    immediate_kw = [
        "1 month", "one month", "within 1 month", "immediately", "urgent", "asap",
        "1 mahine", "ek mahine", "jaldi", "turant", "abhi",
        "ఒక నెల", "తక్షణం", "ఇప్పుడే", "త్వరగా",
    ]

    medium_kw = [
        "2 month", "3 month", "two month", "three month",
        "2-3", "1-3", "few month",
        "do mahine", "teen mahine",
        "రెండు నెలలు", "మూడు నెలలు",
    ]

    enquiry_kw = [
        "enquiry", "planning", "future", "later", "not now", "just checking",
        "soch", "baad mein", "dekhenge", "sirf",
        "తర్వాత", "భవిష్యత్", "చూద్దాం", "ఇప్పుడే కాదు",
    ]

    scores = {"1month": 0, "1to3months": 0, "enquiry": 0}

    for kw in immediate_kw:
        if kw in text_low:
            scores["1month"] += 1

    for kw in medium_kw:
        if kw in text_low:
            scores["1to3months"] += 1

    for kw in enquiry_kw:
        if kw in text_low:
            scores["enquiry"] += 1

    # Numeric range e.g. "2-3 months"
    range_match = re.findall(r'(\d+)\s*[-to]+\s*(\d+)', text_low)
    if range_match:
        nums = [int(n) for pair in range_match for n in pair]
        avg = sum(nums) // len(nums)
        if avg <= 1:
            scores["1month"] += 2
        elif avg <= 3:
            scores["1to3months"] += 2

    # Single digit with month context
    if any(x in text_low for x in ["month", "mahine", "నెల"]):
        nums = re.findall(r'\d+', text_low)
        if nums:
            num = int(nums[0])
            if num <= 1:
                scores["1month"] += 2
            elif num <= 3:
                scores["1to3months"] += 2

    # Word number with month context (after normalization above)
    if "month" in text_low:
        if "one" in text_low:
            scores["1month"] += 2
        if "two" in text_low or "three" in text_low:
            scores["1to3months"] += 2

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best

    # Gemini fallback
    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"""
User answered investment timeline (English/Hindi/Telugu): "{text}"

Classify:
1MONTH = within 1 month
1TO3MONTHS = within 1–3 months
ENQUIRY = just enquiry / later / not now

Reply ONLY: 1MONTH / 1TO3MONTHS / ENQUIRY / UNCLEAR
""",
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
        "ପୁରା", "ଏକଥରେ", "ନକଦ", "ସମ୍ପୂର୍ଣ୍ଣ",

        # Telugu
        "పూర్తి", "ఒకేసారి", "నగదు", "ఫుల్", "క్యాష్"
    ]

    # LOAN / EMI
    loan_kw = [
        # English
        "loan", "emi", "bank", "installment", "finance",

        # Hindi
        "किस्त", "लोन", "बैंक", "ईएमआई", "क़िस्त",

        # Odia
        "ଲୋନ୍", "ଇଏମଆଇ", "ବ୍ୟାଙ୍କ", "କିଷ୍ତି",

        # Telugu
        "లోన్", "ఈఎంఐ", "బ్యాంక్", "కిస్తీ", "ఫైనాన్స్"
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

    # ── STRONG SIGNAL OVERRIDE ───────────────────────
    # if clear loan words exist → prioritize loan
    if any(k in text_low for k in ["emi", "loan", "ఈఎంఐ", "లోన్"]):
        return "loan"

    # if clear full payment words exist → prioritize full
    if any(k in text_low for k in ["cash", "పూర్తి", "నగదు"]):
        return "full"

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
User answered payment preference (English/Hindi/Odia/Telugu): "{text}"

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

    from db import db

    # ── SESSION ID ───────────────────────────────
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())

    session_id = session["session_id"]

    # ── INIT SESSION ─────────────────────────────
    is_new_session = False

    if session_id not in sessions:
        sessions[session_id] = {
            "state": "STATE_1",
            "retries": 0,
            "data": {},
            "turn": 0,
            "no_speech": 0
        }

        db.create_call(session_id, mobile_number="test")
        is_new_session = True

    # 🚨 HARD STOP — PREVENT REPEATED "THANK YOU"
    if sessions[session_id]["state"] == "ENDED":
        print(f"[INFO] Ignoring input — session already ended ({session_id})")

        return {
            "text": "",
            "audio_path": "",
            "end": True
        }

    # ── MAIN BOT LOGIC ───────────────────────────
    if is_new_session or sessions[session_id]["turn"] == 0:
        bot_reply = ask_instant_ai(session_id, is_start=True)
        sessions[session_id]["turn"] = 1
    else:
        bot_reply = ask_instant_ai(session_id, user_text=user_text)

    # ── AUDIO HANDLING ───────────────────────────
    if isinstance(bot_reply, list):
        audio_paths = []

        for reply in bot_reply:
            if reply in PRE_RECORDED_AUDIO:
                audio_paths.append(PRE_RECORDED_AUDIO[reply])
            else:
                audio_file = f"static/reply_{session_id}_{len(audio_paths)}.wav"
                text_to_speech_te(reply, audio_file)
                audio_paths.append(audio_file)

        return {
            "text": bot_reply,
            "audio_paths": audio_paths,
            "end": sessions[session_id]["state"] == "ENDED"
        }
    else:
        audio_path = f"static/reply_{session_id}.wav"
        text_to_speech_te(bot_reply, audio_path)

    return {
        "text": bot_reply,
        "audio_path": audio_path,
        "end": sessions[session_id]["state"] == "ENDED"
    }


def handle_state_1(session_id, user_text_low, user_text_safe):

    if is_positive(user_text_low):
        _log_exchange(session_id, "STATE_1", user_text_safe)

        sessions[session_id]["retries"] = 0
        sessions[session_id]["state"] = "STATE_2"

        return STATE_2_INVESTMENT_REASON

    else:
        _log_exchange(session_id, "STATE_1", user_text_safe)

        sessions[session_id]["state"] = "ENDED"
        _finish_call(session_id, "not_interested")

        return STATE_1_NO_END


def handle_state_2(session_id, user_text_low, user_text_safe):

    intent = _detect_property_type(user_text_low)

    # 🔥 SOFT FALLBACK (IMPORTANT)
    if intent is None:
        # assume investment to move forward
        intent = "investment"

    _log_exchange(session_id, "STATE_2", user_text_safe)

    sessions[session_id]["data"]["purpose"] = intent
    sessions[session_id]["retries"] = 0
    sessions[session_id]["state"] = "STATE_3"

    return STATE_3_PROPERTY

def handle_state_3(session_id, user_text_low, user_text_safe):

    # Normalize Telugu transliterations that te-IN STT produces for English words
    normalized = (
        user_text_low
        .replace("క్వార్టర్", "quarter")
        .replace("హాఫ్", "half")
        .replace("ఒన్", "one")
        .replace("వన్", "one")
        .replace("పావు", "quarter")
        .replace("అర", "half")
        .replace("ఒక", "one")
        .replace("ఎకరం", "acre")
        .replace("ఎకర్", "acre")
        .replace("ఎకరాలు", "acre")
    )

    land_keywords = [
        "quarter", "half", "one", "acre", "acres",
        "1", "2", "పావు", "అర", "ఒక", "ఎకరం", "ఎకర్",
    ]

    if not any(x in normalized for x in land_keywords):
        return _retry_or_end(session_id, "STATE_3")

    _log_exchange(session_id, "STATE_3", user_text_safe)
    sessions[session_id]["data"]["land_size"] = user_text_safe
    sessions[session_id]["retries"] = 0
    sessions[session_id]["state"] = "STATE_4"
    return STATE_4_PAYMENT

def handle_state_4(session_id, user_text_low, user_text_safe):

    payment = _detect_payment(user_text_low)

    if payment is None:
        return _retry_or_end(session_id, "STATE_4")

    _log_exchange(session_id, "STATE_4", user_text_safe)

    sessions[session_id]["data"]["payment"] = payment
    sessions[session_id]["retries"] = 0
    sessions[session_id]["state"] = "STATE_5"

    return STATE_5_TIMELINE

def handle_state_5(session_id, user_text_low, user_text_safe):

    timeline = _detect_timeline(user_text_low)

    if timeline is None:
        return _retry_or_end(session_id, "STATE_5")

    _log_exchange(session_id, "STATE_5", user_text_safe)

    sessions[session_id]["data"]["timeline"] = timeline
    sessions[session_id]["retries"] = 0

    # ✅ EARLY EXIT (consistent with your design)
    if timeline == "enquiry":
        _finish_call(session_id, "completed")
        sessions[session_id]["state"] = "ENDED"
        return [STATE_7_CLOSING, STATE_DISCONNECT]

    sessions[session_id]["state"] = "STATE_6"

    return STATE_6_SITE_VISIT

def handle_state_6(session_id, user_text_low, user_text_safe):

    if is_positive(user_text_low):
        visit = "yes"

    elif any(x in user_text_low for x in ["సండే", "sunday", "date", "తేదీ"]):
        visit = "scheduled"

    elif any(x in user_text_low for x in ["no", "later", "వద్దు"]):
        visit = "no"

    else:
        visit = "unclear"

    _log_exchange(session_id, "STATE_6", user_text_safe)

    sessions[session_id]["data"]["site_visit_interest"] = visit
    sessions[session_id]["retries"] = 0

    # ✅ move to STATE_7 (internal)
    sessions[session_id]["state"] = "STATE_7"

    return STATE_7_CLOSING

def handle_state_7(session_id, user_text_low, user_text_safe):
    """
    This state ignores user input.
    Immediately transitions to disconnect.
    """

    # ✅ DO NOT log user input (we are ignoring it)

    # move to disconnect
    sessions[session_id]["state"] = "DISCONNECT"

    return STATE_DISCONNECT

def handle_disconnect(session_id, user_text_low, user_text_safe):

    _finish_call(session_id, "completed")

    sessions[session_id]["state"] = "ENDED"

    return ""

STATE_HANDLERS = {
    "STATE_1": handle_state_1,
    "STATE_2": handle_state_2,
    "STATE_3": handle_state_3,
    "STATE_4": handle_state_4,
    "STATE_5": handle_state_5,
    "STATE_6": handle_state_6,
    "STATE_7": handle_state_7,
    "DISCONNECT": handle_disconnect,
}


# ─────────────────────────────────────────────────────────────────────────────
# Main state machine
# ─────────────────────────────────────────────────────────────────────────────

# Maps each state to the question text it asked the user
_STATE_QUESTION_MAP = {
    "STATE_1": STATE_1_GREETING,
    "STATE_2": STATE_2_INVESTMENT_REASON,
    "STATE_3": STATE_3_PROPERTY,
    "STATE_4": STATE_4_PAYMENT,
    "STATE_5": STATE_5_TIMELINE,
    "STATE_6": STATE_6_SITE_VISIT,
    "STATE_7": STATE_7_CLOSING,
}

_STATE_QUESTION_MAP_EN = {
    "STATE_1": (
        "Hello! I am Dipti calling from Unnati Land & Infra. "
        "We have a Sattva Organic Farm project located around 90 kilometers from Hyderabad ORR, "
        "available at an early launch offer of just ₹999 per square yard. "
        "With managed sandalwood farming, there is a potential to earn up to ₹2 lakhs per year "
        "and up to ₹4 crores over 15 years. "
        "Would you like to know more details about this?"
    ),

    "STATE_2": (
        "Great! May I know what purpose you are considering this land for? "
        "Is it for investment or for farmhouse use?"
    ),

    "STATE_3": (
        "Approximately how much land are you looking for? "
        "Quarter acre, half acre, or one acre?"
    ),

    "STATE_4": (
        "How would you prefer to make the payment? "
        "Full payment or EMI option?"
    ),

    "STATE_5": (
        "When are you planning to make this investment? "
        "Within 1 month, within 1 to 3 months, or just exploring for now?"
    ),

    "STATE_6": (
        "We offer a free site visit every Sunday with pickup facility available. "
        "Would you like us to arrange a visit this Sunday, or would you prefer another date and time?"
    ),

    "STATE_7": (
        "Thank you! Your details have been successfully recorded. "
        "Our team will contact you shortly to confirm your site visit. "
        "All details will be clearly explained during the visit. "
        "Thank you for choosing Unnati Land & Infra. Have a great day!"
    ),
}


def ask_instant_ai(session_id, user_text=None, is_start=False):

    if session_id not in sessions:
        sessions[session_id] = {
            "state": "STATE_1",
            "retries": 0,
            "data": {},
            "turn": 0,
            "no_speech": 0
        }

    if is_start:
        return STATE_1_GREETING

    user_text_safe = str(user_text).strip()
    user_text_low = user_text_safe.lower()

    state = sessions[session_id]["state"]

    # 🚨 safety
    if state == "ENDED":
        return ""

    handler = STATE_HANDLERS.get(state)

    if not handler:
        return STATE_1_GREETING

    # ── STEP 1: NORMAL HANDLER ───────────────────────
    response = handler(session_id, user_text_low, user_text_safe)

    # ── STEP 2: AUTO CHAIN STATE_7 ───────────────────
    if sessions[session_id]["state"] == "STATE_7":
        # move to disconnect
        sessions[session_id]["state"] = "DISCONNECT"

        # ⚠️ we return ONLY closing here
        return response

    # ── STEP 3: AUTO CHAIN DISCONNECT ────────────────
    if sessions[session_id]["state"] == "DISCONNECT":
        _finish_call(session_id, "completed")
        sessions[session_id]["state"] = "ENDED"

        return STATE_DISCONNECT

    return response



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

def text_to_speech_te(text, output_path):
    try:
        response = sarvam_client.text_to_speech.convert(
            text=text,
            target_language_code="te-IN",
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
        tts = gTTS(text=text, lang="te")
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
        text_to_speech_te(bot_reply, audio_file)
        audio_url = f"/{audio_file}"

    return jsonify({
        "session_id": session_id,
        "text": bot_reply,
        "audio_url": [audio_url],
        "tokens": gemini_tokens
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    session_id = request.form.get("session_id")
    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid or expired session. Please start a new call."}), 400
    
    if sessions[session_id]["state"] == "ENDED":
        return jsonify({
            "answer": "",
            "audio_url": [],
            "end": True
        })

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
        user_text = r.recognize_google(audio_data, language="te-IN")
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
            text_to_speech_te(NO_SPEECH_END, bot_audio_path)
            return jsonify({
                "text": "[No speech detected]",
                "answer": NO_SPEECH_END,
                "audio_url": f"/{bot_audio_path}",
                "tokens": gemini_tokens
            })

        return jsonify({
            "text": "[No speech detected]",
            "answer": "మీ స్వరం వినిపించడం లేదు. దయచేసి మళ్లీ చెప్పండి.",
            "audio_url": [],
            "tokens": gemini_tokens
        })

    # Reset no-speech counter on successful detection
    sessions[session_id]["no_speech"] = 0

    bot_reply = ask_instant_ai(session_id, user_text=user_text)
    print(f"[Session {session_id}] Bot Reply: {bot_reply[:60]}...")

    if isinstance(bot_reply, list):
        audio_url = []
        for reply in bot_reply:
            if reply in PRE_RECORDED_AUDIO:
                audio_url.append(f"/{PRE_RECORDED_AUDIO[reply]}")
            else:
                audio_file = f"static/reply_{session_id}_{len(audio_url)}.wav"
                text_to_speech_te(reply, audio_file)
                audio_url.append(f"/{audio_file}")

        return jsonify({
            "text": user_text,
            "answer": bot_reply,
            "audio_url": audio_url,
            "tokens": gemini_tokens
        })
    else:
        bot_audio_path = f"static/reply_{session_id}.wav"
        text_to_speech_te(bot_reply, bot_audio_path)
        audio_url = f"/{bot_audio_path}"

    return jsonify({
        "text": user_text,
        "answer": bot_reply,
        "audio_url": [audio_url],
        "tokens": gemini_tokens
    })

if __name__ == "__main__":
    app.run(debug=True, port=8080)
