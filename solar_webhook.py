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
import threading

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
    "నమస్కారం! నేను మీరై సోలార్ నుండి దీప్తి మాట్లాడుతున్నాను. "
    "మీరు మీ ఇంట్లో సోలార్ ఏర్పాటు చేసుకుని డెబ్బై ఎనిమిది వేల రూపాయలు వరకు ప్రభుత్వ సబ్సిడీ పొందవచ్చు, "
    "మరియు ప్రతి నెల నాలుగు వేల రూపాయలు వరకు విద్యుత్ బిల్లును ఆదా చేసుకోవచ్చు. "
    "మీరు సోలార్ గురించి ఉచిత సమాచారం పొందాలనుకుంటున్నారా?"
)

STATE_1_NO_END = (
    "పర్లేదు! మీరు తర్వాత సోలార్ గురించి తెలుసుకోవాలనుకుంటే, "
    "దయచేసి ఈ నంబర్‌కు కాల్ చేయండి. "
    "ధన్యవాదాలు! మీ రోజు మంచిగా గడవాలి."
)

STATE_2_PROPERTY = (
    "చాలా బాగుంది! ముందుగా చెప్పండి, మీ ప్రాపర్టీ ఏ రకం? "
    "ఇది సొంత ఇల్లు, అపార్ట్‌మెంట్ లేదా కమర్షియల్ ప్రాపర్టీనా?"
)

STATE_3_BILL = (
    "మీ నెలవారీ విద్యుత్ బిల్లు సాధారణంగా ఎంత వస్తుంది? "
    "వెయ్యి నుంచి రెండు వేల మధ్యనా, "
    "రెండు వేల నుంచి ఐదు వేల మధ్యనా, "
    "లేదా ఐదు వేల కంటే ఎక్కువనా?"
)

STATE_3_LOW_BILL_CONTINUE = (
    "మీ బిల్లు తక్కువగా ఉన్నప్పటికీ, సోలార్ ప్యానెల్స్ తో మీరు ఆ బిల్లును పూర్తిగా జీరో చేసుకోవచ్చు, మరియు భవిష్యత్తులో కరెంట్ ఛార్జీల పెంపు నుండి రక్షణ పొందవచ్చు. "
    "మరి మీరు సోలార్ ఇన్‌స్టాలేషన్ ఎప్పటిలో చేయించుకోవాలని భావిస్తున్నారు? ఒక నెలలోపలనా, ఒకటి నుంచి మూడు నెలల మధ్యనా, లేదా ప్రస్తుతం కేవలం సమాచారం కోసం మాత్రమేనా?"
)

STATE_4_TIMELINE = (
    "మీరు సోలార్ ఇన్‌స్టాలేషన్ ఎప్పటిలో చేయించుకోవాలని భావిస్తున్నారు? "
    "ఒక నెలలోపలనా, ఒకటి నుంచి మూడు నెలల మధ్యనా, "
    "లేదా ప్రస్తుతం కేవలం సమాచారం కోసం మాత్రమేనా?"
)
STATE_4_ENQUIRY_END = (
    "పర్లేదు! మీరు కేవలం సమాచారం కోసం చూస్తున్నారు కాబట్టి, నేను మీ వివరాలను నమోదు చేశాను. "
    "మా బృందం త్వరలో మిమ్మల్ని సంప్రదించి పూర్తి సమాచారాన్ని అందిస్తారు. మీ సమయానికి ధన్యవాదాలు, కాల్ ముగిసింది."
)

STATE_5_PAYMENT = (
    "మీరు చెల్లింపు ఎలా చేయాలనుకుంటున్నారు? "
    "పూర్తి చెల్లింపు లేదా బ్యాంక్ లోన్ ద్వారా?"
)

STATE_6_CLOSING = (
    "ధన్యవాదాలు! మీ వివరాలు విజయవంతంగా నమోదు అయ్యాయి. "
    "మా టీమ్ త్వరలోనే మీతో సంప్రదించి ఉచిత హోమ్ విజిట్‌ను షెడ్యూల్ చేస్తుంది. "
    "ఈ విజిట్ సమయంలో, మా నిపుణులైన ఇంజనీర్ మీ ప్రాపర్టీని పరిశీలించి "
    "మీకు సరైన సోలార్ పరిష్కారాన్ని సూచిస్తారు. "
    "మీరై సోలార్ ను ఎంచుకున్నందుకు ధన్యవాదాలు! మీ రోజు మంచిగా గడవాలి."
)

STATE_LOCATION = "మా ఆఫీస్ విశాఖపట్నంలోని రైల్వే న్యూ కాలనీ దగ్గర ఉంది అండి."

STATE_DISCONNECT = "ధన్యవాదాలు. కాల్ ముగిసింది."


