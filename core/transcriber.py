# Setup notes:
# faster-whisper uses CTranslate2 under the hood.
# On first use it will download the "base" model (~145MB) to ~/.cache/huggingface/
# Install: pip install faster-whisper
# On macOS with Apple Silicon, set compute_type="int8" (default here) for best performance.

import os
import tempfile
import wave
from typing import Optional

from faster_whisper import WhisperModel

SAMPLE_RATE  = 16000
CHANNELS     = 1
SAMPLE_WIDTH = 2  # int16


class Transcriber:
    def __init__(self):
        print("[Transcriber] Loading Whisper 'base' model...")
        self._model = WhisperModel("base", device="cpu", compute_type="int8")
        print("[Transcriber] Model ready.")

    def transcribe(self, audio_bytes: bytes) -> Optional[str]:
        """
        Transcribe raw PCM audio bytes (int16, 16kHz, mono) to text.
        Returns transcribed string or None on failure/empty result.
        """
        if not audio_bytes:
            return None
        tmp_path = None
        try:
            # Wrap raw PCM in a WAV container so faster-whisper can read it
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
                with wave.open(tmp_path, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(SAMPLE_WIDTH)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(audio_bytes)

            segments, info = self._model.transcribe(
                tmp_path,
                language="en",           # force English — avoids mis-detection
                beam_size=5,             # wider beam → more accurate candidates
                best_of=5,               # evaluate 5 candidates, pick best
                temperature=0,           # greedy / deterministic, no hallucination
                vad_filter=True,         # skip non-speech segments
                vad_parameters={
                    "min_silence_duration_ms": 500,  # must have 500ms silence to split
                },
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            if text:
                print(f"[Transcriber] '{text}'  (lang={info.language} prob={info.language_probability:.2f})")
            return text if text else None

        except Exception as e:
            print(f"[Transcriber] ERROR: {e}")
            return None
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
