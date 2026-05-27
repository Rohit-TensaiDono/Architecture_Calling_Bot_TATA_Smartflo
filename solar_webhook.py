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
    api_subscription_key=os.getenv("SARVAM_API_KEY", "sk_1egy7shz_foVYeKo9OrfrtR454ZagxTyw"),
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
# Bot Flow — Unnati Land & Infra Outbound Script
# ─────────────────────────────────────────────────────────────────────────────

# State mapping for sessions
sessions = {}

# ── State Texts ───────────────────────────────────────────────────────────────

STATE_1_GREETING = (
    "నమస్కారం, హైదరాబాద్ ఔటర్ రింగ్ రోడ్ ఎగ్జిట్ ౫ కి జస్ట్ ఒక నిమిషం దూరంలో "
    "ప్రీమియం ఫ్లాట్స్ స్క్వేర్ ఫీట్ కేవలం ౪,౫౦౦ రూపాయలు మాత్రమే. "
    "డిసెంబర్ ౨౦౨౬ కి హ్యాండోవర్. "
    "మీరు వివరాలు తెలుసుకోవాలనుకుంటున్నారా?"
)

STATE_1_NO_END = (
    "పర్లేదు, మీకు తరువాత ఆసక్తి ఉంటే ఈ నంబర్‌కు కాల్ చేయండి. "
    "ధన్యవాదాలు!"
)

STATE_2_INVESTMENT_REASON = (
    "మీరు ప్రస్తుతం హైదరాబాద్‌లో కొత్త ఇల్లు కోసం చూస్తున్నారా "
    "లేక పెట్టుబడి కోసం చూస్తున్నారా?"
)

STATE_3_PROPERTY = (
    "మీరు రెండు బెడ్‌రూమ్ అపార్ట్‌మెంట్ కావాలనుకుంటున్నారా "
    "లేక మూడు బెడ్‌రూమ్ డూప్లెక్స్ విల్లా కావాలనుకుంటున్నారా?"
)

STATE_4_PAYMENT = (
    "మీరు పూర్తి చెల్లింపుతో కొనాలనుకుంటున్నారా "
    "లేక ఈఎంఐ సౌకర్యంతో కొనాలనుకుంటున్నారా?"
)

STATE_5_TIMELINE = (
    "మీరు ఈ పెట్టుబడిని ఎప్పటిలో చేయాలని అనుకుంటున్నారు? "
    "ఒక నెలలోపలా, మూడు నెలలలోపలా, "
    "లేక ప్రస్తుతం కేవలం సమాచారం కోసమా?"
)

STATE_6_SITE_VISIT = (
    "ప్రతి రోజు ఉచిత పికప్ సౌకర్యం అందుబాటుతో సైట్ విజిట్ ఉంటుంది. "
    "మీకు సౌకర్యమైన తేదీ మరియు సమయం చెప్పండి."
)

STATE_7_CLOSING = (
    "ధన్యవాదాలు! మీ వివరాలు విజయవంతంగా నమోదు అయ్యాయి. "
    "మా టీమ్ త్వరలోనే మీకు కాల్ చేసి సైట్ విజిట్‌ను నిర్ధారిస్తుంది. "
    "సైట్ విజిట్‌లో అన్ని వివరాలు స్పష్టంగా తెలియజేయబడతాయి. "
    "ఉన్నతి ల్యాండ్ అండ్ ఇన్‌ఫ్రాను ఎంచుకున్నందుకు ధన్యవాదాలు!"
)


# ── FIX: Dedicated pre-recorded state for price + payment combined response ──
# Previously this was built dynamically as a string inside handle_state_3,
# which meant it never matched any PRE_RECORDED_AUDIO key.
# Now it is a named constant so the lookup always works correctly.
STATE_PRICE_AND_PROPERTY = (
    "మా ప్రాజెక్ట్‌లో స్క్వేర్ ఫీట్ ధర కేవలం ౪,౫౦౦ రూపాయలు మాత్రమే. "
    "మీరు రెండు బెడ్‌రూమ్ అపార్ట్‌మెంట్ కావాలనుకుంటున్నారా "
    "లేక మూడు బెడ్‌రూమ్ డూప్లెక్స్ విల్లా కావాలనుకుంటున్నారా?"
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
    "STATE_1": "మీరు వివరాలు తెలుసుకోవాలనుకుంటున్నారా?",
    "STATE_2": "మీరు కొత్త ఇల్లు కోసమా లేదా పెట్టుబడి కోసమా చూస్తున్నారు?",
    "STATE_3": "రెండు బెడ్‌రూమ్ అపార్ట్‌మెంట్ కావాలా లేక మూడు బెడ్‌రూమ్ విల్లా కావాలా?",
    "STATE_4": "పూర్తి చెల్లింపు చేయాలనుకుంటున్నారా లేక ఈఎంఐ కావాలా?",
    "STATE_5": "మీరు ఈ పెట్టుబడి ఎప్పుడు చేయాలని అనుకుంటున్నారు?",
    "STATE_6": "మీకు సైట్ విజిట్ కు అనుకూలమైన తేదీ చెప్పండి."
}

