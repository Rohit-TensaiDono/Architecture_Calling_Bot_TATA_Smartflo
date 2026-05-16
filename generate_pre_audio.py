"""
Generate pre-recorded audio files for all bot states using Sarvam AI TTS.
Run this script once to generate all audio files in static/pre_audio/

New Flow (Mierae Solar UP Script — High-Converting Final Version):
  STATE_1_GREETING  → Opening / interest check
  STATE_1_NO_END    → User not interested — polite goodbye
  STATE_2_PROPERTY  → Property type question
  STATE_3_BILL      → Monthly bill range question
  STATE_4_TIMELINE  → Installation timeline question
  STATE_5_PAYMENT   → Payment preference question
  STATE_6_CLOSING   → Closing / thank you
  STATE_DISCONNECT  → Call disconnected
"""

from sarvamai import SarvamAI
import base64
import os

client = SarvamAI(
    api_subscription_key="sk_1egy7shz_foVYeKo9OrfrtR454ZagxTyw",
)

# All state texts to generate audio for (ODIA CONVERTED)
STATES = {
    "STATE_1_GREETING": (
        "నమస్కారం! నేను మీరై సోలార్ నుండి దీప్తి మాట్లాడుతున్నాను. "
        "మీరు మీ ఇంట్లో సోలార్ ఏర్పాటు చేసుకుని డెబ్బై ఎనిమిది వేల రూపాయలు వరకు ప్రభుత్వ సబ్సిడీ పొందవచ్చు, "
        "మరియు ప్రతి నెల నాలుగు వేల రూపాయలు వరకు విద్యుత్ బిల్లును ఆదా చేసుకోవచ్చు. "
        "మీరు సోలార్ గురించి ఉచిత సమాచారం పొందాలనుకుంటున్నారా?"
    ),
    "STATE_1_NO_END": (
        "పర్లేదు! మీరు తర్వాత సోలార్ గురించి తెలుసుకోవాలనుకుంటే, "
        "దయచేసి ఈ నంబర్‌కు కాల్ చేయండి. "
        "ధన్యవాదాలు! మీ రోజు మంచిగా గడవాలి."
    ),
    "STATE_2_PROPERTY": (
        "చాలా బాగుంది! ముందుగా చెప్పండి, మీ ప్రాపర్టీ ఏ రకం? "
        "ఇది సొంత ఇల్లు, అపార్ట్‌మెంట్ లేదా కమర్షియల్ ప్రాపర్టీనా?"

    ),
    "STATE_3_BILL": (
        "మీ నెలవారీ విద్యుత్ బిల్లు సాధారణంగా ఎంత వస్తుంది? "
        "వెయ్యి నుంచి రెండు వేల మధ్యనా, "
        "రెండు వేల నుంచి ఐదు వేల మధ్యనా, "
        "లేదా ఐదు వేల కంటే ఎక్కువనా?"
    ),

    # 🚀 NEW: Positive response for low bills + transition to timeline
    "STATE_3_LOW_BILL_CONTINUE": (
        "మీ బిల్లు తక్కువగా ఉన్నప్పటికీ, సోలార్ ప్యానెల్స్ తో మీరు ఆ బిల్లును పూర్తిగా జీరో చేసుకోవచ్చు, మరియు భవిష్యత్తులో కరెంట్ ఛార్జీల పెంపు నుండి రక్షణ పొందవచ్చు. "
        "మరి మీరు సోలార్ ఇన్‌స్టాలేషన్ ఎప్పటిలో చేయించుకోవాలని భావిస్తున్నారు? ఒక నెలలోపలనా, ఒకటి నుంచి మూడు నెలల మధ్యనా, లేదా ప్రస్తుతం కేవలం సమాచారం కోసం మాత్రమేనా?"
    ),


    "STATE_4_TIMELINE": (
        "మీరు సోలార్ ఇన్‌స్టాలేషన్ ఎప్పటిలో చేయించుకోవాలని భావిస్తున్నారు? "
        "ఒక నెలలోపలనా, ఒకటి నుంచి మూడు నెలల మధ్యనా, "
        "లేదా ప్రస్తుతం కేవలం సమాచారం కోసం మాత్రమేనా?"
    ),

    # 🚀 NEW: Polite exit for users who only want information
    "STATE_4_ENQUIRY_END": (
        "పర్లేదు! మీరు కేవలం సమాచారం కోసం చూస్తున్నారు కాబట్టి, నేను మీ వివరాలను నమోదు చేశాను. "
        "మా బృందం త్వరలో మిమ్మల్ని సంప్రదించి పూర్తి సమాచారాన్ని అందిస్తారు. మీ సమయానికి ధన్యవాదాలు, కాల్ ముగిసింది."
    ),

    
    "STATE_5_PAYMENT": (
        "మీరు చెల్లింపు ఎలా చేయాలనుకుంటున్నారు? "
        "పూర్తి చెల్లింపు లేదా బ్యాంక్ లోన్ ద్వారా?"
    ),
    "STATE_6_CLOSING": (
        "ధన్యవాదాలు! మీ వివరాలు విజయవంతంగా నమోదు అయ్యాయి. "
        "మా టీమ్ త్వరలోనే మీతో సంప్రదించి ఉచిత హోమ్ విజిట్‌ను షెడ్యూల్ చేస్తుంది. "
        "ఈ విజిట్ సమయంలో, మా నిపుణులైన ఇంజనీర్ మీ ప్రాపర్టీని పరిశీలించి "
        "మీకు సరైన సోలార్ పరిష్కారాన్ని సూచిస్తారు. "
        "మీరై సోలార్ ను ఎంచుకున్నందుకు ధన్యవాదాలు! మీ రోజు మంచిగా గడవాలి."
    ),
    "STATE_DISCONNECT": "ధన్యవాదాలు. కాల్ ముగిసింది.",

    # 🚀 NEW: The massive final combo text so it plays instantly
    "STATE_6_FINAL": (
        "ధన్యవాదాలు! మీ వివరాలు విజయవంతంగా నమోదు అయ్యాయి. "
        "మా టీమ్ త్వరలోనే మీతో సంప్రదించి ఉచిత హోమ్ విజిట్‌ను షెడ్యూల్ చేస్తుంది. "
        "ఈ విజిట్ సమయంలో, మా నిపుణులైన ఇంజనీర్ మీ ప్రాపర్టీని పరిశీలించి "
        "మీకు సరైన సోలార్ పరిష్కారాన్ని సూచిస్తారు. "
        "మీరై సోలార్ ను ఎంచుకున్నందుకు ధన్యవాదాలు! మీ రోజు మంచిగా గడవాలి. "
        "ధన్యవాదాలు. కాల్ ముగిసింది."
    ),
}



