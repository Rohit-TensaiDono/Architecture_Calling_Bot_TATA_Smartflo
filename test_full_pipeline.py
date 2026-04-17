import sounddevice as sd
from scipy.io.wavfile import write
from pydub import AudioSegment
from pydub.playback import play
import time

from smartflo_server import transcribe_mulaw, audio_converter
from solar_webhook import handle_user_input  # make sure this exists


DURATION = 5
FS = 16000


def record_audio():
    print("\n🎤 Speak now...")
    recording = sd.rec(int(DURATION * FS), samplerate=FS, channels=1, dtype='int16')
    sd.wait()
    write("input.wav", FS, recording)
    print("✅ Recorded")
    return "input.wav"


import wave
import pyaudio

def play_audio(file_path):
    try:
        wf = wave.open(file_path, 'rb')

        p = pyaudio.PyAudio()

        stream = p.open(
            format=p.get_format_from_width(wf.getsampwidth()),
            channels=wf.getnchannels(),
            rate=wf.getframerate(),
            output=True
        )

        data = wf.readframes(1024)

        while data:
            stream.write(data)
            data = wf.readframes(1024)

        stream.stop_stream()
        stream.close()
        p.terminate()

    except Exception as e:
        print("❌ Playback error:", e)

def process_audio_bytes(session, wav_data):
    mulaw = audio_converter.wav_to_mulaw(wav_data)
    user_text = transcribe_mulaw(mulaw)

    if not user_text:
        return None

    response = handle_user_input(session, user_text)

    return {
        "user_text": user_text,
        "bot_text": response["text"],
        "audio_path": response["audio_path"]
    }


def main():
    session = {
        "state": "STATE_1",
        "retries": 0,
        "data": {}
    }

    print("\n🚀 Voice Bot Started (Odia)\n")

    while True:
        # 🎤 Record audio
        wav_path = record_audio()

        # 🔁 Convert → mulaw
        with open(wav_path, "rb") as f:
            wav_data = f.read()

        mulaw = audio_converter.wav_to_mulaw(wav_data)

        # 🧠 STT
        user_text = transcribe_mulaw(mulaw)
        print(f"\n🧠 USER SAID: {user_text}")

        if not user_text:
            print("⚠️ No speech detected")
            continue

        # 🤖 BOT LOGIC
        response = handle_user_input(session, user_text)

        bot_text = response.get("text", "")
        bot_audio = response.get("audio_path", "")

        print(f"🤖 BOT: {bot_text}")

        # 🔊 Play response
        if bot_audio:
            print("🔊 Playing response...")
            play_audio(bot_audio)
        else:
            print("⚠️ No audio generated")

        # 🛑 End condition
        if session.get("state") == "END":
            print("\n✅ Conversation ended")
            break

        time.sleep(1)


if __name__ == "__main__":
    main()