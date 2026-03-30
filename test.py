from sarvamai import SarvamAI
import base64
import os

client = SarvamAI(
    api_subscription_key="sk_f4m68vei_79Gq5UPYq1dKawQeu49o0sdS",
)

response = client.text_to_speech.convert(
            text="धन्यवाद। कॉल समाप्त हो चुकी है। Thank you!",
            target_language_code="hi-IN",
            speaker="roopa",
            pace=1.1,
            # pitch=0.5,  # Increase pitch for a sharper tone
            speech_sample_rate=22050,
            enable_preprocessing=True,
            model="bulbul:v3"
        )

output_path="test.wav"
with open(output_path, 'wb') as f:
    audio_data = base64.b64decode(response.audios[0])
    f.write(audio_data)
    print(f"  ✓ Saved to {output_path} ({len(audio_data)} bytes)")