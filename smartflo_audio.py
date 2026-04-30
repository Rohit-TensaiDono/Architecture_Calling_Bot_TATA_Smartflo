"""
SmartFlo Audio Utilities - Tata Smartflo Bi-Directional Audio Streaming
Adapted from five_5/tata_tele_service.py for use with six_testing bot.

Protocol Events (Incoming from SmartFlo):
- connected : Initial WebSocket connection established
- start     : Stream metadata (streamSid, callSid, mediaFormat)
- media     : Audio data (base64 encoded mu-law)
- stop      : Stream ended

Audio Format:
- Encoding  : audio/x-mulaw  (G.711 µ-law)
- Sample Rate: 8000 Hz, Mono
- Chunk size : Must be multiple of 160 bytes (20ms per frame)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict
import base64
import io
import audioop


@dataclass
class SmartfloSession:
    """Represents an active Tata Smartflo streaming call session."""
    stream_sid: str
    call_sid: str
    encoding: str = "audio/x-mulaw"
    sample_rate: int = 8000
    connected_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True
    audio_buffer: bytes = field(default_factory=bytes)

    def to_dict(self) -> dict:
        return {
            "stream_sid": self.stream_sid,
            "call_sid": self.call_sid,
            "encoding": self.encoding,
            "sample_rate": self.sample_rate,
            "connected_at": self.connected_at.isoformat(),
            "is_active": self.is_active,
            "buffer_size": len(self.audio_buffer),
        }


class SmartfloAudioConverter:
    """
    Audio format converter for SmartFlo's mu-law requirements.
    SmartFlo sends/expects: audio/x-mulaw, 8kHz, mono
    STT  expects: WAV (PCM 16-bit, 16kHz or 8kHz)
    Sarvam TTS produces: WAV (typically 22050Hz)
    """

    @staticmethod
    def mulaw_to_pcm(mulaw_data: bytes) -> bytes:
        """Convert mu-law audio to 16-bit linear PCM."""
        try:
            return audioop.ulaw2lin(mulaw_data, 2)
        except Exception as e:
            print(f"[AudioConvert] mu-law → PCM failed: {e}")
            return b""

    @staticmethod
    def pcm_to_mulaw(pcm_data: bytes, sample_width: int = 2) -> bytes:
        """Convert 16-bit linear PCM audio to mu-law."""
        try:
            return audioop.lin2ulaw(pcm_data, sample_width)
        except Exception as e:
            print(f"[AudioConvert] PCM → mu-law failed: {e}")
            return b""

    @staticmethod
    def wav_to_mulaw(wav_data: bytes) -> bytes:
        """
        Convert WAV audio (any sample rate, mono) to mu-law 8kHz mono.
        Used to convert Sarvam TTS WAV output → SmartFlo format.
        Requires pydub + ffmpeg.
        """
        try:
            from pydub import AudioSegment

            audio = AudioSegment.from_file(io.BytesIO(wav_data), format="wav")
            # Resample to 8kHz, mono, 16-bit
            audio = audio.set_frame_rate(8000).set_channels(1).set_sample_width(2)

            pcm_buffer = io.BytesIO()
            audio.export(pcm_buffer, format="raw")
            pcm_data = pcm_buffer.getvalue()

            mulaw_data = audioop.lin2ulaw(pcm_data, 2)

            # Pad to multiple of 160 bytes (20ms frames at 8kHz)
            remainder = len(mulaw_data) % 160
            if remainder:
                mulaw_data += b"\xff" * (160 - remainder)  # 0xff = silence in mu-law

            return mulaw_data
        except Exception as e:
            print(f"[AudioConvert] WAV → mu-law failed: {e}")
            return b""

    @staticmethod
    def mulaw_to_wav_bytes(mulaw_data: bytes) -> bytes:
        """
        Convert mu-law 8kHz audio to WAV (PCM 16-bit, 8kHz).
        Used to convert SmartFlo incoming audio → format accepted by Google STT.
        """
        try:
            from pydub import AudioSegment

            pcm_data = audioop.ulaw2lin(mulaw_data, 2)
            
            # ── GAIN BOOST ──
            # Boost gain by 2.0x (6dB) to help Google STT catch "normal" speech 
            # in noisy environments (offices, public places).
            pcm_data = audioop.mul(pcm_data, 2, 2)

            audio = AudioSegment(
                data=pcm_data,
                sample_width=2,    # 16-bit
                frame_rate=8000,
                channels=1,
            )
            wav_buffer = io.BytesIO()
            audio.export(wav_buffer, format="wav")
            return wav_buffer.getvalue()
        except Exception as e:
            print(f"[AudioConvert] mu-law → WAV failed: {e}")
            return b""


class TataSmartfloService:
    """
    Manages Tata SmartFlo bi-directional streaming sessions.
    Handles session lifecycle, audio buffering, silence detection,
    and formatting of media response messages.
    """

    def __init__(self):
        self.active_sessions: Dict[str, SmartfloSession] = {}
        self.audio_converter = SmartfloAudioConverter()

        # Buffer settings (8kHz mu-law = 8000 bytes/second)
        self.min_buffer_size = 12000   # 1.5 seconds — more responsive than 3s
        self.max_buffer_size = 64000   # 8 seconds — hard cap

        # Silence detection (Energy based)
        self.silence_threshold = 450         # RMS threshold (300-600 is typical for phone)
        self.silence_duration_bytes = 6400    # Check last 0.8s for silence

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(self, start_data: dict) -> SmartfloSession:
        """
        Create a new session from SmartFlo 'start' event data.
        Expected start_data keys: streamSid, callSid, mediaFormat
        """
        media_fmt = start_data.get("mediaFormat", {})
        session = SmartfloSession(
            stream_sid=start_data.get("streamSid", ""),
            call_sid=start_data.get("callSid", ""),
            encoding=media_fmt.get("encoding", "audio/x-mulaw"),
            sample_rate=media_fmt.get("sampleRate", 8000),
        )
        self.active_sessions[session.stream_sid] = session
        print(f"[SmartFlo] New session — stream:{session.stream_sid[:12]}… call:{session.call_sid[:12]}…")
        return session

    def get_session(self, stream_sid: str) -> Optional[SmartfloSession]:
        return self.active_sessions.get(stream_sid)

    def end_session(self, stream_sid: str) -> Optional[SmartfloSession]:
        if stream_sid in self.active_sessions:
            session = self.active_sessions.pop(stream_sid)
            session.is_active = False
            duration = (datetime.now() - session.connected_at).total_seconds()
            print(f"[SmartFlo] Session ended — stream:{stream_sid[:12]}… duration:{duration:.1f}s")
            return session
        return None

    def get_active_sessions_count(self) -> int:
        return len(self.active_sessions)

    def get_all_sessions(self) -> list:
        return [s.to_dict() for s in self.active_sessions.values()]

    # ------------------------------------------------------------------
    # Audio buffering & silence detection
    # ------------------------------------------------------------------

    def add_audio_to_buffer(self, stream_sid: str, audio_payload_b64: str) -> Optional[bytes]:
        """
        Decode and buffer an incoming base64 mu-law audio chunk.
        Returns buffered audio ready for STT when speech is complete, else None.

        Triggers processing when:
          1) buffer >= min_buffer_size AND last 0.5s is silence
          2) buffer >= max_buffer_size (hard cap)
        """
        session = self.active_sessions.get(stream_sid)
        if not session:
            return None

        try:
            audio_bytes = base64.b64decode(audio_payload_b64)
            session.audio_buffer += audio_bytes
            buf_len = len(session.audio_buffer)

            if buf_len >= self.max_buffer_size:
                print(f"[SmartFlo] Max buffer ({buf_len}B) — forcing processing")
                return self._flush_buffer(session)

            if buf_len >= self.min_buffer_size:
                tail = session.audio_buffer[-self.silence_duration_bytes:]
                if self._is_silence(tail):
                    print(f"[SmartFlo] Silence after {buf_len/8000:.1f}s — processing")
                    return self._flush_buffer(session)

            return None
        except Exception as e:
            print(f"[SmartFlo] Buffer error: {e}")
            return None

    def _flush_buffer(self, session: SmartfloSession) -> bytes:
        data = session.audio_buffer
        session.audio_buffer = bytes()
        return data

    def get_buffered_audio(self, stream_sid: str) -> bytes:
        """Get and clear the current audio buffer for a session (used to discard echo)."""
        session = self.active_sessions.get(stream_sid)
        if session and session.audio_buffer:
            data = session.audio_buffer
            session.audio_buffer = bytes()
            return data
        return bytes()

    def _is_silence(self, audio_chunk: bytes) -> bool:
        """
        Check if an audio chunk is silence using Energy (RMS).
        This is much more robust than checking individual mu-law bytes.
        """
        if not audio_chunk:
            return False
        try:
            # Convert to PCM to calculate RMS energy
            pcm_data = audioop.ulaw2lin(audio_chunk, 2)
            rms = audioop.rms(pcm_data, 2)
            return rms < self.silence_threshold
        except Exception as e:
            print(f"[SmartFlo] Silence check error: {e}")
            return True # fallback to assuming silence

    # ------------------------------------------------------------------
    # Response message builders
    # ------------------------------------------------------------------

    def create_media_response(self, stream_sid: str, audio_data: bytes) -> dict:
        """
        Build a SmartFlo media message to send audio back to the caller.
        audio_data must be mu-law bytes; padded to 160-byte boundary here.
        """
        remainder = len(audio_data) % 160
        if remainder:
            audio_data += b"\xff" * (160 - remainder)

        return {
            "event": "media",
            "streamSid": stream_sid,
            "media": {
                "payload": base64.b64encode(audio_data).decode("utf-8")
            },
        }

    def create_clear_response(self, stream_sid: str) -> dict:
        """Tell SmartFlo to clear its playback buffer (interrupt bot speech)."""
        return {"event": "clear", "streamSid": stream_sid}


# ---------------------------------------------------------------------------
# Singletons — import these in smartflo_server.py
# ---------------------------------------------------------------------------
smartflo_service = TataSmartfloService()
audio_converter = SmartfloAudioConverter()
