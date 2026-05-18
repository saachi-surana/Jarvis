# Setup notes:
# 1. Install openwakeword: pip install openwakeword
#    On first run it auto-downloads the "hey_jarvis" model (~2MB) to ~/.cache/openwakeword/
# 2. Install pyaudio: pip install pyaudio
#    On macOS you may need: brew install portaudio first
# 3. Install pygame: pip install pygame
# 4. No API key required — openwakeword is fully open source and runs locally.
#    If init fails, the fallback keyboard shortcut Cmd+Shift+J applies.

import os
import math
import struct
import threading
import numpy as np
import pyaudio
import pygame

SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT = pyaudio.paInt16
CHUNK = 512
DETECTION_CHUNK = 1280    # openwakeword requires 80ms frames at 16kHz
WAKE_SCORE_THRESHOLD = 0.5
SILENCE_THRESHOLD = 500   # RMS below this is considered silence
SILENCE_DURATION = 1.5    # seconds of silence before stopping recording
MAX_RECORD_SECONDS = 10


def _generate_chime(frequency: int = 880, duration_ms: int = 200) -> bytes:
    """Generate a simple sine-wave chime as raw PCM bytes (16-bit, 44100Hz, mono)."""
    sample_rate = 44100
    num_samples = int(sample_rate * duration_ms / 1000)
    buf = []
    for i in range(num_samples):
        t = i / sample_rate
        sample = int(32767 * 0.3 * math.sin(2 * math.pi * frequency * t))
        buf.append(struct.pack("<h", sample))
    return b"".join(buf)


def _play_chime():
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
        pcm = _generate_chime()
        sound = pygame.sndarray.make_sound(
            np.frombuffer(pcm, dtype=np.int16)
        )
        sound.play()
        pygame.time.wait(250)
    except Exception as e:
        print(f"[Listener] Chime playback failed: {e}")


def _record_until_silence(stream: pyaudio.Stream) -> bytes:
    """Record audio from an open PyAudio stream until silence or max duration."""
    frames = []
    silent_chunks = 0
    max_chunks = int(SAMPLE_RATE / CHUNK * MAX_RECORD_SECONDS)
    silence_chunks_needed = int(SAMPLE_RATE / CHUNK * SILENCE_DURATION)

    for _ in range(max_chunks):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
        # Calculate RMS of this chunk
        shorts = struct.unpack(f"{len(data) // 2}h", data)
        rms = math.sqrt(sum(s * s for s in shorts) / len(shorts)) if shorts else 0
        if rms < SILENCE_THRESHOLD:
            silent_chunks += 1
        else:
            silent_chunks = 0
        if silent_chunks >= silence_chunks_needed:
            break

    return b"".join(frames)


class Listener:
    def __init__(self, on_audio_callback):
        """
        on_audio_callback: callable that receives raw PCM audio bytes (int16, 16kHz, mono)
        """
        self.on_audio = on_audio_callback
        self._oww_model = None
        self._wake_word_active = False
        self._thread = None
        self._stop_event = threading.Event()
        self._init_openwakeword()

    def _init_openwakeword(self):
        try:
            from openwakeword.model import Model
            self._oww_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            self._wake_word_active = True
            print("[Listener] Wake word 'hey jarvis' active via openwakeword.")
        except Exception as e:
            print(f"[Listener] WARNING: openwakeword init failed ({e}) — wake word disabled. Use Cmd+Shift+J.")

    @property
    def wake_word_status(self) -> str:
        return "active" if self._wake_word_active else "disabled (keyboard fallback)"

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
                pcm = stream.read(DETECTION_CHUNK, exception_on_overflow=False)
                audio_chunk = np.frombuffer(pcm, dtype=np.int16)
                scores = self._oww_model.predict(audio_chunk)
                if any(score >= WAKE_SCORE_THRESHOLD for score in scores.values()):
                    print("[Listener] Wake word detected.")
                    _play_chime()
                    self._oww_model.reset()
                    # Switch to recording stream
                    stream.stop_stream()
                    rec_stream = pa.open(
                        rate=SAMPLE_RATE,
                        channels=CHANNELS,
                        format=FORMAT,
                        input=True,
                        frames_per_buffer=CHUNK,
                    )
                    audio_bytes = _record_until_silence(rec_stream)
                    rec_stream.stop_stream()
                    rec_stream.close()
                    self.on_audio(audio_bytes)
                    stream.start_stream()
        finally:
            stream.stop_stream()
            stream.close()
        pa.terminate()

    def trigger_recording(self):
        """Manually trigger a recording session (used for keyboard shortcut fallback)."""
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
        self.on_audio(audio_bytes)

    def start(self):
        if self._wake_word_active:
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop_event.set()
