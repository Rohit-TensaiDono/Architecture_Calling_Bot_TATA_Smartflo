import sounddevice as sd
from scipy.io.wavfile import write
import numpy as np

from smartflo_server import transcribe_mulaw, audio_converter

# Recording settings
DURATION = 5  # seconds
FS = 16000    # sample rate

print("🎤 Speak now (Odia)...")

# Record audio
recording = sd.rec(int(DURATION * FS), samplerate=FS, channels=1, dtype='int16')
sd.wait()

# Save temp wav
write("mic_test.wav", FS, recording)

print("✅ Recording complete")

# Load and convert
with open("mic_test.wav", "rb") as f:
    wav_data = f.read()

mulaw_data = audio_converter.wav_to_mulaw(wav_data)

# STT
text = transcribe_mulaw(mulaw_data)

print("\n==== RESULT ====")
print(text)