STATE_6_FINAL = (
    "ధన్యవాదాలు! మీ వివరాలు విజయవంతంగా నమోదు అయ్యాయి. "
    "మా టీమ్ త్వరలోనే మీతో సంప్రదించి ఉచిత హోమ్ విజిట్‌ను షెడ్యూల్ చేస్తుంది. "
    "ఈ విజిట్ సమయంలో, మా నిపుణులైన ఇంజనీర్ మీ ప్రాపర్టీని పరిశీలించి "
    "మీకు సరైన సోలార్ పరిష్కారాన్ని సూచిస్తారు. "
    "మీరై సోలార్ ను ఎంచుకున్నందుకు ధన్యవాదాలు! మీ రోజు మంచిగా గడవాలి. "
    "ధన్యవాదాలు. కాల్ ముగిసింది."
)


# ── Retry / Error Messages ────────────────────────────────────────────────────
MAX_RETRIES = 3
MAX_NO_SPEECH = 3

RETRY_PREFIX = "నేను సరిగ్గా అర్థం చేసుకోలేకపోయాను. "

END_MISUNDERSTAND = "దయచేసి తరువాత మళ్లీ కాల్ చేయండి. ధన్యవాదాలు."

NO_SPEECH_END = "మీ స్వరం వినిపించడం లేదు. దయచేసి తరువాత కాల్ చేయండి."

RETRY_QUESTIONS = {
    "STATE_1": "మీరు సోలార్ గురించి ఉచిత సమాచారం పొందాలనుకుంటున్నారా?",
    "STATE_2": "మీ ప్రాపర్టీ ఏ రకం?",
    "STATE_3": "మీ విద్యుత్ బిల్లు ఎంత వస్తుంది?",
    "STATE_4": "మీరు సోలార్ ఎప్పుడు ఇన్‌స్టాల్ చేయించుకోవాలని అనుకుంటున్నారు?",
    "STATE_5": "మీరు చెల్లింపు ఎలా చేయాలనుకుంటున్నారు?"
}


# ── Pre-recorded audio mapping ────────────────────────────────────────────────
PRE_RECORDED_AUDIO = {
    STATE_LOCATION: "static/pre_audio/STATE_LOCATION.wav",

    STATE_1_GREETING:  "static/pre_audio/STATE_1_GREETING.wav",
    STATE_1_NO_END:    "static/pre_audio/STATE_1_NO_END.wav",
    STATE_2_PROPERTY:  "static/pre_audio/STATE_2_PROPERTY.wav",
    STATE_3_BILL:      "static/pre_audio/STATE_3_BILL.wav",
    STATE_3_LOW_BILL_CONTINUE: "static/pre_audio/STATE_3_LOW_BILL_CONTINUE.wav",
    STATE_4_TIMELINE:  "static/pre_audio/STATE_4_TIMELINE.wav",
    STATE_4_ENQUIRY_END: "static/pre_audio/STATE_4_ENQUIRY_END.wav",
    STATE_5_PAYMENT:   "static/pre_audio/STATE_5_PAYMENT.wav",
    STATE_6_CLOSING:   "static/pre_audio/STATE_6_CLOSING.wav",
    STATE_DISCONNECT:  "static/pre_audio/STATE_DISCONNECT.wav",
    STATE_6_FINAL: "static/pre_audio/STATE_6_FINAL.wav",
    
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

def is_positive(text):
    text = text.lower().strip()

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
        "అవును చెప్పండి", "సరే చెప్పండి", "హా", "హాన్", "సరేనండి", "ఆ", "ఊ", 
        "వినాలనుకుంటున్నాను", "పర్వాలేదు", "కంటిన్యూ చేయండి", "వివరాలు చెప్పండి", 
        "తెలుసుకోవాలి", "ఇంట్రెస్ట్ ఉంది", "ఎస్", "ఎస్రండి"

        "haan bolo", "haan batao", "ok bolo", "ok batao",
        "bolo", "batao", "samjhao", "samjha do",
        "haan ji bataiye", "haan ji boliye",
        "ok tell me", "yes tell me", "yes please",
        "hello", "hi", "नमस्ते", "ନମସ୍କାର", "ହ୍ୟାଲୋ", "నమస్కారం", "హలో"
    }
    
    # ── NEGATIVE KEYWORDS (Added missing single Telugu words) ──
    negatives_exact = {
        "no", "nope", "not", "nahi", "na", "नहीं", "ना",
        "ନା", "ନାହିଁ", "కాదు", "వద్దు", "లేదు", "అక్కర్లేదు", "వద్దండి", "లేదండి", 
        "పెట్టేయ్", "పెట్టేయండి", "నో"
    }

    # 1. ── CHECK PHRASES FIRST (Fixes the multi-word bug) ──
    negative_phrases = ["అవసరం లేదు", "నాకు వద్దు", "not interested", "don't want",
        "ఇంట్రెస్ట్ లేదు", "టైమ్ లేదు", "కాల్ చేయకండి", "నాట్ ఇంట్రెస్టెడ్"]
    if any(phrase in text for phrase in negative_phrases):
        return False

    # 2. ── TOKEN CHECK ───────────────────────────────────
    words = text.split()
    has_positive = any(w in positives_exact for w in words)
    has_negative = any(w in negatives_exact for w in words)

    if has_negative and not has_positive:
        return False

    if has_positive:
        return True

    # 3. ── GEMINI FALLBACK (Fixes the "Blind Faith" bug) ──
    # If keywords fail, use your ultra-fast Gemini function to decide!
    global gemini_model
    if gemini_model:
        prompt = f"The user was asked if they want free solar info. They replied: '{text}'. Does this mean YES or NO? Reply with exactly 'yes' or 'no'."
        gemini_decision = _gemini_yes_no(prompt)
        if gemini_decision is not None:
            return gemini_decision

    # 4. ── FINAL SAFETY NET ──
    return True

