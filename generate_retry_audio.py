"""
Generate pre-recorded audio files for all retry/failure states using Sarvam AI TTS.
"""
from sarvamai import SarvamAI
import base64
import os
import solar_webhook

client = SarvamAI(
    api_subscription_key="sk_1egy7shz_foVYeKo9OrfrtR454ZagxTyw",
)

os.makedirs("static/pre_audio", exist_ok=True)

# Collect all new retry texts to generate
texts_to_generate = {
    solar_webhook.END_MISUNDERSTAND: "static/pre_audio/END_MISUNDERSTAND.wav",
    solar_webhook.NO_SPEECH_END: "static/pre_audio/NO_SPEECH_END.wav",

    # ✅ FIXED: Hindi → Odia
    solar_webhook.RETRY_PREFIX + "ଦୟାକରି ପୁଣିଥରେ କହନ୍ତୁ।": "static/pre_audio/NO_SPEECH_RETRY.wav"
}

# Add state retries
for state_key, q_text in solar_webhook.RETRY_QUESTIONS.items():
    full_retry_text = solar_webhook.RETRY_PREFIX + q_text
    texts_to_generate[full_retry_text] = f"static/pre_audio/{state_key}_RETRY.wav"

success = 0
failed = 0

print(f"Starting generation of {len(texts_to_generate)} retry audio files using Sarvam AI...")

for text, output_path in texts_to_generate.items():
    print(f"\nGenerating: {output_path}")
    print(f"Text: {text[:60]}...")

    try:
        response = client.text_to_speech.convert(
            text=text,
            target_language_code="od-IN",  # ✅ already correct
            speaker="roopa",
            pace=1.1,
            speech_sample_rate=22050,
            enable_preprocessing=True,
            model="bulbul:v3"
        )

        if hasattr(response, 'audios') and response.audios:
            audio_data = base64.b64decode(response.audios[0])

            # overwrite existing files (intentional)
            with open(output_path, 'wb') as f:
                f.write(audio_data)

            print(f"  OK Saved to {output_path} ({len(audio_data)} bytes)")
            success += 1
        else:
            print(f"  FAILED Unexpected response format")
            failed += 1

    except Exception as e:
        print(f"  FAILED Error: {e}")
        failed += 1

print(f"\n{'='*50}")
print(f"Done! Generated: {success}/{len(texts_to_generate)} | Failed: {failed}")