os.makedirs("static/pre_audio", exist_ok=True)

success = 0
failed = 0

for name, text in STATES.items():
    output_path = f"static/pre_audio/{name}.wav"

    #  NEW: Check if the file already exists before calling the API!
    if os.path.exists(output_path):
        print(f"⏩ Skipping {name}... (Audio file already exists)")
        success += 1
        continue

    print(f"[{success + failed + 1}/{len(STATES)}] Generating {name}...")

    try:
        response = client.text_to_speech.convert(
            text=text,
            target_language_code="te-IN",
            speaker="ritu",
            pace=1.1,
            speech_sample_rate=22050,
            enable_preprocessing=True,
            model="bulbul:v3"
        )

        if hasattr(response, 'audios') and response.audios:
            audio_data = base64.b64decode(response.audios[0])
            with open(output_path, 'wb') as f:
                f.write(audio_data)

            print(f"  OK Saved to {output_path} ({len(audio_data)} bytes)")
            success += 1
        else:
            print(f"  FAILED Unexpected response format: {type(response)}")
            print(f"    Response: {response}")
            failed += 1

    except Exception as e:
        print(f"  FAILED Error: {e}")
        failed += 1

print(f"\n{'='*50}")
print(f"Done! Generated: {success}/{len(STATES)} | Failed: {failed}")
print(f"Audio files saved to: static/pre_audio/")