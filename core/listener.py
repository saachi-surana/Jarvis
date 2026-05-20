# Setup notes:
# 1. pip install openwakeword pyaudio pygame
#    On macOS: brew install portaudio  (before pip install pyaudio)
# 2. openwakeword auto-downloads the hey_jarvis model on first run (~2 MB).
# 3. No API key required — fully local.

import math
import struct
import threading

import numpy as np
import pyaudio
import pygame

SAMPLE_RATE          = 16000
CHANNELS             = 1
FORMAT               = pyaudio.paInt16
CHUNK                = 512      # frames per read during command recording
DETECTION_CHUNK      = 1280     # exactly 80 ms at 16 kHz — required by openwakeword
WAKE_SCORE_THRESHOLD = 0.5
SILENCE_THRESHOLD    = 900      # RMS below this is silence (raised from 500 to filter noise)
SILENCE_DURATION     = 1.5     # seconds of silence to end recording
MAX_RECORD_SECONDS   = 12
MIN_RECORD_SECONDS   = 1.0      # discard recordings shorter than this


def _generate_chime(frequency: int = 880, duration_ms: int = 200) -> bytes:
    sample_rate = 44100
    n = int(sample_rate * duration_ms / 1000)
    return b"".join(
        struct.pack("<h", int(32767 * 0.3 * math.sin(2 * math.pi * frequency * i / sample_rate)))
        for i in range(n)
    )


def _play_chime():
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
        sound = pygame.sndarray.make_sound(np.frombuffer(_generate_chime(), dtype=np.int16))
        sound.play()
        pygame.time.wait(250)
    except Exception as e:
        print(f"[Listener] Chime failed: {e}")


def _rms(data: bytes) -> float:
    shorts = struct.unpack(f"{len(data) // 2}h", data)
    return math.sqrt(sum(s * s for s in shorts) / len(shorts)) if shorts else 0.0


def _record_until_silence(stream: pyaudio.Stream) -> bytes | None:
    """
    Record until SILENCE_DURATION of consecutive silence or MAX_RECORD_SECONDS.
    Returns the audio bytes, or None if the recording is too short to be real speech.
    """
    frames          = []
    silent_chunks   = 0
    max_chunks      = int(SAMPLE_RATE / CHUNK * MAX_RECORD_SECONDS)
    silence_needed  = int(SAMPLE_RATE / CHUNK * SILENCE_DURATION)
    min_chunks      = int(SAMPLE_RATE / CHUNK * MIN_RECORD_SECONDS)

    for _ in range(max_chunks):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
        rms  = _rms(data)
        silent_chunks = silent_chunks + 1 if rms < SILENCE_THRESHOLD else 0
        if silent_chunks >= silence_needed:
            break

    if len(frames) < min_chunks:
        print(f"[Listener] Recording too short ({len(frames)} chunks < {min_chunks} min) — discarding.")
        return None

    audio = b"".join(frames)
    duration_s = len(audio) / (SAMPLE_RATE * 2)  # 2 bytes per sample
    print(f"[Listener] Recorded {duration_s:.2f}s of audio.")
    return audio


class Listener:
    def __init__(self, on_audio_callback):
        self.on_audio          = on_audio_callback
        self._oww_model        = None
        self._wake_word_active = False
        self._thread           = None
        self._stop_event       = threading.Event()
        self._init_openwakeword()

    def _init_openwakeword(self):
        try:
            from openwakeword.model import Model
            self._oww_model        = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            self._wake_word_active = True
            print("[Listener] Wake word 'hey jarvis' active via openwakeword.")
        except Exception as e:
            print(f"[Listener] WARNING: openwakeword init failed ({e}) — mic button only.")

    @property
    def wake_word_status(self) -> str:
        return "active" if self._wake_word_active else "disabled (mic button only)"

    def _listen_loop(self):
        pa = pyaudio.PyAudio()
        stream = pa.open(
            rate=SAMPLE_RATE,
            channels=CHANNELS,
            format=FORMAT,
            input=True,
            frames_per_buffer=DETECTION_CHUNK,
        )
        print("[Listener] Listening for wake word...")
        try:
            while not self._stop_event.is_set():
                pcm      = stream.read(DETECTION_CHUNK, exception_on_overflow=False)
                chunk_np = np.frombuffer(pcm, dtype=np.int16)
                scores   = self._oww_model.predict(chunk_np)

                if any(s >= WAKE_SCORE_THRESHOLD for s in scores.values()):
                    print("[Listener] Wake word detected.")
                    _play_chime()
                    self._oww_model.reset()

                    stream.stop_stream()
                    rec = pa.open(
                        rate=SAMPLE_RATE,
                        channels=CHANNELS,
                        format=FORMAT,
                        input=True,
                        frames_per_buffer=CHUNK,
                    )
                    audio_bytes = _record_until_silence(rec)
                    rec.stop_stream()
                    rec.close()

                    if audio_bytes is not None:
                        self.on_audio(audio_bytes)
                    else:
                        print("[Listener] Discarded short/silent recording after wake word.")
                    stream.start_stream()
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def trigger_recording(self):
        """Manually start a recording session — called by the mic button in the HUD."""
        _play_chime()
        pa = pyaudio.PyAudio()
        stream = pa.open(
            rate=SAMPLE_RATE,
            channels=CHANNELS,
            format=FORMAT,
            input=True,
            frames_per_buffer=CHUNK,
        )
        audio_bytes = _record_until_silence(stream)
        stream.stop_stream()
        stream.close()
        pa.terminate()
        if audio_bytes is not None:
            self.on_audio(audio_bytes)
        else:
            print("[Listener] Discarded short/silent recording from mic button.")

    def start(self):
        if self._wake_word_active:
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop_event.set()
