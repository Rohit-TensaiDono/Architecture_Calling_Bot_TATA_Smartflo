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

# All state texts to generate audio for
STATES = {
    "STATE_1_GREETING": (
        "नमस्ते! मैं Mierae Solar से Dipti बोल रही हूँ। "
        "आप अपने घर पर सोलर लगवाकर एक लाख आठ हज़ार रुपये तक की सरकारी सब्सिडी पा सकते हैं, "
        "और हर महीने चार हज़ार रुपये तक का बिजली बिल बचा सकते हैं। "
        "क्या आप सोलर के बारे में फ्री जानकारी लेना चाहेंगे?"
    ),
    "STATE_1_NO_END": (
        "कोई बात नहीं! अगर आप कभी सोलर के बारे में जानकारी लेना चाहें तो "
        "हमें इसी नंबर पर कॉल करें। "
        "Thank you for your time. Have a great day"
    ),
    "STATE_2_PROPERTY": (
        "बहुत अच्छा! सबसे पहले बताएँ, आपकी प्रॉपर्टी किस टाइप की है? "
        "क्या यह एक इंडिपेंडेंट हाउस है, अपार्टमेंट है, या कमर्शियल प्रॉपर्टी है?"
    ),
    "STATE_3_BILL": (
        "आपका औसत मासिक बिजली का बिल कितना आता है? "
        "क्या यह एक हज़ार से दो हज़ार के बीच है, "
        "दो हज़ार से पाँच हज़ार के बीच है, "
        "या पाँच हज़ार से ज़्यादा है?"
    ),
    "STATE_4_TIMELINE": (
        "आप सोलर इंस्टॉलेशन कब तक करवाना चाहते हैं? "
        "क्या एक महीने के अंदर, एक से तीन महीने के अंदर, "
        "या अभी सिर्फ़ एन्क्वायरी कर रहे हैं?"
    ),
    "STATE_5_PAYMENT": (
        "आप पेमेंट कैसे करना prefer करेंगे? "
        "फुल पेमेंट, या बैंक लोन?"
    ),
    "STATE_6_CLOSING": (
        "धन्यवाद! आपकी डिटेल्स successfully receive हो गई हैं। "
        "हमारी टीम आपको जल्दी ही contact करेगी और free home visit schedule करेगी। "
        "इस visit के दौरान, हमारे expert engineer आपकी property inspect करके "
        "best solar solution suggest करेंगे। "
        "Thank you for choosing Mierae Solar. Have a great day"
    ),
    "STATE_DISCONNECT": "धन्यवाद। कॉल समाप्त हो चुकी है। Thank you!",
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
            target_language_code="hi-IN",
            speaker="roopa",
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