def _detect_property_type(text):
    """Returns 'independent', 'apartment', 'commercial', or None."""
    text_clean = text.lower().strip()

    # ── NORMALIZE TEXT ────────────────────────────────
    text_clean = (
        text_clean.replace(".", " ")
        .replace(",", " ")
        .replace("।", " ")
        .replace("?", " ")
    )
    
    # 🚀 Create a spaceless version to catch STT joined words
    text_spaceless = text_clean.replace(" ", "")

    # ── KEYWORDS (All Languages Preserved) ────────────
    independent_kw = [
        # English
        "independent", "house", "home", "villa", "bungalow", "plot",
        # Hindi
        "ghar", "मकान", "घर", "kothi", "खुद का घर",
        # Odia
        "ଘର", "ସ୍ୱତନ୍ତ୍ର", "ନିଜ ଘର", "ଭିଲା",
        
        # 🚀 Telugu (Phonetic Roots & Full Words)
        "ఇల్లు", "హౌస్", "విల్లా", "మాదే", "పోర్షన్",
        "సొంత", "స్వంత", "సంత", "సంధి",  # <-- The Magic Phonetic Roots!
        "ఇల్లే", "సొంతి", "స్వంతి", "సంతి",
        "సొంత ఇల్లు", "స్వంత ఇల్లు", "సొంతిల్లు", "స్వంతిల్లు", 
        "సొంత ఇల్లే", "స్వంత ఇల్లే", "మాది సొంతిల్లు", "నా సొంత ఇల్లు", 
        "నాది సొంతిల్లు", "సొంత ఇల్లు అండి", "ఇండిపెండెంట్", "హవుస్", "మా సొంత ఇల్లు",
        "సొంత ఇల్లేనండి", "మాదేనండి"
    ]

    apartment_kw = [
        # English
        "apartment", "flat", "flats", "building", "society",
        # Hindi
        "अपार्टमेंट", "फ्लैट",
        # Odia
        "ଆପାର୍ଟମେଣ୍ଟ", "ଫ୍ଲାଟ", "ବିଲ୍ଡିଂ",
        # Telugu
        "అపార్ట్‌మెంట్", "అపార్ట్మెంట్", "ఫ్లాట్", "బిల్డింగ్", "ప్లాట్", "ప్లాట్స్", 
        "అపార్ట్ మెంట్", "అపార్ట్మెంట్లో", "అపార్ట్మెంట్స్", "ఫ్లాట్స్", "ఫ్లాట్ లో", "సొసైటీ", 
        "భవనం", "సముదాయం", "కాంప్లెక్స్", "అపార్టుమెంటు", "గేటెడ్ కమ్యూనిటీ"
    ]

    commercial_kw = [
        # English
        "commercial", "shop", "office", "factory", "warehouse", "mall", "showroom",
        # Hindi
        "dukan", "दुकान", "ऑफिस",
        # Odia
        "ଦୋକାନ", "ଅଫିସ", "କମର୍ସିଆଲ", "କାରଖାନା",
        # Telugu
        "దుకాణం", "ఆఫీస్", "కమర్షియల్", "ఫ్యాక్టరీ", "గోదాం", "షోరూమ్"
    ]

    # ── SCORING MATCH (Upgraded with Spaceless logic) ──
    scores = {
        "independent": 0,
        "apartment": 0,
        "commercial": 0
    }

    # 🚀 It checks the normal sentence, AND the spaceless sentence
    for kw in independent_kw:
        if kw in text_clean or kw.replace(" ", "") in text_spaceless:
            scores["independent"] += 1

    for kw in apartment_kw:
        if kw in text_clean or kw.replace(" ", "") in text_spaceless:
            scores["apartment"] += 1

    for kw in commercial_kw:
        if kw in text_clean or kw.replace(" ", "") in text_spaceless:
            scores["commercial"] += 1

    # ── DECISION BASED ON MAX SCORE ───────────────────
    best = max(scores, key=scores.get)

    if scores[best] > 0:
        return best

    # ── GEMINI FALLBACK ───────────────────────────────
    # (Kept intact just in case, though the spaceless check will catch almost everything!)
    global gemini_model
    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"""
User replied to property type question (English/Hindi/Odia/Telugu): "{text}"

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
    """Returns 'very_low' (<=1k), 'low' (1k-2k), 'mid' (2k-5k), 'high' (5k+), or None."""
    text_lower = text.lower().strip()

    # ── NORMALIZE NUMBERS ─────────────────────────────
    text_clean = re.sub(r'(\d),(\d)', r'\1\2', text_lower)
    text_clean = re.sub(r'(\d+)\s*k', lambda m: str(int(m.group(1)) * 1000), text_clean)

    range_match = re.findall(r'(\d+)\s*[-to]+\s*(\d+)', text_clean)
    if range_match:
        nums = [int(n) for pair in range_match for n in pair]
    else:
        nums = [int(n) for n in re.findall(r'\d+', text_clean)]

    if nums:
        avg_amount = sum(nums) // len(nums)
        if avg_amount >= 5000: return "high"
        elif avg_amount >= 2000: return "mid"
        elif avg_amount > 1000: return "low"
        elif avg_amount > 0 and avg_amount <= 1000:  #  FIX: <= 1000 catches exactly 1000!
            return "very_low"

    # ── KEYWORD MATCHING ─────────────────────────────
    high_kw = [
        "high", "above 5000", "more than 5000", "zyada", 
        "ఐదు వేల పైన", "ఐదు వేల కంటే ఎక్కువ", "ఎక్కువే", "చాలా ఎక్కువ", "పైన", 
        "ఐదుకి పైన", "పది వేలు", "ఆరు వేలు", "ఏడు వేలు", "ఐదు వేలకి పైనే"
    ]
    mid_kw = [
        "2000", "3000", "4000", "around 3", 
        "రెండు వేల", "మూడు వేల", "నాలుగు వేల", "రెండు వేలు", "మూడు వేలు", "నాలుగు వేలు", 
        "ఐదు వేల లోపు", "ఐదు వేల లోపల", "రెండు నుంచి ఐదు", "రెండు ఐదు మధ్యలో", 
        "మూడు వేల దాకా", "రెండుకి ఐదుకి మధ్య"
    ]
    low_kw = [
        "1500", "around 2", 
        "పదిహేను వందలు", "పదిహేనొందలు", "వెయ్యికి రెండు వేలకి మధ్య", 
        "రెండు వేల లోపు", "రెండు వేల లోపల", "వెయ్యి పైన", "రెండు వేలకి తక్కువ"
    ]
    #  FIX: Massive expansion of very low bill keywords in English and Telugu
    very_low_kw = [
        # The basics & Shorthand
        "1000", "ek hazar", "hazar", "వెయ్యి", "1k", "one k",
        
        # "Under 1000" variations (English & Hindi)
        "below 1000", "under 1000", "less than 1000", 
        "below one thousand", "under one thousand", "under 1k", "below 1k",
        "hazar se kam", "hazar ke andar",
        
        # "Under 1000" variations (Telugu Conversational)
        "1000 lopala", "1000 లోపల", "1000 lopu", "1000 లోపు", 
        "1000 varaku", "1000 వరకు", "1000 దాకా",
        "వెయ్యి లోపల", "వెయ్యికి లోపల", "వెయ్యి కంటే తక్కువ", 
        "వెయ్యి లోపు", "వెయ్యి వరకు", "వెయ్యి దాకా",

        # STT Typos & Phonetic Spellings for 1000
        "వేయి", "వెయి", "వయ్యి", "వెయ్", "వేయ్యి", "veyi", "veyyi", 
        "వెయ్య", "veyya", "వేయికి", "వెయ్యికి",
        
        # Specific hundreds (Numbers - Expanded full range)
        "100", "200", "300", "400", "500", "600", "700", "800", "900",
        
        # Specific hundreds (Telugu Spoken & Sandhi/Joined Words)
        "వంద", "రెండు వందలు", "మూడు వందలు", "నాలుగు వందలు", "ఐదు వందలు", 
        "ఆరు వందలు", "ఏడు వందలు", "ఎనిమిది వందలు", "తొమ్మిది వందలు",
        "రెండొందలు", "మూడొందలు", "నాలగొందలు", "ఐదొందలు", "ఆరొందలు", 
        "ఏడొందలు", "ఎనిమిదొందలు", "తొమ్మిదొందలు",
        
        # General low words & Contextual Fillers
        "తక్కువ", "లోపల", "లోపు", "వరకు", "దాకా", 
        "చాలా తక్కువ", "వందల్లో", "vandallo"
        
    ]
    for kw in high_kw:
        if kw in text_lower: return "high"
    for kw in mid_kw:
        if kw in text_lower: return "mid"
    for kw in very_low_kw:  # 🚀 Check very low keywords first
        if kw in text_lower: return "very_low"
    for kw in low_kw:
        if kw in text_lower: return "low"

    # ── GEMINI FALLBACK ──────────────────────────────
    global gemini_model
    if gemini_model:
        try:
            resp = gemini_model.generate_content(
                f"""
                            User answered electricity bill in English/Hindi/Odia/Telugu: "{text}"

                            CRITICAL RULE: If the text is just random, short, nonsensical syllables or bizarre words (like 'ఈ', 'బై', 'బెంగీ', single letters, or grammar mistakes), it is an STT hallucination caused by telecom static when the user said "1000" (వెయ్యి). You MUST classify these weird hallucinations as VERY_LOW.

                            Classify into:
                            VERY_LOW = ₹1000 or under (e.g., 500, 800, 1000)
                            LOW = ₹1001–2000
                            MID = ₹2000–5000
                            HIGH = ₹5000+

                            Reply ONLY: VERY_LOW / LOW / MID / HIGH / UNCLEAR
                            """,
                generation_config=genai.GenerationConfig(max_output_tokens=5, temperature=0)
            )
            track_tokens_usage(resp)
            ans = resp.text.strip().upper()

            if "VERY_LOW" in ans: return "very_low"
            if "HIGH" in ans: return "high"
            if "MID" in ans: return "mid"
            if "LOW" in ans: return "low"
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

    immediate_kw = [
        # English
        "1 month", "one month", "within 1 month", "immediately", "urgent", "asap",

        # Hindi
        "1 mahine", "ek mahine", "jaldi", "turant", "abhi", "एक महीने", "तुरंत", "अभी",

        # Odia
        "ଏକ ମାସ", "ତୁରନ୍ତ", "ସତ୍ତ୍ୱର", "ଏବେ", "ଶୀଘ୍ର",

        # Telugu
       "ఒక నెల", "తక్షణం", "ఇప్పుడే", "త్వరగా", "నెలలోపు", "నెలలోపల", "వెంటనే", 
        "ఈ నెలే", "ఒక్క నెల", "నెల రోజుల్లో", "వీలైనంత త్వరగా", "వెంటనే కావాలి", "త్వరలో"
    ]

    medium_kw = [
        # English
        "2 month", "3 month", "2-3", "1-3 months", "few months",

        # Hindi
        "do mahine", "teen mahine", "2 se 3", "1 se 3",
        "दो महीने", "तीन महीने", "दो-तीन",

        # Odia
        "ଦୁଇ ମାସ", "ତିନି ମାସ", "1-3 ମାସ", "କିଛି ମାସ",

        # Telugu
        "రెండు నెలలు", "మూడు నెలలు", "2-3 నెలలు", "కొన్ని నెలలు", "ఒకటి రెండు నెలలు", 
        "రెండు మూడు నెలలు", "టైం పడుతుంది", "మూడు నెలల లోపు", "రెండు నెలల లోపు"
    ]

    enquiry_kw = [
        # English
        "enquiry", "planning", "future", "later", "not now", "just checking",

        # Hindi
        "soch", "baad mein", "dekhenge", "sirf", "पूछताछ", "बाद में",

        # Odia
        "ପରେ", "ଭବିଷ୍ୟତ", "ଚିନ୍ତା", "ଦେଖିବା", "ଏବେ ନୁହେଁ", "କେବଳ ପଚାରୁଛି",

        # Telugu
        "తర్వాత", "భవిష్యత్", "చూద్దాం", "ఇప్పుడే కాదు", "కేవలం అడుగుతున్నాను", 
        "కేవలం సమాచారం", "సమాచారం కోసం", "కనుక్కుంటున్నాను", "ఇంకా ఆలోచించలేదు", 
        "ప్రస్తుతానికి వద్దు", "వివరాలు తెలుసుకుందామని", "ఇన్ఫర్మేషన్ కోసం"
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

    # Handle ranges like "2-3 months"
    range_match = re.findall(r'(\d+)\s*[-to]+\s*(\d+)', text_low)
    if range_match:
        nums = [int(n) for pair in range_match for n in pair]
        avg = sum(nums) // len(nums)
        if avg <= 1:
            scores["1month"] += 2
        elif avg <= 3:
            scores["1to3months"] += 2

    # Detect single number only if context exists
    if any(x in text_low for x in ["month", "mahine", "ମାସ", "నెల"]):
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
User answered solar installation timeline (English/Hindi/Odia/Telugu): "{text}"

Classify:
1MONTH = within 1 month
1TO3MONTHS = within 1–3 months
ENQUIRY = just enquiry / later / not now

CRITICAL RULE: If the user is asking a question (like asking about cost, space, battery, or technical details), you MUST reply with UNCLEAR.

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
        "ପୁରା", "ଏକଥରେ", "ନକଦ", "ସମ୍ପୂର୍ଣ୍ଣ",

        # Telugu
        "పూర్తి", "ఒకేసారి", "నగదు", "ఫుల్", "క్యాష్", "మొత్తం ఒకేసారి", 
        "మొత్తం కట్టేస్తాం", "లమ్ సమ్", "లంసంగా", "ఫుల్ పేమెంట్", "చేతి డబ్బులు", "అప్పు వద్దు"
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
        "లోన్", "ఈఎంఐ", "బ్యాంక్", "కిస్తీ", "ఫైనాన్స్", "లోన్ ద్వారా", 
        "ఇయంఐ", "ఈయమ్ఐ", "లోను", "అప్పు చేసి", "బ్యాంక్ లోన్", "నెల నెలా"
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





def _retry_or_end(session_id, state, user_text=""):
    """100% Static Fallback: Re-asks the state question without AI latency."""
    retries = sessions[session_id].get("retries", 0) + 1
    sessions[session_id]["retries"] = retries
    
    # If they fail too many times, drop the call politely
    if retries >= MAX_RETRIES:
        sessions[session_id]["state"] = "ENDED"
        sessions[session_id]["retries"] = 0
        return END_MISUNDERSTAND
        
    question_to_reask = RETRY_QUESTIONS.get(state, "")
    return RETRY_PREFIX + question_to_reask


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
    if sessions[session_id]["state"] in ("STATE_6", "ENDED"):
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

    # 🚀 FIX: UNPACK DYNAMIC LISTS TO PREVENT CRASH
    if isinstance(bot_reply, list):
        # We ignore the filler audio here because the local wrapper 
        # only expects a single final audio path to play.
        dynamic_text = bot_reply[1]
        
        audio_path = f"static/reply_{session_id}.wav"
        text_to_speech_te(dynamic_text, audio_path)
        
        return {
            "text": dynamic_text,  # Return actual string, not the list
            "audio_path": audio_path,
            "end": False
        }

    # ── STATIC LOGIC ─────────────────────────────
    
    # 🚨 IF THIS RESPONSE ENDS CALL → MARK IT
    if bot_reply in (STATE_6_CLOSING, STATE_DISCONNECT, STATE_6_FINAL):
        sessions[session_id]["state"] = "ENDED"

    # ── AUDIO HANDLING ───────────────────────────
    if bot_reply in PRE_RECORDED_AUDIO:
        audio_path = PRE_RECORDED_AUDIO[bot_reply]
    else:
        audio_path = f"static/reply_{session_id}.wav"
        text_to_speech_te(bot_reply, audio_path)

    return {
        "text": bot_reply,
        "audio_path": audio_path,
        "end": sessions[session_id]["state"] == "ENDED"
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
    "STATE_1": "Hello! I am Dipti speaking from Mierae Solar. By installing solar at your house, you can get a government subsidy of up to 78 thousand rupees, and save your electricity bill up to four thousand rupees every month. Would you like to take free information about solar?",
    "STATE_2": "Very good! Firstly tell me, what type of property do you have? Is it an independent house, apartment, or commercial property?",
    "STATE_3": "What is your average monthly electricity bill? Is it between one thousand and two thousand, between two thousand and five thousand, or more than five thousand?",
    "STATE_4": "When do you want to get the solar installation done? Within one month, within one to three months, or are you just inquiring right now?",
    "STATE_5": "How would you prefer to make the payment? Full payment, or bank loan?",
    "STATE_6": "Thank you! Your details have been successfully received. Our team will contact you shortly and schedule a free home visit. During this visit, our expert engineer will inspect your property and suggest the best solar solution. Thank you for choosing Mierae Solar. Have a great day",
}


def is_bot_or_voicemail(session_id, current_text):
    """
    Tracks text cumulatively across the session greeting to aggressively
    kill bots trying to stream long paragraphs in short audio bursts.
    """
    if not current_text:
        return False

    text_low = current_text.lower().strip()
    
    # 1. Immediate Network & Bot Keywords Filter
    bot_keywords = [
        "switched off", "unavailable", "not reachable", "out of coverage", "voicemail",
        "busy", "try again later", "number you are calling", "leave a message", "after the tone",
        "beep", "please wait", "dialed", "automated", "virtual assistant", "recording",
        "welcome to", "press 1", "press 2", "press one", "press two", "customer care",
        "main menu", "assist you", "how may i help", "toll free",

        # 🚀 THE NEW TRUECALLER / GATEKEEPER KILLERS
        "record your name", "reason for calling", "person is available", 
        "why you are calling", "who is calling", "truecaller", "google assistant",

        "ట్రూకాలర్", "ట్రూ కాలర్", "రికార్డ్", "రీజన్", "స్క్రీనింగ్", "అసిస్టెంట్",
        "కాలింగ్", "యువర్ నేమ్", "రీజన్ ఫర్",

        
        "sari aindi kadu", 
        "invalid number", "wrong number", "check the number",
        
        # Telugu IVRs, Gatekeepers & Wrong Numbers
        "స్విచ్ ఆఫ్", "అందుబాటులో లేదు", "కవరేజ్", "ఏరియా", "డయల్ చేసిన నంబర్", 
        "నెట్‌వర్క్", "బిజీగా", "ప్రయత్నించండి", "బీప్", "మెసేజ్", "దయచేసి వేచి ఉండండి",
        "సంప్రదించలేకపోతున్నాము", "లైన్ బిజీగా ఉంది", "స్వాగతం", "నొక్కండి", "కస్టమర్ కేర్", 
        "సహాయం", "ప్రెస్ చేయండి", "కారణం చెప్పండి", "ఎవరు మాట్లాడుతున్నారు",
        "సరైనది కాదు", "సరి అయింది కాదు", "సరియైనది కాదు", "సరిచూసుకోండి", 
        "తప్పు నంబర్", "ఉనికిలో లేదు"

        # ── Secretary / receptionist IVR (from live call logs) ──
        "record your name", "record you name", "reason for calling",
        "name and reason", "this person is available", "person is available",
        "wait as we connect", "wait as we try", "connecting you",
        "transferring your call", "transfer your call", "please hold",
        "hold the line", "one moment please", "connecting to",
        "will see if this person", "check if this person",
        # ── Telugu equivalents ──
        "పేరు చెప్పండి", "కారణం చెప్పండి", "కనెక్ట్ చేస్తున్నాము",
        "వేచి ఉండండి", "ట్రాన్స్ఫర్", "హోల్డ్", "కనెక్ట్ అవుతున్నాము", "చెక్ చేస్తున్నాము", "ఈ వ్యక్తి అందుబాటులో ఉన్నారా"
    ]
    
    if any(kw in text_low for kw in bot_keywords):
        return True

    # 2. Cumulative Text Accumulator Strategy
    if session_id in sessions:
        # Initialize an ongoing speech history buffer
        if "bot_detect_buffer" not in sessions[session_id]:
            sessions[session_id]["bot_detect_buffer"] = ""
            
        # Append the new fragment to our session memory
        sessions[session_id]["bot_detect_buffer"] += " " + text_low
        combined_text = sessions[session_id]["bot_detect_buffer"].strip()
        
        total_words = len(combined_text.split())
        print(f"[Bot Memory Check] Session cumulative word count: {total_words} | Text so far: '{combined_text}'")
        
        # If they speak more than 5 words before we even start, it's a bot/IVR
        if total_words > 5:
            return True
            
    return False

def ask_instant_ai(session_id, user_text=None, is_start=False):
    # ── Initialize New Session ──
    if session_id not in sessions:
        sessions[session_id] = {
            "state": "STATE_0_INIT", # 🚀 Start in listening mode
            "retries": 0,
            "data": {},
            "turn": 0,
            "bot_detect_buffer": ""
        }

    state = sessions[session_id]["state"]
    user_text_safe = str(user_text or "").strip()
    user_text_low = user_text_safe.lower()

    # ── 100% STATIC GLOBAL LOCATION INTERCEPTOR ──
    location_keywords = ["ఎక్కడ", "office", "address", "location", "ఆఫీస్", "అడ్రస్", "where"]
    if any(kw in user_text_low for kw in location_keywords):
        print(f"[Static Intercept] Catching location question in {state}!")
        sessions[session_id]["retries"] = 0 
        question_to_reask = RETRY_QUESTIONS.get(state, "")
        return [STATE_LOCATION, RETRY_PREFIX + question_to_reask]

    # ── HELPERS ──
    def _translate_to_english(text: str) -> str:
        if not text or not text.strip(): return text
        try:
            resp = requests.post(
                "https://api.sarvam.ai/translate",
                json={
                    "input": text, "source_language_code": "auto", "target_language_code": "en-IN",
                    "speaker_gender": "Female", "mode": "formal", "model": "mayura:v1", "enable_preprocessing": False,
                },
                headers={"api-subscription-key": "sk_1egy7shz_foVYeKo9OrfrtR454ZagxTyw", "Content-Type": "application/json"},
                timeout=8,
            )
            if resp.ok:
                translated = resp.json().get("translated_text", "").strip()
                if translated: return translated
        except: pass
        return text

    def _log_exchange(answer: str):
        def _background_task():
            turn = sessions[session_id]["turn"] + 1
            sessions[session_id]["turn"] = turn
            question_text = _STATE_QUESTION_MAP_EN.get(state, state)
            translated_answer = _translate_to_english(answer)
            db.add_exchange(session_id, question_text, translated_answer, state, turn)
        threading.Thread(target=_background_task).start()

    def _finish_call(status="completed"):
        lead = sessions[session_id].get("data", {})
        db.complete_call(session_id, lead_data=lead, status=status)


    # ── 🚀 STATE 0: THE INITIAL LISTEN PHASE ──
    if state == "STATE_0_INIT":
        
        # 1. Handle No Speech / 2.5s Silence Timeout
        if not user_text_safe:
            print("[STATE_0] Silence detected. Moving to greeting.")
            sessions[session_id]["state"] = "STATE_1"
            return STATE_1_GREETING
            
        # 2. Safe Human Whitelist
        human_greetings = [
            "hello", "హలో", "evaru", "ఎవరు", "చెప్పండి", "cheppandi", 
            "namaste", "నమస్తే", "అవును", "avunu", "మాట్లాడేది", "హలో హలో", "ఎవరు మాట్లాడేది"
        ]
        
        if any(word in user_text_low for word in human_greetings):
            print(f"[STATE_0] Human greeting '{user_text_safe}' detected. Moving to greeting.")
            sessions[session_id]["state"] = "STATE_1"
            return STATE_1_GREETING

        # 3. Bot & Word Count Detection (Max 4 words allowed for humans picking up)
        word_count = len(user_text_low.split())
        if word_count > 4 or is_bot_or_voicemail(session_id, user_text_safe):
            print("\n🚨 [BOT DETECTION] Call disconnected! Opposite side spoke a long IVR message immediately. 🚨")
            print(f"   Detected Text: '{user_text_safe}'\n")
            sessions[session_id]["state"] = "ENDED"
            _finish_call(status="voicemail_or_bot") 
            return STATE_DISCONNECT
            
        # 4. 🚀 IGNORING BACKGROUND NOISE (The Fix)
        # If it's a short word like 'అవైలబుల్' but NOT in the greeting whitelist, 
        # do NOT change the state. Return an empty string so the bot stays quiet.
        print(f"[STATE_0] Ignored background noise / non-greeting: '{user_text_safe}'. Still listening...")
        return ""


    # ── STATE_1: Opening ──
    elif state == "STATE_1":

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


    # ── STATE_2: Property Type ──
    elif state == "STATE_2":
        prop = _detect_property_type(user_text_low)
        if prop is None:
            return _retry_or_end(session_id, "STATE_2", user_text_safe)
        _log_exchange(user_text_safe)
        sessions[session_id]["data"]["property_type"] = prop
        sessions[session_id]["retries"] = 0
        sessions[session_id]["state"] = "STATE_3"
        return STATE_3_BILL


    # ── STATE_3: Monthly Bill Range ──
    elif state == "STATE_3":
        bill = _detect_bill_range(user_text_low)
        if bill is None:
            return _retry_or_end(session_id, "STATE_3", user_text_safe)
        _log_exchange(user_text_safe)
        sessions[session_id]["data"]["bill_range"] = bill
        sessions[session_id]["retries"] = 0
        sessions[session_id]["state"] = "STATE_4"
        if bill == "very_low":
            return STATE_3_LOW_BILL_CONTINUE
        return STATE_4_TIMELINE


    # ── STATE_4: Timeline ──
    elif state == "STATE_4":
        timeline = _detect_timeline(user_text_low)
        if timeline is None:
            return _retry_or_end(session_id, "STATE_4", user_text_safe)
        _log_exchange(user_text_safe)
        sessions[session_id]["data"]["timeline"] = timeline
        if timeline == "enquiry":
            sessions[session_id]["state"] = "ENDED"
            _finish_call(status="enquiry_only")
            return STATE_4_ENQUIRY_END
        sessions[session_id]["retries"] = 0
        sessions[session_id]["state"] = "STATE_5"
        return STATE_5_PAYMENT


    # ── STATE_5: Payment Preference ──
    elif state == "STATE_5":
        payment = _detect_payment(user_text_low)
        if payment is None:
            return _retry_or_end(session_id, "STATE_5", user_text_safe)
        _log_exchange(user_text_safe)
        sessions[session_id]["data"]["payment"] = payment
        sessions[session_id]["retries"] = 0
        _finish_call(status="completed")
        sessions[session_id]["state"] = "ENDED"
        return STATE_6_FINAL


    # ── STATE_6: Closing ──
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

        # 🚀 UPGRADED STT: Sarvam AI with Google Fallback
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
            "audio_url": "",
            "tokens": gemini_tokens
        })

    # Reset no-speech counter on successful detection
    sessions[session_id]["no_speech"] = 0

    bot_reply = ask_instant_ai(session_id, user_text=user_text)
    
    # 🚀 FIXED: Wrapped in str() to prevent slicing errors if bot_reply is a list
    print(f"[Session {session_id}] Bot Reply: {str(bot_reply)[:60]}...")

    # 🚀 UPGRADED: Handle Dynamic Generative Lists [Filler, DynamicText]
    if isinstance(bot_reply, list):
        filler_key = bot_reply[0]
        dynamic_text = bot_reply[1]
        
        # 1. Grab the instant filler audio to play immediately
        filler_url = f"/{PRE_RECORDED_AUDIO[filler_key]}"
        
        # 2. Generate the slow dynamic audio in the background
        bot_audio_path = f"static/reply_{session_id}.wav"
        text_to_speech_te(dynamic_text, bot_audio_path)
        audio_url = f"/{bot_audio_path}"
        
        return jsonify({
            "text": user_text,
            "answer": dynamic_text,
            "audio_url": audio_url,
            "filler_url": filler_url, # Pass filler to telephony server
            "tokens": gemini_tokens
        })

    # ── EXISTING STATIC LOGIC ──
    elif bot_reply in PRE_RECORDED_AUDIO:
        audio_url = f"/{PRE_RECORDED_AUDIO[bot_reply]}"
    else:
        bot_audio_path = f"static/reply_{session_id}.wav"
        text_to_speech_te(bot_reply, bot_audio_path)
        audio_url = f"/{bot_audio_path}"

    return jsonify({
        "text": user_text,
        "answer": bot_reply,
        "audio_url": audio_url,
        "tokens": gemini_tokens
    })

if __name__ == "__main__":
    app.run(debug=True, port=8080)