# ── Pre-recorded audio mapping ────────────────────────────────────────────────
PRE_RECORDED_AUDIO = {
    STATE_1_GREETING:        "static/pre_audio/STATE_1_GREETING.wav",
    STATE_1_NO_END:          "static/pre_audio/STATE_1_NO_END.wav",
    STATE_2_INVESTMENT_REASON: "static/pre_audio/STATE_2_INVESTMENT_REASON.wav",
    STATE_3_PROPERTY:        "static/pre_audio/STATE_3_PROPERTY.wav",
    STATE_4_PAYMENT:         "static/pre_audio/STATE_4_PAYMENT.wav",
    STATE_5_TIMELINE:        "static/pre_audio/STATE_5_TIMELINE.wav",
    STATE_6_SITE_VISIT:      "static/pre_audio/STATE_6_SITE_VISIT.wav",
    STATE_7_CLOSING:         "static/pre_audio/STATE_7_CLOSING.wav",
    STATE_PRICE_AND_PROPERTY: "static/pre_audio/STATE_PRICE_AND_PROPERTY.wav",
    STATE_DISCONNECT:        "static/pre_audio/STATE_DISCONNECT.wav",
    END_MISUNDERSTAND:       "static/pre_audio/END_MISUNDERSTAND.wav",
    NO_SPEECH_END:           "static/pre_audio/NO_SPEECH_END.wav",
    RETRY_PREFIX + "దయచేసి మళ్లీ చెప్పండి.": "static/pre_audio/NO_SPEECH_RETRY.wav",
}

# Auto-add retry questions to pre-recorded mapping
for _state_key, _q_text in RETRY_QUESTIONS.items():
    _full_retry_text = RETRY_PREFIX + _q_text
    PRE_RECORDED_AUDIO[_full_retry_text] = f"static/pre_audio/{_state_key}_RETRY.wav"


# ── Startup: log any missing pre-recorded files so you know immediately ───────
def _check_pre_recorded_files():
    missing = [p for p in PRE_RECORDED_AUDIO.values() if not os.path.exists(p)]
    if missing:
        print(f"[Startup] ⚠️  {len(missing)} pre-recorded audio file(s) MISSING — will fall back to dynamic TTS:")
        for p in missing:
            print(f"           ✗ {p}")
    else:
        print(f"[Startup] ✅ All {len(PRE_RECORDED_AUDIO)} pre-recorded audio files found.")


_check_pre_recorded_files()


# ─────────────────────────────────────────────────────────────────────────────
# Translation helper
# ─────────────────────────────────────────────────────────────────────────────

def _translate_to_english(text: str) -> str:
    if not text or not text.strip():
        return text

    # 1. Sarvam AI translate
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
                "api-subscription-key": os.getenv("SARVAM_API_KEY", "sk_1egy7shz_foVYeKo9OrfrtR454ZagxTyw"),
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

    # 2. Google Translate free fallback
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


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _log_exchange(session_id, state, answer):
    turn = sessions[session_id]["turn"] + 1
    sessions[session_id]["turn"] = turn
    question_text = _STATE_QUESTION_MAP_EN.get(state, state)
    db.add_exchange(session_id, question_text, _translate_to_english(answer), state, turn)


def _finish_call(session_id, status="completed"):
    lead = sessions[session_id].get("data", {})
    db.complete_call(session_id, lead_data=lead, status=status)


