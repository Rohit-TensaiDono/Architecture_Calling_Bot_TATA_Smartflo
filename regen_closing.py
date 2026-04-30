"""Regenerate STATE_6_CLOSING.wav only."""
from sarvamai import SarvamAI
import base64, os

client = SarvamAI(api_subscription_key="sk_1egy7shz_foVYeKo9OrfrtR454ZagxTyw")

text = (
    "धन्यवाद! आपकी डिटेल्स successfully receive हो गई हैं। "
    "हमारी टीम आपको जल्दी ही contact करेगी और free home visit schedule करेगी। "
    "इस visit के दौरान, हमारे expert engineer आपकी property inspect करके "
    "best solar solution suggest करेंगे। "
    "Thank you for choosing Mierae Solar. Have a great day"
)

output_path = "static/pre_audio/STATE_6_CLOSING.wav"
os.makedirs("static/pre_audio", exist_ok=True)

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
    audio_data = base64.b64decode(response.audios[0])
    with open(output_path, "wb") as f:
        f.write(audio_data)
    print(f"OK  Saved: {output_path}  ({len(audio_data):,} bytes)")
except Exception as e:
    print(f"FAILED: {e}")
