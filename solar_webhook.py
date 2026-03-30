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

sarvam_client = SarvamAI(
    api_subscription_key="sk_f4m68vei_79Gq5UPYq1dKawQeu49o0sdS",
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

# State mapping for INSTANT rule-based engine
sessions = {}

STATE_1_GREETING = "नमस्ते! मैं Mierae Solar की तरफ़ से बोल रही हूँ। हम एक सरकारी-मान्यता प्राप्त सोलर कंपनी हैं। क्या आप जानते हैं कि घर पर सोलर लगवाने पर सरकार 78 हज़ार रुपये तक की सब्सिडी दे रही है? क्या मैं आपको इसका विवरण सिर्फ़ दो मिनट में समझा दूँ?"
STATE_1_GREETING_PART1 = "नमस्ते! मैं Mierae Solar की तरफ़ से बोल रही हूँ।"
STATE_1_GREETING_PART2 = "हम एक सरकारी-मान्यता प्राप्त सोलर कंपनी हैं। क्या आप जानते हैं कि घर पर सोलर लगवाने पर सरकार 78 हज़ार रुपये तक की सब्सिडी दे रही है? क्या मैं आपको इसका विवरण सिर्फ़ दो मिनट में समझा दूँ?"
STATE_2_OWN_HOUSE = "क्या जिस घर में आप सोलर लगवाना चाहते हैं वह आपका अपना है?"
STATE_2_NO_END = "पच्चीस लाख से ज़्यादा परिवार सब्सिडी ले चुके हैं और ज़ीरो बिजली बिल दे रहे हैं। अगर आप कभी सोलर लगवाना चाहें तो इसी नंबर पर कॉल करें। Thank you for your time. Have a great day."
STATE_3_ELEC = "क्या आपके घर में बिजली का कनेक्शन है?"
STATE_3_NO_REF = "कोई बात नहीं! आप किसी ऐसे व्यक्ति को रेफ़र कर सकते हैं जिनका खुद का घर है और जिनका बिजली बिल अधिक आता है। हर रेफ़रल पर आपको 5 हज़ार रुपये सीधे आपके बैंक खाते में मिलेंगे। क्या रेफ़रल प्रोग्राम समझाने के लिए मैं हमारी टीम का एक कॉल-बैक बुक कर दूँ?"
STATE_4_BILL = "आपका औसत मासिक बिजली बिल कितना आता है?"
STATE_5_CALLBACK = "बधाई हो! आप 78 हज़ार रुपये तक की सब्सिडी और तीस साल तक की मुफ़्त बिजली के लिए पात्र हैं। आवेदन आगे बढ़ाने के लिए क्या मैं आपके लिए हमारे सोलर एक्सपर्ट का एक कॉल-बैक अरेंज कर दूँ?"
STATE_5_ZERO = "आप फ़िर भी अपने घर में सोलर लगवाकर 78 हज़ार रुपये तक की सब्सिडी सीधे अपने बैंक खाते में प्राप्त कर सकते हैं। आवेदन आगे बढ़ाने के लिए क्या मैं आपके लिए हमारे सोलर एक्सपर्ट का एक कॉल-बैक अरेंज कर दूँ?"
STATE_6_DATE = "आप हमारे सोलर एक्सपर्ट का कॉल-बैक कब अटेंड करना चाहेंगे?"
STATE_6_NO_END = "Mierae Solar सोलर इंस्टॉलेशन के लिए A से Z तक की पूरी जिम्मेदारी लेता है। Thank you for your time. Have a great day."
STATE_6B_REASK = "कृपया पूरी तारीख़ बताएं — कौन सा महीना, कौन सी तारीख़, और कौन सा समय, जैसे 15 मार्च दोपहर 2 बजे या कल सुबह 10 बजे।"
STATE_6B_REASK_TIME = "वो समय सही नहीं है। कृपया सुबह 8 बजे से रात 9 बजे के बीच का समय चुनें, जैसे कल सुबह 10 बजे या शाम 5 बजे।"
STATE_7_TIME = "क्या कोई विशेष समय पसंद है?"
STATE_8_HOME = "हमने कॉल-बैक शेड्यूल कर दिया है। अगर आप चाहें तो हमारी एक फ्री होम विज़िट भी बुक कर सकते हैं, जहाँ इंजीनियर आपको सब समझाएँगे। क्या आप फ्री होम विज़िट बुक करना चाहेंगे?"
STATE_9_ADDR = "कृपया वह पता बताएं जहाँ आप सोलर लगवाना चाहते हैं।"
STATE_9_NO_END = "ठीक है, Thank you for choosing Mierae Solar. Have a nice day."
STATE_10_HDATE = "हमारे सोलर इंजीनियर को आपके घर कब भेजें?"
STATE_10B_REASK = "कृपया पूरी तारीख़ बताएं — कौन सा महीना, कौन सी तारीख़, और कौन सा समय, जैसे 15 मार्च दोपहर 2 बजे या कल सुबह 10 बजे।"
STATE_10B_REASK_TIME = "वो समय सही नहीं है। कृपया सुबह 8 बजे से रात 9 बजे के बीच का समय चुनें, जैसे कल सुबह 10 बजे या शाम 5 बजे।"
STATE_11_HTIME = "क्या कोई विशेष समय पसंद है?"
STATE_12_END = "हमने आपकी होम विज़िट बुक कर दी है। हमारे सोलर इंजीनियर आपके घर आने से तीस मिनट पहले आपको कॉल करेंगे। क्या आपको कोई और सवाल है? अगर नहीं, तो मैं कॉल डिस्कनेक्ट कर रहा हूँ। Thank you for choosing Mierae Solar. Have a nice day."
STATE_13_DISCONNECT = "धन्यवाद। कॉल समाप्त हो चुकी है। Thank you!"

# Pre-recorded audio mapping: state response text → audio file path
# Generated via generate_pre_audio.py using Sarvam AI TTS (bulbul:v3)
PRE_RECORDED_AUDIO = {
    STATE_1_GREETING: "static/pre_audio/STATE_1_GREETING.wav",
    STATE_1_GREETING_PART1: "static/pre_audio/STATE_1_GREETING_PART1.wav",
    STATE_1_GREETING_PART2: "static/pre_audio/STATE_1_GREETING_PART2.wav",
    STATE_2_OWN_HOUSE: "static/pre_audio/STATE_2_OWN_HOUSE.wav",
    STATE_2_NO_END: "static/pre_audio/STATE_2_NO_END.wav",
    STATE_3_ELEC: "static/pre_audio/STATE_3_ELEC.wav",
    STATE_3_NO_REF: "static/pre_audio/STATE_3_NO_REF.wav",
    STATE_4_BILL: "static/pre_audio/STATE_4_BILL.wav",
    STATE_5_CALLBACK: "static/pre_audio/STATE_5_CALLBACK.wav",
    STATE_5_ZERO: "static/pre_audio/STATE_5_ZERO.wav",
    STATE_6_DATE: "static/pre_audio/STATE_6_DATE.wav",
    STATE_6_NO_END: "static/pre_audio/STATE_6_NO_END.wav",
    STATE_7_TIME: "static/pre_audio/STATE_7_TIME.wav",
    STATE_8_HOME: "static/pre_audio/STATE_8_HOME.wav",
    STATE_9_ADDR: "static/pre_audio/STATE_9_ADDR.wav",
    STATE_9_NO_END: "static/pre_audio/STATE_9_NO_END.wav",
    STATE_10_HDATE: "static/pre_audio/STATE_10_HDATE.wav",
    STATE_11_HTIME: "static/pre_audio/STATE_11_HTIME.wav",
    STATE_12_END: "static/pre_audio/STATE_12_END.wav",
    STATE_13_DISCONNECT: "static/pre_audio/STATE_13_DISCONNECT.wav",
}

# Retry system constants
MAX_RETRIES = 3
MAX_NO_SPEECH = 3  # Max consecutive "no speech detected" before ending call
RETRY_PREFIX = "मुझे लगता है आपकी बात सही से समझ नहीं आई। "
END_MISUNDERSTAND = "कोई बात नहीं। अगर आप बाद में बात करना चाहें तो कृपया हमें 9070607050 पर कॉल करें। Thank you! Have a nice day."
NO_SPEECH_END = "लगता है आपकी आवाज़ नहीं आ पा रही है। कृपया बाद में हमें 9070607050 पर कॉल करें। Thank you! Have a nice day."

# Short re-ask questions for retry (not the full long message)
RETRY_QUESTIONS = {
    "STATE_1": "क्या मैं आपको सोलर सब्सिडी के बारे में बता सकती हूँ?",
    "STATE_2": "क्या यह घर आपका अपना है?",
    "STATE_3": "क्या आपके घर में बिजली का कनेक्शन है?",
    "STATE_4": "आपका मासिक बिजली बिल कितना आता है?",
    "STATE_5": "क्या मैं आपके लिए कॉल-बैक अरेंज कर दूँ?",
    "STATE_6": "आप कॉल-बैक कब चाहेंगे?",
    "STATE_6B": "कृपया सही तारीख़ और सुबह 8 से रात 9 बजे के बीच का समय बताएं।",
    "STATE_7": "कौन सा समय अच्छा रहेगा?",
    "STATE_8": "क्या आप फ्री होम विज़िट बुक करना चाहेंगे?",
    "STATE_9": "कृपया अपना पता बताएं।",
    "STATE_10": "सोलर इंजीनियर को कब भेजें?",
    "STATE_10B": "कृपया सही तारीख़ और सुबह 8 से रात 9 बजे के बीच का समय बताएं।",
    "STATE_11": "कौन सा समय अच्छा रहेगा?",
}

def is_positive(text):
    text = text.lower()
    
    # Fast keyword check first (0 tokens)
    negatives_exact = {"no", "nahi", "na", "mat", "busy", "rakho", "नहीं", "ना", "मत", "बिजी"}
    negatives_substring = ["not interested", "bad me", "रहने दो", "बंद करो", "zarurat nahi", "ज़रूरत नहीं"]
    positives_exact = {
        # Direct yes
        "yes", "haa", "ha", "ji", "haan", "ok", "okay", "sure", "theek", "bilkul",
        "हाँ", "हां", "जी", "ठीक", "बिल्कुल", "चलो", "सही",
        # Agreement through request verbs ("samjha do" = "yes, explain")
        "samjha", "samjhao", "batao", "bataiye", "bolo", "boliye",
        "sunao", "karo", "kariye", "kar", "do", "dijiye", "de",
        "chalo", "chaliye", "zaroor", "jaroor", "please",
        # Hindi request/agreement verbs
        "समझा", "समझाओ", "बताओ", "बताइए", "बोलो", "बोलिए",
        "सुनाओ", "करो", "करिए", "दो", "दीजिए", "दे",
        "चलिए", "ज़रूर", "जरूर", "लगवाना", "चाहिए", "चाहते",
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
    
    # Ambiguous or no clear signal → ask Gemini (~20 tokens)
    result = _gemini_yes_no(f"The bot asked a yes/no question. Is this user reply expressing agreement, willingness, or requesting to proceed? Note: requests like 'explain', 'tell me', 'do it' mean YES. Reply only YES or NO: {text}")
    if result is not None:
        return result
    
    # Default: assume agreement
    return True

def extract_bill_amount(text):
    text = text.lower()

    # Normalize comma-formatted numbers like "5,000" → "5000" before extracting digits
    text_no_commas = re.sub(r'(\d),(\d)', r'\1\2', text)
    text_no_commas = re.sub(r'(\d),(\d)', r'\1\2', text_no_commas)  # Handle triple groups e.g. 1,00,000

    matches = re.findall(r'\d+', text_no_commas)
    if matches:
        return int(matches[0])
        
    if "डेढ़ सौ" in text or "dedh sau" in text: return 150
    if "ढाई सौ" in text or "dhai sau" in text: return 250
    
    if "सौ" in text or "sau" in text or "so " in text:
        for p, v in [("एक",100), ("ek",100), ("दो",200), ("do",200), ("तीन",300), ("teen",300), ("चार",400), ("char",400), ("पांच",500), ("paanch",500), ("panch",500), ("छह",600), ("che",600), ("chhe",600), ("सात",700), ("saat",700), ("आठ",800), ("aath",800), ("नौ",900), ("nau",900)]:
            if p in text: return v
        return 100
        
    if "हजार" in text or "hazar" in text or "hazaar" in text: return 1000
    if "पचास" in text or "pachas" in text: return 50
    
    zero_words = ["0", "zero", "ज़ीरो", "शून्य", "कुछ नहीं", "kuch nahi", "bilkul nahi", "फ्री", "मुफ्त"]
    for z in zero_words:
        if z in text: return 0
            
    return 999

def has_time_info(text):
    """Check if user's response already includes time information.
    Fast keywords first, then Gemini fallback for edge cases."""
    text_lower = text.lower()
    time_keywords = [
        # Immediate
        "abhi", "अभी", "turant", "तुरंत", "foran", "फौरन",
        # Time of day (Hindi)
        "subah", "सुबह", "dopahar", "दोपहर", "sham", "शाम", "raat", "रात",
        # Time of day (Hindi transliteration of English)
        "मॉर्निंग", "इवनिंग", "आफ्टरनून", "नाइट", "लंच टाइम",
        # Time of day (English)
        "morning", "evening", "afternoon", "night", "lunch",
        # Clock time
        "baje", "बजे", "o'clock", "o clock",
        # Relative time
        "ghante", "घंटे", "घण्टे", "minute", "मिनट",
        # Time periods
        "lunch", "लंच",
    ]
    for kw in time_keywords:
        if kw in text_lower:
            return True
    # Check for digit + time pattern like "5 बजे", "2 ghante"
    if re.search(r'\d+\s*(baje|बजे|ghante|घंटे|घण्टे|minute|मिनट)', text_lower):
        return True
    # Check for clock time format like "9:00", "10:30"
    if re.search(r'\d{1,2}:\d{2}', text_lower):
        return True
    
    # Keywords missed → ask Gemini (~20 tokens)
    result = _gemini_yes_no(f"Does this Hindi/Hinglish text mention a specific TIME (hour, period, immediately)? Reply only YES or NO: {text}")
    if result is not None:
        return result
    return False


def _validate_datetime(user_text):
    """Validate if the user-provided date/time is reasonable using Gemini.
    Returns: 'VALID_WITH_TIME', 'VALID_NO_TIME', 'INVALID_TIME', 'INVALID_DATE', or 'UNCLEAR'
    - VALID_WITH_TIME: both date and time are reasonable
    - VALID_NO_TIME: date is valid but no time mentioned
    - INVALID_TIME: date is fine but time is unreasonable (before 8 AM or after 9 PM)
    - INVALID_DATE: date is ambiguous (no month), in the past, or too far in future
    - UNCLEAR: couldn't determine a date at all
    """
    if not gemini_model:
        # Fallback: if no Gemini, accept anything (old behavior)
        if has_time_info(user_text):
            return "VALID_WITH_TIME"
        return "VALID_NO_TIME"
    
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    day_name = today.strftime("%A")
    
    try:
        resp = gemini_model.generate_content(
            f"""Today is {today_str} ({day_name}). A voice bot is scheduling a callback/visit. 
The user said (in Hindi/Hinglish): "{user_text}"

Analyze and reply with EXACTLY ONE of these:
- VALID_WITH_TIME: if both a CLEAR, UNAMBIGUOUS future date AND a reasonable time (8 AM to 9 PM) are mentioned
- VALID_NO_TIME: if a CLEAR, UNAMBIGUOUS future date is mentioned but NO specific time
- INVALID_TIME: if the date is fine/clear BUT the time is unreasonable (before 8 AM or after 9 PM). Examples: "kal subah 6 baje" = date is fine (kal=tomorrow) but 6 AM is too early → INVALID_TIME. "कल रात 11 बजे" = date is fine but 11 PM is too late → INVALID_TIME
- INVALID_DATE: if the date itself is problematic — ambiguous (no month specified for a bare date number), in the past, or more than 60 days away. Examples: "5 tarikh" / "5 तारीख" / "20 ko" → INVALID_DATE (which month?)
- UNCLEAR: if no recognizable date/time at all

CRITICAL rules:
- Bare date numbers without month → INVALID_DATE: "5 tarikh", "10 tarikh", "20 ko", "5 tarikh ko sham 6 baje" → all INVALID_DATE
- Unambiguous relative dates → VALID: "kal" (tomorrow), "aaj" (today), "parson" (day after), "somvar"/"monday", "is hafte", "agle hafte"
- Dates with explicit month → VALID: "15 march", "15 मार्च", "agle mahine 5 ko"
- "abhi" / "turant" = immediately → VALID_WITH_TIME
- Time between 8 AM and 9 PM (inclusive) → reasonable
- Time before 8 AM or after 9 PM → INVALID_TIME (NOT INVALID_DATE)

Reply ONLY one: VALID_WITH_TIME, VALID_NO_TIME, INVALID_TIME, INVALID_DATE, or UNCLEAR""",
            generation_config=genai.GenerationConfig(max_output_tokens=10, temperature=0)
        )
        track_tokens_usage(resp)
        answer = resp.text.strip().upper()
        print(f"[DateTime Validation] Input: '{user_text}' → Gemini: '{answer}'")
        
        if "VALID_WITH_TIME" in answer:
            return "VALID_WITH_TIME"
        if "VALID_NO_TIME" in answer:
            return "VALID_NO_TIME"
        if "INVALID_TIME" in answer:
            return "INVALID_TIME"
        if "INVALID_DATE" in answer:
            return "INVALID_DATE"
        if "INVALID" in answer:
            return "INVALID_DATE"  # generic INVALID → treat as date issue
        if "UNCLEAR" in answer:
            return "UNCLEAR"
        
        # Fallback parsing
        return "VALID_NO_TIME"
    except Exception as e:
        print(f"DateTime validation error: {e}")
        # Fallback: accept (old behavior)
        if has_time_info(user_text):
            return "VALID_WITH_TIME"
        return "VALID_NO_TIME"

def _is_relevant_answer(state, text):
    """Check if user's answer is relevant to what was asked.
    Fast keyword check first, Gemini fallback for edge cases."""
    text_lower = text.lower()
    words = text_lower.replace(".", " ").replace(",", " ").replace("।", " ").replace("?", " ").split()
    
    # Yes/No questions: keywords first, then detect off-topic questions
    if state in ("STATE_1", "STATE_2", "STATE_3", "STATE_5", "STATE_8"):
        # 1. Clear yes/no or agreement/refusal keywords → instant relevant
        yes_no_words = {
            "yes", "no", "haa", "ha", "nahi", "na", "ji", "haan", "ok", "okay",
            "sure", "theek", "bilkul", "mat", "busy", "chahiye", "chahte",
            "lagwana", "batao", "bataiye", "bolo", "samjhao", "samjha",
            "sunao", "karo", "kariye", "kar", "do", "dijiye", "zaroor",
            "chalo", "please", "rehne", "band", "nai",
            "हाँ", "हां", "नहीं", "जी", "ना", "ठीक", "बिल्कुल", "चलो", "चलिए",
            "सही", "मत", "बिजी", "बताओ", "बताइए", "समझाओ", "समझा", "सुनाओ",
            "बोलो", "करो", "करिए", "दो", "दीजिए", "ज़रूर", "जरूर",
            "लगवाना", "चाहिए", "रहने", "बंद",
        }
        if any(w in yes_no_words for w in words):
            return True
        
        # 2. Detect off-topic counter-questions (user asking bot something)
        question_indicators = {
            "कौन", "कैसे", "कैसा", "कहाँ", "कहां", "क्यों", "किसका", "किसके",
            "किसको", "कितना", "कितने", "तुम्हारा", "तुम्हारे", "तुम्हारी",
            "kaun", "kaise", "kahan", "kyon", "kiska", "tumhara", "tumhare",
        }
        # "नाम" (name) with question context = off-topic
        has_question_word = any(w in question_indicators for w in words)
        has_name_query = "नाम" in text_lower or "naam" in text_lower
        if has_question_word and has_name_query:
            return False
        if has_question_word:
            # Ask Gemini to confirm if it's off-topic
            ctx = {"STATE_1": "solar interest", "STATE_2": "house ownership",
                   "STATE_3": "electricity connection", "STATE_5": "callback",
                   "STATE_8": "home visit"}.get(state, "the question")
            result = _gemini_yes_no(f"Bot asked about {ctx}. Is this reply answering it or asking something unrelated? Reply YES if answering, NO if unrelated: {text}")
            if result is not None:
                return result
            return False  # Question words + no Gemini = likely off-topic
        
        # 3. No clear signal → Gemini decides
        result = _gemini_yes_no(f"Is this Hindi/Hinglish text a valid response to a yes/no question? Reply YES or NO: {text}")
        if result is not None:
            return result
        
        # 4. Default: assume relevant (don't block if Gemini unavailable)
        return True
    
    # Bill amount: needs a number or amount keyword
    elif state == "STATE_4":
        if re.search(r'\d+', text_lower):
            return True
        bill_words = ["सौ", "हज़ार", "हजार", "sau", "hazar", "hazaar", "पचास",
                      "pachas", "zero", "ज़ीरो", "शून्य", "रुपये", "बिल",
                      "फ्री", "मुफ्त", "kuch nahi", "bill"]
        if any(w in text_lower for w in bill_words):
            return True
    
    # Date/Time: needs date or time info
    elif state in ("STATE_6", "STATE_6B", "STATE_10", "STATE_10B"):
        date_words = [
            "kal", "कल", "parson", "परसों", "aaj", "आज", "abhi", "अभी",
            "tarikh", "तारीख", "तारीख़",
            "सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार",
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
            "next", "अगले", "इस हफ्ते",
        ]
        if any(w in text_lower for w in date_words):
            return True
        if has_time_info(text):  # Time also counts as relevant for date question
            return True
        if re.search(r'\d+', text_lower):  # Any number could be a date
            return True
    
    # Time: needs time info
    elif state in ("STATE_7", "STATE_11"):
        if has_time_info(text):
            return True
        if re.search(r'\d+', text_lower):
            return True
    
    # Address: almost anything substantial counts
    elif state == "STATE_9":
        if len(text.strip()) > 3:
            return True
    
    # Gemini fallback for edge cases (~25 tokens)
    context_map = {
        "STATE_1": "solar interest (yes/no)",
        "STATE_2": "owns house (yes/no)",
        "STATE_3": "has electricity (yes/no)",
        "STATE_4": "electricity bill amount",
        "STATE_5": "wants callback (yes/no)",
        "STATE_6": "callback date/time",
        "STATE_7": "preferred time",
        "STATE_8": "home visit (yes/no)",
        "STATE_9": "home address",
        "STATE_10": "home visit date",
        "STATE_11": "home visit time",
    }
    ctx = context_map.get(state, "the question")
    result = _gemini_yes_no(f"Bot asked about {ctx}. Is this user reply relevant/answering it? Reply YES or NO: {text}")
    if result is not None:
        return result
    
    # Default: assume relevant (don't block the user)
    return True

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

# Question context for yes/no states (used by AI to understand intent)
YES_NO_CONTEXT = {
    "STATE_1": "Should I explain solar subsidy details to you?",
    "STATE_2": "Is the house where you want solar panels your own? (family house counts as own)",
    "STATE_3": "Does your house have an electricity connection?",
    "STATE_5": "Should I arrange a callback from our solar expert?",
    "STATE_8": "Would you like to book a free home visit?",
}

def _ai_understand(question_context, user_reply):
    """Use Gemini to understand user's reply in context.
    Returns: True (yes/agree), False (no/refuse), None (irrelevant/off-topic)"""
    if not gemini_model:
        return None
    try:
        resp = gemini_model.generate_content(
            f"""Voice bot conversation in Hindi/Hinglish.
Bot asked: {question_context}
User replied: {user_reply}

Classify the reply:
- YES: user agrees, says yes, or their answer implies yes (e.g. "my father's house" = YES for "is it your own house?", "explain" = YES for "should I explain?")
- NO: user refuses, says no, or answer implies no (e.g. "rented" = NO for "own house?")
- IRRELEVANT: user asks something unrelated or doesn't answer

Reply ONLY one word: YES, NO, or IRRELEVANT""",
            generation_config=genai.GenerationConfig(max_output_tokens=5, temperature=0)
        )
        track_tokens_usage(resp)
        answer = resp.text.strip().lower()
        if "irrelevant" in answer:
            return None
        if "yes" in answer:
            return True
        if "no" in answer:
            return False
        return None
    except Exception as e:
        print(f"Gemini understand error: {e}")
        return None

def _get_yes_no_intent(state, user_text):
    """Determine user intent for yes/no questions.
    Returns: True (positive), False (negative), None (irrelevant/retry needed)"""
    text = user_text.lower()
    words = text.replace(".", " ").replace(",", " ").replace("।", " ").replace("?", " ").split()
    
    # 1. Fast keyword check (0 tokens, instant)
    negatives_exact = {"no", "nahi", "na", "mat", "busy", "rakho", "नहीं", "ना", "मत", "बिजी"}
    negatives_sub = ["not interested", "bad me", "रहने दो", "बंद करो", "zarurat nahi", "ज़रूरत नहीं"]
    positives_exact = {
        "yes", "haa", "ha", "ji", "haan", "ok", "okay", "sure", "theek", "bilkul",
        "हाँ", "हां", "जी", "ठीक", "बिल्कुल", "चलो", "सही",
        "samjha", "samjhao", "batao", "bataiye", "bolo", "boliye",
        "sunao", "karo", "kariye", "kar", "do", "dijiye", "de",
        "chalo", "chaliye", "zaroor", "jaroor", "please",
        "समझा", "समझाओ", "बताओ", "बताइए", "बोलो", "बोलिए",
        "सुनाओ", "करो", "करिए", "दो", "दीजिए", "दे",
        "चलिए", "ज़रूर", "जरूर", "लगवाना", "चाहिए", "चाहते",
    }
    
    # Negative substring phrases are always clear refusals
    for sub in negatives_sub:
        if sub in text:
            return False
    
    has_negative = any(w in negatives_exact for w in words)
    has_positive = any(w in positives_exact for w in words)
    
    # SHORT responses (1-2 words): trust keywords directly
    # e.g. "नहीं" = clear NO, "हाँ" = clear YES
    if len(words) <= 2:
        if has_negative and not has_positive:
            return False
        if has_positive and not has_negative:
            return True
    
    # LONG responses (3+ words): keywords only for clear positive (no negatives)
    # Complex sentences like "नहीं वह मेरे पापा का है तो मेरा ही हुआ ना"
    # can use "नहीं" colloquially and "ना" as tag question — AI must decide
    if len(words) > 2:
        if has_positive and not has_negative:
            return True  # Clear positive, no ambiguity
        # Any negative in a long sentence → let AI understand the nuance
    
    # 2. AI understanding with full question context
    question = YES_NO_CONTEXT.get(state, "")
    if question:
        result = _ai_understand(question, user_text)
        return result  # True=yes, False=no, None=irrelevant
    
    # 3. Default: assume positive
    return True

def ask_instant_ai(session_id, user_text=None, is_start=False):
    if session_id not in sessions:
        sessions[session_id] = {"state": "STATE_1", "retries": 0}
        
    state = sessions[session_id]["state"]
    
    if is_start:
        return STATE_1_GREETING

    user_text_safe = str(user_text).lower()

    # --- Yes/No states: use smart intent detection ---
    yes_no_states = {"STATE_1", "STATE_2", "STATE_3", "STATE_5", "STATE_8"}
    if state in yes_no_states:
        intent = _get_yes_no_intent(state, user_text_safe)
        
        if intent is None:  # Irrelevant/off-topic → retry
            return _retry_or_end(session_id, state)
        
        sessions[session_id]["retries"] = 0  # Valid answer, reset retries
        
        if state == "STATE_1":
            if intent:
                sessions[session_id]["state"] = "STATE_2"
                return STATE_2_OWN_HOUSE
            else:
                sessions[session_id]["state"] = "ENDED"
                return STATE_2_NO_END
        elif state == "STATE_2":
            if intent:
                sessions[session_id]["state"] = "STATE_3"
                return STATE_3_ELEC
            else:
                sessions[session_id]["state"] = "STATE_5"
                return STATE_3_NO_REF
        elif state == "STATE_3":
            if intent:
                sessions[session_id]["state"] = "STATE_4"
                return STATE_4_BILL
            else:
                sessions[session_id]["state"] = "STATE_5"
                return STATE_3_NO_REF
        elif state == "STATE_5":
            if intent:
                sessions[session_id]["state"] = "STATE_6"
                return STATE_6_DATE
            else:
                sessions[session_id]["state"] = "ENDED"
                return STATE_6_NO_END
        elif state == "STATE_8":
            if intent:
                sessions[session_id]["state"] = "STATE_9"
                return STATE_9_ADDR
            else:
                sessions[session_id]["state"] = "ENDED"
                return STATE_9_NO_END

    # --- Data states: check relevance, then process ---
    if state not in ("ENDED", "STATE_12") and state not in yes_no_states:
        if not _is_relevant_answer(state, user_text_safe):
            return _retry_or_end(session_id, state)
        sessions[session_id]["retries"] = 0

    if state == "STATE_4":
        sessions[session_id]["state"] = "STATE_5"
        bill_amount = extract_bill_amount(user_text_safe)
        if bill_amount < 500:
            return STATE_5_ZERO
        return STATE_5_CALLBACK
        
    elif state == "STATE_6":
        validation = _validate_datetime(user_text_safe)
        print(f"[Session {session_id}] STATE_6 datetime validation: {validation}")
        if validation == "INVALID_TIME":
            sessions[session_id]["state"] = "STATE_6B"
            return STATE_6B_REASK_TIME
        elif validation in ("INVALID_DATE", "UNCLEAR"):
            sessions[session_id]["state"] = "STATE_6B"
            return STATE_6B_REASK
        elif validation == "VALID_WITH_TIME":
            sessions[session_id]["state"] = "STATE_8"
            return STATE_8_HOME
        else:  # VALID_NO_TIME
            sessions[session_id]["state"] = "STATE_7"
            return STATE_7_TIME
    
    elif state == "STATE_6B":
        # User is re-providing date/time after invalid attempt
        validation = _validate_datetime(user_text_safe)
        print(f"[Session {session_id}] STATE_6B datetime validation: {validation}")
        if validation == "INVALID_TIME":
            return _retry_or_end(session_id, state)
        elif validation in ("INVALID_DATE", "UNCLEAR"):
            return _retry_or_end(session_id, state)
        elif validation == "VALID_WITH_TIME":
            sessions[session_id]["state"] = "STATE_8"
            return STATE_8_HOME
        else:  # VALID_NO_TIME
            sessions[session_id]["state"] = "STATE_7"
            return STATE_7_TIME
        
    elif state == "STATE_7":
        sessions[session_id]["state"] = "STATE_8"
        return STATE_8_HOME
        
    elif state == "STATE_9":
        sessions[session_id]["state"] = "STATE_10"
        return STATE_10_HDATE
        
    elif state == "STATE_10":
        validation = _validate_datetime(user_text_safe)
        print(f"[Session {session_id}] STATE_10 datetime validation: {validation}")
        if validation == "INVALID_TIME":
            sessions[session_id]["state"] = "STATE_10B"
            return STATE_10B_REASK_TIME
        elif validation in ("INVALID_DATE", "UNCLEAR"):
            sessions[session_id]["state"] = "STATE_10B"
            return STATE_10B_REASK
        elif validation == "VALID_WITH_TIME":
            sessions[session_id]["state"] = "STATE_12"
            return STATE_12_END
        else:  # VALID_NO_TIME
            sessions[session_id]["state"] = "STATE_11"
            return STATE_11_HTIME
    
    elif state == "STATE_10B":
        validation = _validate_datetime(user_text_safe)
        print(f"[Session {session_id}] STATE_10B datetime validation: {validation}")
        if validation in ("INVALID_TIME", "INVALID_DATE", "UNCLEAR"):
            return _retry_or_end(session_id, state)
        elif validation == "VALID_WITH_TIME":
            sessions[session_id]["state"] = "STATE_12"
            return STATE_12_END
        else:  # VALID_NO_TIME
            sessions[session_id]["state"] = "STATE_11"
            return STATE_11_HTIME
        
    elif state == "STATE_11":
        sessions[session_id]["state"] = "STATE_12"
        return STATE_12_END
        
    elif state == "STATE_12" or state == "ENDED":
        sessions[session_id]["state"] = "ENDED"
        return STATE_13_DISCONNECT
        
    return STATE_1_GREETING

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

def _humanize_text(text):
    """Preprocess Hindi text for friendly, calm, consultant-like delivery.
    Adds varied natural pauses — longer after statements (gathering next point),
    softer after questions (inviting listener to respond)."""
    t = text
    # Calm pause after Hindi full stop — like a consultant pausing before next point
    t = t.replace("।", "।,  ")
    # Softer, inviting pause after questions — giving listener space to think
    t = t.replace("?", "?, ")
    # Brief warm pause after exclamations — friendly energy without rushing
    t = t.replace("!", "!, ")
    # Gentle pause after English periods mid-text (e.g. "Mierae Solar. हम...")
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

@app.route("/solar_test")
def index():
    return render_template("solar_test.html")

@app.route("/start_call", methods=["POST"])
def start_call():
    session_id = str(uuid.uuid4())
    bot_reply = ask_instant_ai(session_id, is_start=True)
    
    # Use pre-recorded audio if available, otherwise generate TTS
    if bot_reply in PRE_RECORDED_AUDIO:
        audio_url = f"/{PRE_RECORDED_AUDIO[bot_reply]}"
    else:
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
    # 1. Transcribe audio using Google Cloud Speech Recognition (Instant + Flawless Hindi)
    try:
        wav_path = f"static/temp_{session_id}.wav"
        # Convert webm to PCM wav format
        ffmpeg_result = subprocess.run(
            ["ffmpeg", "-y", "-i", user_audio_path, "-ac", "1", "-ar", "16000", wav_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
        if ffmpeg_result.returncode != 0:
            print(f"[Session {session_id}] ffmpeg conversion failed: {ffmpeg_result.stderr.decode('utf-8', errors='ignore')[-200:]}")
            raise Exception("ffmpeg conversion failed")
        
        # Check if wav file was created and has content
        if not os.path.exists(wav_path):
            print(f"[Session {session_id}] WAV file not created after ffmpeg")
            raise Exception("WAV file not created")
        
        wav_size = os.path.getsize(wav_path)
        webm_size = os.path.getsize(user_audio_path) if os.path.exists(user_audio_path) else 0
        print(f"[Session {session_id}] Audio sizes - WebM: {webm_size}B, WAV: {wav_size}B")
        
        if wav_size < 5000:  # Less than 5KB = likely silence or too short
            print(f"[Session {session_id}] WAV file too small ({wav_size}B), likely silence")
            raise Exception("Audio too short or silent")
        
        r = sr.Recognizer()
        r.energy_threshold = 300  # Lower threshold to catch softer speech
        with sr.AudioFile(wav_path) as source:
            audio_data = r.record(source)
        # Google's Hindi engine translates perfect Indian context instantly
        user_text = r.recognize_google(audio_data, language="hi-IN")
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
        # Track consecutive no-speech events
        no_speech_count = sessions[session_id].get("no_speech", 0) + 1
        sessions[session_id]["no_speech"] = no_speech_count
        print(f"[Session {session_id}] No speech detected ({no_speech_count}/{MAX_NO_SPEECH})")
        
        if no_speech_count >= MAX_NO_SPEECH:
            # Too many failures → end call gracefully
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

    # 2. Extract Response via blazing fast Rule-Based Dictionary Lookups (0s latency)
    bot_reply = ask_instant_ai(session_id, user_text=user_text)
    print(f"[Session {session_id}] Instant Engine Reply: {bot_reply[:30]}...")
    
    # 3. Use pre-recorded audio if available, otherwise generate TTS
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
