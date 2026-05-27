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

# All state texts to generate audio
STATES = {
 
    "STATE_1_GREETING": (
        "నమస్కారం, హైదరాబాద్ ఔటర్ రింగ్ రోడ్ ఎగ్జిట్ ౫ కి జస్ట్ ఒక నిమిషం దూరంలో "
        "ప్రీమియం ఫ్లాట్స్ స్క్వేర్ ఫీట్ కేవలం ౪,౫౦౦ రూపాయలు మాత్రమే. "
        "డిసెంబర్ ౨౦౨౬ కి హ్యాండోవర్. "
        "మీరు వివరాలు తెలుసుకోవాలనుకుంటున్నారా?"
    ),
 
    "STATE_1_NO_END": (
        "పర్లేదు, మీకు తరువాత ఆసక్తి ఉంటే ఈ నంబర్‌కు కాల్ చేయండి. "
        "ధన్యవాదాలు!"
    ),
 
    "STATE_2_INVESTMENT_REASON": (
        "మీరు ప్రస్తుతం హైదరాబాద్‌లో కొత్త ఇల్లు కోసం చూస్తున్నారా "
        "లేక పెట్టుబడి కోసం చూస్తున్నారా?"
    ),
 
    "STATE_3_PROPERTY": (
        "మీరు రెండు బెడ్‌రూమ్ అపార్ట్‌మెంట్ కావాలనుకుంటున్నారా "
        "లేక మూడు బెడ్‌రూమ్ డూప్లెక్స్ విల్లా కావాలనుకుంటున్నారా?"
    ),
 
    "STATE_4_PAYMENT": (
        "మీరు పూర్తి చెల్లింపుతో కొనాలనుకుంటున్నారా "
        "లేక ఈఎంఐ సౌకర్యంతో కొనాలనుకుంటున్నారా?"
    ),
 
    "STATE_5_TIMELINE": (
        "మీరు ఈ పెట్టుబడిని ఎప్పటిలో చేయాలని అనుకుంటున్నారు? "
        "ఒక నెలలోపలా, మూడు నెలలలోపలా, "
        "లేక ప్రస్తుతం కేవలం సమాచారం కోసమా?"
    ),
 
    "STATE_6_SITE_VISIT": (
    	"ప్రతి రోజు ఉచిత పికప్ సౌకర్యం అందుబాటుతో సైట్ విజిట్ ఉంటుంది. "
        "మీకు సౌకర్యమైన తేదీ మరియు సమయం చెప్పండి."
    ),
 
    "STATE_7_CLOSING": (
        "ధన్యవాదాలు! మీ వివరాలు విజయవంతంగా నమోదు అయ్యాయి. "
        "మా టీమ్ త్వరలోనే మీకు కాల్ చేసి సైట్ విజిట్‌ను నిర్ధారిస్తుంది. "
        "సైట్ విజిట్‌లో అన్ని వివరాలు స్పష్టంగా తెలియజేయబడతాయి. "
        "ఉన్నతి ల్యాండ్ అండ్ ఇన్‌ఫ్రాను ఎంచుకున్నందుకు ధన్యవాదాలు!"
    ),

    "STATE_PRICE_AND_PROPERTY": (
        "మా ప్రాజెక్ట్‌లో స్క్వేర్ ఫీట్ ధర కేవలం ౪,౫౦౦ రూపాయలు మాత్రమే. "
        "మీరు రెండు బెడ్‌రూమ్ అపార్ట్‌మెంట్ కావాలనుకుంటున్నారా "
        "లేక మూడు బెడ్‌రూమ్ డూప్లెక్స్ విల్లా కావాలనుకుంటున్నారా?"
    ),
 
    "STATE_DISCONNECT": (
        "కాల్ ముగిసింది."
    )
}



os.makedirs("static/pre_audio", exist_ok=True)

success = 0
failed = 0

for name, text in STATES.items():
    output_path = f"static/pre_audio/{name}.wav"

    print(f"[{success + failed + 1}/{len(STATES)}] Generating {name}...")

    try:
        response = client.text_to_speech.convert(
            text=text,
            target_language_code="te-IN",
            speaker="ritu",
            pace=1.085,
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