def check_status_eng():
    try:
        test_inputs = [" నమస్కారం", "नमस्ते", "ନମସ୍କାର"]
        results = [bool(_translate_to_english(t)) for t in test_inputs]
        return {
            "translation_pipeline_working": all(results),
            "sarvam_key_present": (os.getenv("SARVAM_API_KEY")),
            "gemini_key_present": (os.getenv("GEMINI_API_KEY")),
            "elevenlabs_key_present": (os.getenv("ELEVENLABS_API_KEY")),
        }
    except Exception as e:
        return {"translation_pipeline_working": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Intent helpers
# ─────────────────────────────────────────────────────────────────────────────

def is_positive(text):
    text = text.lower().strip()

    # 1. ── CHECK PHRASES FIRST (Fixes multi-word bugs like "అవసరం లేదు") ──
    negative_phrases = ["అవసరం లేదు", "నాకు వద్దు", "not interested", "don't want"]
    if any(phrase in text for phrase in negative_phrases):
        return False

    # ── POSITIVE KEYWORDS ─────────────────────────────
    positives_exact = {
        "yes", "ok", "okay", "sure", "yeah", "yup", "yep", "fine", "alright",
        "go ahead", "tell me", "please tell", "continue", "proceed", "do it",
        "haa", "ha", "haan", "ji", "haanji", "theek", "ठीक", "ठीक है",
        "हाँ", "हां", "जी", "बिल्कुल", "ज़रूर", "जरूर",
        "बताओ", "बताइए", "कहिए", "समझाइए", "करो", "कीजिए",
        "ହଁ", "ହାଁ", "ଠିକ୍", "ଠିକ", "ହଁ ଠିକ୍", "ଚାହୁଁଛି",
        "କୁହ", "କୁହନ୍ତୁ", "କହ", "ବୁଝା", "କର", "କରନ୍ତୁ",
        "అవును", "అవునండి", "సరే", "ఓకే", "ఓకే అండి",
        "కావాలి", "చెప్పండి", "చెప్పు", "వివరించండి",
        "చెప్పండి అండి", "మాట్లాడండి", "చెప్పండి ప్లీజ్",
        "అవును చెప్పండి", "సరే చెప్పండి",
        "haan bolo", "haan batao", "ok bolo", "ok batao",
        "bolo", "batao", "samjhao", "samjha do",
        "haan ji bataiye", "haan ji boliye",
        "ok tell me", "yes tell me", "yes please",
        "hello", "hi", "నమస్కారం", "హలో", "नमस्ते", "ନମସ୍କାର", "ହ୍ୟାଲୋ",
    }

    # ── NEGATIVE KEYWORDS (Added missing single words like "లేదు") ──────
    negatives_exact = {
        "no", "nope", "not", "nahi", "na", "नहीं", "ना",
        "ନା", "ନାହିଁ", "కాదు", "వద్దు", "లేదు", "అక్కర్లేదు"
    }

    # 2. ── TOKEN CHECK ───────────────────────────────────
    words = text.split()
    has_positive = any(w in positives_exact for w in words)
    has_negative = any(w in negatives_exact for w in words)

    if has_negative and not has_positive:
        return False
    if has_positive:
        return True

    # 3. ── GEMINI FALLBACK (The Safety Net) ─────────────
    global gemini_model
    if gemini_model:
        prompt = f"The user was asked if they want details about a real estate project. They replied: '{text}'. Does this mean YES or NO? Reply with exactly 'yes' or 'no'."
        gemini_decision = _gemini_yes_no(prompt)
        if gemini_decision is not None:
            return gemini_decision

    # 4. ── FINAL FALLBACK ──
    return True

def _detect_property_type(text):
    text = text.lower().strip()
    text = text.replace("ఫామ్", "farm").replace("ల్యాండ్", "land")

    if any(x in text for x in ["investment", "invest", "investing", "పెట్టుబడి", "ఇన్వెస్ట్", "returns"]):
        return "investment"
    if any(x in text for x in ["farmhouse", "farm", "land", "agriculture", "ఫామ్", "వ్యవసాయం", "ల్యాండ్"]):
        return "farmhouse"
    return None


def _detect_timeline(text):
    """Returns '1month', '1to3months', 'enquiry', or None."""
    text_low = text.lower().strip()

    text_low = (
        text_low
        .replace("మంత్", "month").replace("మంథ్", "month")
        .replace("నెల", "month").replace("నెలలు", "month")
        .replace("వన్", "one").replace("ఒన్", "one")
        .replace("ట్వో", "two").replace("త్రీ", "three")
        .replace("ఒక", "one").replace("రెండు", "two").replace("మూడు", "three")
        .replace(".", " ").replace(",", " ").replace("।", " ").replace("?", " ")
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

    range_match = re.findall(r'(\d+)\s*[-to]+\s*(\d+)', text_low)
    if range_match:
        nums = [int(n) for pair in range_match for n in pair]
        avg = sum(nums) // len(nums)
        if avg <= 1:
            scores["1month"] += 2
        elif avg <= 3:
            scores["1to3months"] += 2

    if any(x in text_low for x in ["month", "mahine", "నెల"]):
        nums = re.findall(r'\d+', text_low)
        if nums:
            num = int(nums[0])
            if num <= 1:
                scores["1month"] += 2
            elif num <= 3:
                scores["1to3months"] += 2

    if "month" in text_low:
        if "one" in text_low:
            scores["1month"] += 2
        if "two" in text_low or "three" in text_low:
            scores["1to3months"] += 2

    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best

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
    """Returns 'full', 'emi', or None."""
    text_low = text.lower().strip()
    text_low = (
        text_low.replace(".", " ").replace(",", " ")
        .replace("।", " ").replace("?", " ")
    )

    full_kw = [
        "full", "full payment", "cash", "one time", "outright",
        "ek baar", "ekbari", "puri", "नकद", "एकसाथ", "पूरी", "फुल",
        "ପୁରା", "ଏକଥରେ", "ନକଦ", "ସମ୍ପୂର୍ଣ୍ଣ",
        "పూర్తి", "ఒకేసారి", "నగదు", "ఫుల్", "క్యాష్",
    ]
    loan_kw = [
        "loan", "emi", "bank", "installment", "finance",
        "किस्त", "लोन", "बैंक", "ईएमआई", "क़िस्त",
        "ଲୋନ୍", "ଇଏମଆଇ", "ବ୍ୟାଙ୍କ", "କିଷ୍ତି",
        "లోన్", "ఈఎంఐ", "బ్యాంక్", "కిస్తీ", "ఫైనాన్స్",
    ]

    # Strong signal overrides first
    if any(k in text_low for k in ["emi", "loan", "ఈఎంఐ", "లోన్"]):
        return "emi"
    if any(k in text_low for k in ["cash", "పూర్తి", "నగదు"]):
        return "full"

    scores = {"full": 0, "emi": 0}
    for kw in full_kw:
        if kw in text_low:
            scores["full"] += 1
    for kw in loan_kw:
        if kw in text_low:
            scores["emi"] += 1

    if scores["full"] > scores["emi"]:
        return "full"
    if scores["emi"] > scores["full"]:
        return "emi"

    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"""
User answered payment preference (English/Hindi/Odia/Telugu): "{text}"

Classify:
FULL = full payment / cash
EMI = bank loan / EMI / installment

Reply ONLY: FULL / EMI / UNCLEAR
""",
                generation_config=genai.GenerationConfig(max_output_tokens=5, temperature=0)
            )
            track_tokens_usage(resp)
            ans = resp.text.strip().upper()
            if "FULL" in ans:
                return "full"
            if "EMI" in ans:
                return "emi"
        except Exception as e:
            print(f"Payment detect error: {e}")

    return None


def _retry_or_end(session_id, state):
    """Increment retry counter. Re-ask up to MAX_RETRIES, then end gracefully."""
    retries = sessions[session_id].get("retries", 0) + 1
    sessions[session_id]["retries"] = retries
    if retries >= MAX_RETRIES:
        sessions[session_id]["state"] = "ENDED"
        sessions[session_id]["retries"] = 0
        _finish_call(session_id, "max_retries")
        return END_MISUNDERSTAND
    question = RETRY_QUESTIONS.get(state, "")
    return RETRY_PREFIX + question


# ─────────────────────────────────────────────────────────────────────────────
# State handlers
# ─────────────────────────────────────────────────────────────────────────────

def handle_state_1(session_id, user_text_low, user_text_safe):
    _log_exchange(session_id, "STATE_1", user_text_safe)

    if is_positive(user_text_low):
        sessions[session_id]["retries"] = 0
        sessions[session_id]["state"] = "STATE_2"
        return STATE_2_INVESTMENT_REASON
    else:
        sessions[session_id]["state"] = "ENDED"
        _finish_call(session_id, "not_interested")
        return STATE_1_NO_END


def handle_state_2(session_id, user_text_low, user_text_safe):
    intent = _detect_property_type(user_text_low)
    if intent is None:
        intent = "investment"  # soft fallback — keep conversation moving

    _log_exchange(session_id, "STATE_2", user_text_safe)
    sessions[session_id]["data"]["purpose"] = intent
    sessions[session_id]["retries"] = 0
    sessions[session_id]["state"] = "STATE_3"
    return STATE_3_PROPERTY


def handle_state_3(session_id, user_text_low, user_text_safe):
    """
    FIX: Two valid paths through STATE_3:
      1. User asks about price  → answer price, embed payment question,
                                   stay in STATE_3 only if no land size given,
                                   OR advance to STATE_4 if we have enough info.
      2. User states land size  → log it, advance to STATE_4.

    Previously the code advanced to STATE_4 even when answering a price
    question, so the next user response (still in the price conversation)
    was sent to handle_state_4 (payment detection) instead of collecting
    the land size.  Now price-only queries stay in STATE_3 so the user can
    still confirm their preferred land size before we move on.
    """
    price_keywords = [
        "price", "cost", "rate", "amount", "how much",
        "ఎంత", "ధర", "రేటు", "ఖర్చు",
        "entha", "dhara", "retu", "karchu", "enta", "costu", "ratu",
    ]
    size_keywords = [
    "2bhk", "3bhk", "2 bhk", "3 bhk", "two bhk", "three bhk",
    "అపార్ట్‌మెంట్", "విల్లా", "డూప్లెక్స్",
    "apartment", "villa", "duplex", "flat",
    "రెండు బెడ్‌రూమ్", "మూడు బెడ్‌రూమ్",
    ]

    asking_price = any(kw in user_text_low for kw in price_keywords)
    gave_size    = any(kw in user_text_low for kw in size_keywords)

    print(f"[STATE_3] asking_price={asking_price}, gave_size={gave_size} | '{user_text_safe}'")

    # ── Case 1: user gave a land size (may also have asked price) ────────────
    if gave_size:
        _log_exchange(session_id, "STATE_3", user_text_safe)
        sessions[session_id]["data"]["property_type"] = user_text_safe
        sessions[session_id]["retries"] = 0
        sessions[session_id]["state"] = "STATE_4"

        if asking_price:
            # They asked price AND stated size in one go — answer both, move on
            return STATE_PRICE_AND_PROPERTY
        return STATE_4_PAYMENT

    # ── Case 2: user only asked about price — answer but STAY in STATE_3 ─────
    if asking_price:
        # Do NOT log exchange or advance state here — we still need land size
        # Reset retries so the follow-up size question gets a clean slate
        sessions[session_id]["retries"] = 0
        return STATE_PRICE_AND_PROPERTY   # named constant → pre-recorded lookup works

    # ── Case 3: neither — ask again ──────────────────────────────────────────
    return _retry_or_end(session_id, "STATE_3")


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

    if timeline == "enquiry":
        _finish_call(session_id, "completed")
        sessions[session_id]["state"] = "ENDED"
        return [STATE_7_CLOSING, STATE_DISCONNECT]

    sessions[session_id]["state"] = "STATE_6"
    return STATE_6_SITE_VISIT


def handle_state_6(session_id, user_text_low, user_text_safe):
    if is_positive(user_text_low):
        visit = "yes"
    elif any(x in user_text_low for x in ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "సండే", "date", "తేదీ", "రోజు"]):
        visit = "scheduled"
    elif any(x in user_text_low for x in ["no", "later", "వద్దు"]):
        visit = "no"
    else:
        visit = "unclear"

    _log_exchange(session_id, "STATE_6", user_text_safe)
    sessions[session_id]["data"]["site_visit_interest"] = visit
    sessions[session_id]["retries"] = 0
    sessions[session_id]["state"] = "STATE_7"
    return STATE_7_CLOSING


