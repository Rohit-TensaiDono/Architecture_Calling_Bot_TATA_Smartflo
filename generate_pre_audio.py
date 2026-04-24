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
        "ନମସ୍କାର! ମୁଁ Mierae Solar ରୁ ଦୀପ୍ତି କହୁଛି। "
        "ଆପଣ ନିଜ ଘରେ ସୋଲାର ଲଗାଇ ଏକ ଲକ୍ଷ ଅଠତିରିଶି ହଜାର ଟଙ୍କା ପର୍ଯ୍ୟନ୍ତ ସରକାରୀ ସବସିଡି ପାଇପାରିବେ, "
        "ଏବଂ ପ୍ରତିମାସ ଚାରି ହଜାର ଟଙ୍କା ପର୍ଯ୍ୟନ୍ତ ବିଦ୍ୟୁତ ବିଲ୍ ବଞ୍ଚାଇପାରିବେ। "
        "ଆପଣ ସୋଲାର ବିଷୟରେ ମାଗଣା ସୂଚନା ନେବାକୁ ଇଚ୍ଛା କରିବେ କି?"
    ),
    "STATE_1_NO_END": (
        "କିଛି ନୁହେଁ! ଯଦି ପରେ ଆପଣ ସୋଲାର ବିଷୟରେ ଜାଣିବାକୁ ଚାହିବେ, "
        "ତେବେ ଆମକୁ ଏହି ନମ୍ବରରେ କଲ୍ କରନ୍ତୁ। "
        "ଧନ୍ୟବାଦ! ଆପଣଙ୍କ ଦିନଟି ଭଲ କଟୁ।"
    ),
    "STATE_2_PROPERTY": (
        "ଆପଣଙ୍କ ପ୍ରୋପର୍ଟି କଣ ପ୍ରକାରର? "
        "ଏହା ସ୍ୱତନ୍ତ୍ର ଘର, ଆପାର୍ଟମେଣ୍ଟ କିମ୍ବା କମର୍ସିଆଲ୍ ପ୍ରୋପର୍ଟି?"
    ),
    "STATE_3_BILL": (
        "ଆପଣଙ୍କ ମାସିକ ବିଦ୍ୟୁତ ବିଲ୍ କେତେ ଆସେ? "
        "ଏକ ହଜାରରୁ ଦୁଇ ହଜାର, "
        "ଦୁଇ ହଜାରରୁ ପାଞ୍ଚ ହଜାର, "
        "ନା କି ପାଞ୍ଚ ହଜାରରୁ ଅଧିକ?"
    ),
    "STATE_4_TIMELINE": (
        "ଆପଣ କେବେ ସୋଲାର ଇନ୍ସଟଲେସନ୍ କରିବାକୁ ଚାହୁଁଛନ୍ତି? "
        "ଏକ ମାସ ଭିତରେ, ଏକରୁ ତିନି ମାସ ମଧ୍ୟରେ, "
        "ନା କି ଏବେ କେବଳ ଜାଣିବାକୁ ଚାହୁଁଛନ୍ତି?"
    ),
    "STATE_5_PAYMENT": (
        "ଆପଣ କିପରି ପେମେଣ୍ଟ କରିବାକୁ ଚାହିବେ? "
        "ପୁରା ପେମେଣ୍ଟ କିମ୍ବା ବ୍ୟାଙ୍କ ଲୋନ୍?"
    ),
    "STATE_6_CLOSING": (
        "ଧନ୍ୟବାଦ! ଆପଣଙ୍କ ତଥ୍ୟ ସଫଳତାର ସହିତ ମିଳିଗଲା। "
        "ଆମ ଟିମ୍ ଶୀଘ୍ର ଆପଣଙ୍କୁ ସମ୍ପର୍କ କରିବ। "
        "Mierae Solar ବାଛିଥିବାରୁ ଧନ୍ୟବାଦ!"
    ),
    "STATE_DISCONNECT": "ଧନ୍ୟବାଦ। କଲ୍ ସମାପ୍ତ ହୋଇଛି।",
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
            target_language_code="od-IN",
            speaker="ritu",
            pace=1.13,
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