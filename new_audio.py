from pathlib import Path
import subprocess

# 🚀 Target your specific folder
target_folder = Path("static/new_audio")

# Search for mp3 files ONLY inside that folder
for mp3_file in target_folder.glob("*.mp3"):
    wav_file = mp3_file.with_suffix(".wav")

    if wav_file.exists():
        print(f"Skipping {mp3_file.name} (WAV already exists)")
        continue

    # Convert keeping the Telecom Standard flags!
    subprocess.run([
        "ffmpeg",
        "-i", str(mp3_file),
        "-ac", "1",             # Channels: 1 (Mono)
        "-ar", "8000",          # Sample Rate: 8000 Hz (Telecom standard)
        "-c:a", "pcm_s16le",    # Codec: 16-bit PCM
        str(wav_file)
    ], check=True)

    print(f"Converted {mp3_file.name} to Telecom-Ready WAV")