def handle_state_7(session_id, user_text_low, user_text_safe):
    """
    Closing message already played.  Any input here just triggers disconnect.
    Do NOT log or process user input at this point.
    """
    sessions[session_id]["state"] = "DISCONNECT"
    return STATE_DISCONNECT


def handle_disconnect(session_id, user_text_low, user_text_safe):
    _finish_call(session_id, "completed")
    sessions[session_id]["state"] = "ENDED"
    return ""


STATE_HANDLERS = {
    "STATE_1":    handle_state_1,
    "STATE_2":    handle_state_2,
    "STATE_3":    handle_state_3,
    "STATE_4":    handle_state_4,
    "STATE_5":    handle_state_5,
    "STATE_6":    handle_state_6,
    "STATE_7":    handle_state_7,
    "DISCONNECT": handle_disconnect,
}

# ─────────────────────────────────────────────────────────────────────────────
# State → question maps (used for DB logging)
# ─────────────────────────────────────────────────────────────────────────────

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
        "Hello! I am calling from Sanarelli. "
        "Premium flats near Hyderabad Outer Ring Road Exit 5, just 1 minute away. "
        "Price: ₹4,500 per sq ft. Handover: December 2026. "
        "Would you like to know more details?"
    ),
    "STATE_2": "Are you looking for a new home in Hyderabad or is this for investment?",
    "STATE_3": "Would you prefer a 2BHK apartment or a 3BHK duplex villa?",
    "STATE_4": "Would you prefer to buy with full payment or with EMI facility?",
    "STATE_5": "When are you planning to make this investment — within 1 month, 3 months, or just exploring?",
    "STATE_6": "Free site visit available daily with pickup facility. What date and time works for you?",
    "STATE_7": (
        "Thank you! Your details have been recorded. "
        "Our team will call you to confirm the site visit. "
        "Thank you for choosing Sanarelli!"
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Main state machine entry point
# ─────────────────────────────────────────────────────────────────────────────

def ask_instant_ai(session_id, user_text=None, is_start=False):
    """
    Central bot brain.  Called by both Flask routes and SmartFlo WS handler.

    FIX: Removed the eager STATE_7 → DISCONNECT → ENDED auto-chain that was
    firing on every response.  The chain now only executes when the handler
    explicitly sets the state to DISCONNECT (i.e. handle_state_7 was reached
    because the user replied *after* the closing message).  This prevents
    echo / stale audio frames during greeting playback from instantly ending
    the call.
    """
    # Initialise session if this is the very first touch
    if session_id not in sessions:
        sessions[session_id] = {
            "state":    "STATE_1",
            "retries":  0,
            "data":     {},
            "turn":     0,
            "no_speech": 0,
        }

    # ── Greeting ─────────────────────────────────────────────────────────────
    if is_start:
        return STATE_1_GREETING

    user_text_safe = str(user_text).strip()
    user_text_low  = user_text_safe.lower()
    state          = sessions[session_id]["state"]

    if state == "ENDED":
        print(f"[ask_instant_ai] Session {session_id} already ENDED — ignoring input.")
        return ""

    handler = STATE_HANDLERS.get(state)
    if not handler:
        print(f"[ask_instant_ai] No handler for state '{state}' — resetting to STATE_1.")
        sessions[session_id]["state"] = "STATE_1"
        return STATE_1_GREETING

    # ── Run the handler ───────────────────────────────────────────────────────
    response = handler(session_id, user_text_low, user_text_safe)

    # ── FIX: Only auto-chain DISCONNECT→ENDED if handler actually set DISCONNECT
    # Previously this block ran unconditionally after EVERY handler call,
    # meaning any audio frame that arrived while the bot was speaking the
    # greeting could trigger the full close sequence immediately.
    if sessions[session_id]["state"] == "DISCONNECT":
        _finish_call(session_id, "completed")
        sessions[session_id]["state"] = "ENDED"
        # response is already STATE_DISCONNECT (set by handle_state_7)
        # so just return it — don't replace it
        return response

    return response


# ─────────────────────────────────────────────────────────────────────────────
# handle_user_input — thin wrapper for local / browser testing
# ─────────────────────────────────────────────────────────────────────────────

def handle_user_input(session, user_text):
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())

    session_id     = session["session_id"]
    is_new_session = False

    if session_id not in sessions:
        sessions[session_id] = {
            "state": "STATE_1", "retries": 0,
            "data": {}, "turn": 0, "no_speech": 0,
        }
        db.create_call(session_id, mobile_number="test")
        is_new_session = True

    if sessions[session_id]["state"] == "ENDED":
        print(f"[INFO] Ignoring input — session already ended ({session_id})")
        return {"text": "", "audio_path": "", "end": True}

    if is_new_session or sessions[session_id]["turn"] == 0:
        bot_reply = ask_instant_ai(session_id, is_start=True)
        sessions[session_id]["turn"] = 1
    else:
        bot_reply = ask_instant_ai(session_id, user_text=user_text)

    # Audio handling — list vs single string
    if isinstance(bot_reply, list):
        audio_paths = []
        for reply in bot_reply:
            if reply in PRE_RECORDED_AUDIO and os.path.exists(PRE_RECORDED_AUDIO[reply]):
                audio_paths.append(PRE_RECORDED_AUDIO[reply])
            else:
                audio_file = f"static/reply_{session_id}_{len(audio_paths)}.wav"
                text_to_speech_te(reply, audio_file)
                audio_paths.append(audio_file)
        return {
            "text": bot_reply,
            "audio_paths": audio_paths,
            "end": sessions[session_id]["state"] == "ENDED",
        }

    audio_path = f"static/reply_{session_id}.wav"
    text_to_speech_te(bot_reply, audio_path)
    return {
        "text": bot_reply,
        "audio_path": audio_path,
        "end": sessions[session_id]["state"] == "ENDED",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TTS
# ─────────────────────────────────────────────────────────────────────────────

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")


def text_to_speech_te(text, output_path):
    """
    Convert Telugu text to speech using Sarvam AI TTS.
    Falls back to gTTS if Sarvam fails.
    Validates output so callers can trust the file exists and is non-empty.
    """
    if not text or not text.strip():
        print(f"[TTS] ⚠️  Empty text passed — skipping TTS for {output_path}")
        return None

    try:
        response = sarvam_client.text_to_speech.convert(
            text=text,
            target_language_code="te-IN",
            speaker="ritu",
            pace=1.09,
            speech_sample_rate=22050,
            enable_preprocessing=True,
            model="bulbul:v3",
        )
        audio_data = base64.b64decode(response.audios[0])
        with open(output_path, "wb") as f:
            f.write(audio_data)
        print(f"[TTS] ✅ Sarvam → {output_path} ({len(audio_data)} bytes)")
        return output_path
    except Exception as e:
        print(f"[TTS] ❌ Sarvam failed: {e} — trying gTTS fallback")

    try:
        tts = gTTS(text=text, lang="te")
        tts.save(output_path)
        print(f"[TTS] ✅ gTTS fallback → {output_path}")
        return output_path
    except Exception as e2:
        print(f"[TTS] ❌ gTTS also failed: {e2}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Flask Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/solar_test")
def index():
    return render_template("solar_test.html")


@app.route("/start_call", methods=["POST"])
def start_call():
    session_id = str(uuid.uuid4())
    mobile     = request.form.get("mobile_number", "unknown")

    bot_reply = ask_instant_ai(session_id, is_start=True)
    db.create_call(session_id, mobile_number=mobile)

    # Resolve audio URL — pre-recorded first, dynamic TTS fallback
    pre_path = PRE_RECORDED_AUDIO.get(bot_reply)
    if pre_path and os.path.exists(pre_path):
        audio_url = f"/{pre_path}"
    else:
        if pre_path:
            print(f"[start_call] Pre-recorded file missing: {pre_path} — generating TTS")
        audio_file = f"static/intro_{session_id}.wav"
        result = text_to_speech_te(bot_reply, audio_file)
        audio_url = f"/{audio_file}" if result else ""

    return jsonify({
        "session_id": session_id,
        "text":       bot_reply,
        "audio_url":  [audio_url],
        "tokens":     gemini_tokens,
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    session_id = request.form.get("session_id")

    if not session_id or session_id not in sessions:
        return jsonify({"error": "Invalid or expired session. Please start a new call."}), 400

    if sessions[session_id]["state"] == "ENDED":
        return jsonify({"answer": "", "audio_url": [], "end": True})

    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided."}), 400

    file            = request.files["audio"]
    user_audio_path = f"static/user_audio_{session_id}.webm"
    file.save(user_audio_path)

    user_text = ""
    wav_path  = f"static/temp_{session_id}.wav"

    try:
        ffmpeg_result = subprocess.run(
            ["ffmpeg", "-y", "-i", user_audio_path, "-ac", "1", "-ar", "16000", wav_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        if ffmpeg_result.returncode != 0:
            err = ffmpeg_result.stderr.decode("utf-8", errors="ignore")[-200:]
            print(f"[Session {session_id}] ffmpeg failed: {err}")
            raise Exception("ffmpeg conversion failed")

        if not os.path.exists(wav_path):
            raise Exception("WAV file not created by ffmpeg")

        wav_size  = os.path.getsize(wav_path)
        webm_size = os.path.getsize(user_audio_path) if os.path.exists(user_audio_path) else 0
        print(f"[Session {session_id}] Audio sizes — WebM: {webm_size}B, WAV: {wav_size}B")

        if wav_size < 5000:
            raise Exception(f"WAV too small ({wav_size}B) — likely silence")

        r = sr.Recognizer()
        r.energy_threshold = 300
        with sr.AudioFile(wav_path) as source:
            audio_data = r.record(source)
        user_text = r.recognize_google(audio_data, language="te-IN")
        print(f"[Session {session_id}] Transcription: '{user_text}'")

    except sr.UnknownValueError:
        print(f"[Session {session_id}] Google STT: could not understand audio")
        user_text = ""
    except sr.RequestError as e:
        print(f"[Session {session_id}] Google STT API error: {e}")
        user_text = ""
    except Exception as e:
        print(f"[Session {session_id}] Transcription error: {e}")
        user_text = ""
    finally:
        try: os.remove(wav_path)
        except: pass
        try: os.remove(user_audio_path)
        except: pass

    # ── No speech ─────────────────────────────────────────────────────────────
    if not user_text:
        no_speech_count = sessions[session_id].get("no_speech", 0) + 1
        sessions[session_id]["no_speech"] = no_speech_count
        print(f"[Session {session_id}] No speech ({no_speech_count}/{MAX_NO_SPEECH})")

        if no_speech_count >= MAX_NO_SPEECH:
            sessions[session_id]["state"]    = "ENDED"
            sessions[session_id]["no_speech"] = 0
            bot_audio_path = f"static/reply_{session_id}.wav"
            text_to_speech_te(NO_SPEECH_END, bot_audio_path)
            return jsonify({
                "text":      "[No speech detected]",
                "answer":    NO_SPEECH_END,
                "audio_url": f"/{bot_audio_path}",
                "tokens":    gemini_tokens,
                "end":       True,
            })

        return jsonify({
            "text":      "[No speech detected]",
            "answer":    "మీ స్వరం వినిపించడం లేదు. దయచేసి మళ్లీ చెప్పండి.",
            "audio_url": [],
            "tokens":    gemini_tokens,
        })

    # Reset no-speech counter on successful transcription
    sessions[session_id]["no_speech"] = 0

    bot_reply = ask_instant_ai(session_id, user_text=user_text)
    print(f"[Session {session_id}] State: {sessions[session_id]['state']} | Bot: {str(bot_reply)[:80]}")

    # ── FIX: handle list replies (e.g. closing + disconnect) ──────────────────
    if isinstance(bot_reply, list):
        audio_url = []
        for reply in bot_reply:
            pre_path = PRE_RECORDED_AUDIO.get(reply)
            if pre_path and os.path.exists(pre_path):
                audio_url.append(f"/{pre_path}")
            else:
                if pre_path:
                    print(f"[webhook] Pre-recorded missing: {pre_path} — generating TTS")
                audio_file = f"static/reply_{session_id}_{len(audio_url)}.wav"
                text_to_speech_te(reply, audio_file)
                audio_url.append(f"/{audio_file}")

        return jsonify({
            "text":      user_text,
            "answer":    bot_reply,
            "audio_url": audio_url,
            "tokens":    gemini_tokens,
            "end":       sessions[session_id]["state"] == "ENDED",
        })

    # ── Single reply ──────────────────────────────────────────────────────────
    pre_path = PRE_RECORDED_AUDIO.get(bot_reply)
    if pre_path and os.path.exists(pre_path):
        audio_url = f"/{pre_path}"
    else:
        if pre_path:
            print(f"[webhook] Pre-recorded missing: {pre_path} — generating TTS")
        bot_audio_path = f"static/reply_{session_id}.wav"
        text_to_speech_te(bot_reply, bot_audio_path)
        audio_url = f"/{bot_audio_path}"

    return jsonify({
        "text":      user_text,
        "answer":    bot_reply,
        "audio_url": [audio_url],
        "tokens":    gemini_tokens,
        "end":       sessions[session_id]["state"] == "ENDED",
    })


if __name__ == "__main__":
    app.run(debug=True, port=8080)