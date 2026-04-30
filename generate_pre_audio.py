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
        "నమస్కారం,  నేను ఉన్నతి ల్యాండ్ అండ్ Infra నుండి దీప్తి మాట్లాడుతున్నాను."
        "హైదరాబాద్ రింగ్ రోడ్డు కి వంద కిలోమీటర్ల దూరంలో మా సత్వ ఆర్గానిక్ Farms ప్రాజెక్ట్ Early launch offer లో గజం భూమి కేవలం వేయి రూపాయలకే అందుబాటులో ఉంది."
        "మీ భూమిలో మా కంపెనీ కమర్షియల్ sandalwood farming చేసి సంవత్సరానికి రెండు లక్షల వరకు మరియు పదిహేను సంవత్సరాల్లో నాలుగు కోట్లు వరకు ఆదాయం పొందవచ్చు."
        "మీరు వివరాలు తెలుసుకోవాలనుకుంటున్నారా?"
    ),

    "STATE_1_NO_END": (
        "పర్లేదు, మీకు తరువాత ఆసక్తి ఉంటే ఈ నంబర్‌కు కాల్ చేయండి."
        "ధన్యవాదాలు!"
    ),

    "STATE_2_INVESTMENT_REASON": (
        "మీరు ఈ land ను ఎందుకు consider చేస్తున్నారు?"
        "investment కోసమా లేక farmhouse కోసమా?"
    ),

    "STATE_3_PROPERTY": (
        "సుమారుగా ఎంత భూమి కావాలి అనుకుంటున్నారు?"
        "పావు ఎకరం, అర ఎకరం లేదా ఒక ఎకరం?"
    ),

    "STATE_4_PAYMENT": (
        "మీరు పూర్తి payment ఎలా చేయాలని అనుకుంటున్నారు?"
        "Full Payment లేదా EMI?"
    ),

    "STATE_5_TIMELINE": (
        "మీరు investment ఎప్పటిలో చేయాలని అనుకుంటున్నారు?"
        "ఒక నెలలోపలనా, మూడు నెలల మధ్యనా, లేదా ప్రస్తుతం కేవలం సమాచారం కోసమా?"
    ),

    "STATE_6_SITE_VISIT": (
        "ప్రతి సండే ఉచిత సైట్ విజిట్ ఉంటుంది, free pickup facility కూడా ఉంటుంది."
        "మీకు ఈ సండే సైట్ విజిట్ Arrange చేయాలా లేదా మీకు సౌకర్యమైన తేదీ మరియు సమయం చెప్పండి."
    ),

    "STATE_7_CLOSING": (
        "ధన్యవాదాలు! మీ వివరాలు విజయవంతంగా నమోదు అయ్యాయి."
        "మా టీమ్ త్వరలోనే మీకు కాల్ చేసి site visit ను confirm చేస్తారు."
        "Site visit లో అన్ని వివరాలను స్పష్టంగా వివరించబడతాయి."
        "ఉన్నతి ల్యాండ్ అండ్ Infra ను ఎంచుకున్నందుకు ధన్యవాదాలు!"
    ),

    "STATE_DISCONNECT": (
        " కాల్ ముగిసింది."
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
            speaker="simran",
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