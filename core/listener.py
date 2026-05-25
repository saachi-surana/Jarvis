# Setup notes:
# 1. pip install openwakeword sounddevice
#    sounddevice uses Core Audio on macOS natively — no brew packages needed.
# 2. openwakeword auto-downloads the hey_jarvis model on first run (~2 MB).
# 3. No API key required — fully local.

import collections
import math
import os
import queue
import subprocess
import sys
import threading
import time

import numpy as np
import sounddevice as sd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.logger import logger
from config import (
    CHIME_SOUND,
    WAKE_WORD_THRESHOLD,
    WAKE_WORD_COOLDOWN,
    SILENCE_THRESHOLD,
    MAX_RECORD_SECONDS,
    MIN_RECORD_SECONDS,
)

SAMPLE_RATE     = 16000
CHANNELS        = 1
DTYPE           = "int16"
BLOCKSIZE       = 1280      # exactly 80 ms at 16 kHz — required by openwakeword
SILENCE_DURATION = 1.5     # seconds of consecutive silence to end recording
PIPELINE_START_WAIT = 20.0 # max seconds to wait for speaker to start after on_audio()

# Rolling pre-buffer: capture ~0.5s before wake word fires so the
# first word of the command isn't clipped.
PRE_BUFFER_CHUNKS = max(1, int(SAMPLE_RATE / BLOCKSIZE * 0.5))  # ≈ 6 chunks


def _play_chime() -> None:
    try:
        subprocess.run(["afplay", CHIME_SOUND], capture_output=True)
    except Exception as e:
        logger.error("Listener chime failed: %s", e)


def _rms(chunk: np.ndarray) -> float:
    samples = chunk.flatten().astype(np.float64)
    return math.sqrt(np.mean(samples ** 2)) if len(samples) else 0.0


def _speaker_is_speaking() -> bool:
    try:
        from core import speaker
        return speaker.is_speaking
    except Exception:
        return False


class Listener:
    def __init__(self, on_audio_callback):
        self.on_audio     = on_audio_callback
        self._oww_model   = None
        self._oww_active  = False
        self._stop_event  = threading.Event()
        self._audio_q     = queue.Queue()
        self._record_q    = queue.Queue()
        self._recording   = False
        self._record_lock = threading.Lock()
        self._pre_buf     = collections.deque(maxlen=PRE_BUFFER_CHUNKS)
        self._init_openwakeword()

    def _init_openwakeword(self):
        try:
            from openwakeword.model import Model
            self._oww_model  = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            self._oww_active = True
            logger.info("Wake word 'hey jarvis' active via openwakeword.")
        except Exception as e:
            logger.warning("openwakeword init failed (%s) — mic button only.", e)

    @property
    def wake_word_status(self) -> str:
        return "active" if self._oww_active else "disabled (mic button only)"

    # ── Audio callback (runs in sounddevice thread) ─────────────────────────

    def _callback(self, indata, frames, time_info, status):
        chunk = indata.copy()
        if self._recording:
            self._record_q.put(chunk)
        else:
            self._audio_q.put(chunk)

    # ── Post-pipeline blocking wait ─────────────────────────────────────────

    def _wait_until_response_done(self):
        deadline = time.monotonic() + PIPELINE_START_WAIT
        while time.monotonic() < deadline:
            if _speaker_is_speaking():
                break
            time.sleep(0.1)

        while _speaker_is_speaking():
            time.sleep(0.1)

        logger.info("Response done — %.1fs cooldown before re-arming.", WAKE_WORD_COOLDOWN)
        time.sleep(WAKE_WORD_COOLDOWN)
        self._drain(self._audio_q)
        self._pre_buf.clear()
        self._oww_model.reset()
        logger.info("Wake word detection re-armed.")

    # ── Wake word detection loop ────────────────────────────────────────────

    def _listen_loop(self):
        logger.info("Listening for wake word...")
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=BLOCKSIZE,
            callback=self._callback,
        ):
            while not self._stop_event.is_set():
                try:
                    chunk = self._audio_q.get(timeout=0.5)
                except queue.Empty:
                    continue

                if _speaker_is_speaking():
                    continue

                self._pre_buf.append(chunk)

                scores = self._oww_model.predict(chunk.flatten())
                if any(s >= WAKE_WORD_THRESHOLD for s in scores.values()):
                    logger.info("Wake word detected.")
                    pre_frames = list(self._pre_buf)
                    _play_chime()
                    self._oww_model.reset()
                    audio_bytes = self._collect_recording(pre_frames=pre_frames)
                    if audio_bytes:
                        self.on_audio(audio_bytes)
                        self._wait_until_response_done()
                    else:
                        logger.info("Discarded short/silent recording after wake word.")

    # ── Core recording logic ────────────────────────────────────────────────

    def _collect_recording(self, pre_frames=None) -> bytes | None:
        pre_frames = list(pre_frames or [])

        with self._record_lock:
            # Rescue audio that queued during wake detection + chime playback
            chime_gap = []
            while not self._audio_q.empty():
                try:
                    chime_gap.append(self._audio_q.get_nowait())
                except queue.Empty:
                    break

            self._drain(self._record_q)
            self._recording = True

            frames         = pre_frames + chime_gap
            silent_chunks  = 0
            max_chunks     = int(SAMPLE_RATE / BLOCKSIZE * MAX_RECORD_SECONDS)
            silence_needed = int(SAMPLE_RATE / BLOCKSIZE * SILENCE_DURATION)
            min_chunks     = int(SAMPLE_RATE / BLOCKSIZE * MIN_RECORD_SECONDS)

            for _ in range(max_chunks):
                try:
                    chunk = self._record_q.get(timeout=1.0)
                except queue.Empty:
                    break
                frames.append(chunk)
                silent_chunks = silent_chunks + 1 if _rms(chunk) < SILENCE_THRESHOLD else 0
                if silent_chunks >= silence_needed:
                    break

            self._recording = False

        n_rescued = len(pre_frames) + len(chime_gap)
        if len(frames) < min_chunks:
            logger.info(
                "Recording too short (%d chunks < %d) — discarding.", len(frames), min_chunks
            )
            return None

        audio      = np.concatenate(frames).flatten().tobytes()
        duration_s = len(audio) / (SAMPLE_RATE * 2)
        logger.info("Recorded %.2fs (%d rescued pre-recording frames).", duration_s, n_rescued)
        return audio

    @staticmethod
    def _drain(q: queue.Queue):
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                break

    # ── Public API ──────────────────────────────────────────────────────────

    def trigger_recording(self):
        if _speaker_is_speaking():
            logger.info("Skipping mic trigger — Jarvis is currently speaking.")
            return

        _play_chime()

        if self._oww_active:
            self._drain(self._audio_q)
            audio_bytes = self._collect_recording()
        else:
            audio_bytes = self._record_standalone()

        if audio_bytes:
            self.on_audio(audio_bytes)
        else:
            logger.info("Discarded short/silent recording from mic button.")

    def _record_standalone(self) -> bytes | None:
        tmp_q = queue.Queue()

        def cb(indata, frames, time_info, status):
            tmp_q.put(indata.copy())

        frames         = []
        silent_chunks  = 0
        max_chunks     = int(SAMPLE_RATE / BLOCKSIZE * MAX_RECORD_SECONDS)
        silence_needed = int(SAMPLE_RATE / BLOCKSIZE * SILENCE_DURATION)
        min_chunks     = int(SAMPLE_RATE / BLOCKSIZE * MIN_RECORD_SECONDS)

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=BLOCKSIZE,
            callback=cb,
        ):
            for _ in range(max_chunks):
                try:
                    chunk = tmp_q.get(timeout=1.0)
                except queue.Empty:
                    break
                frames.append(chunk)
                silent_chunks = silent_chunks + 1 if _rms(chunk) < SILENCE_THRESHOLD else 0
                if silent_chunks >= silence_needed:
                    break

        if len(frames) < min_chunks:
            logger.info("Standalone recording too short — discarding.")
            return None

        audio      = np.concatenate(frames).flatten().tobytes()
        duration_s = len(audio) / (SAMPLE_RATE * 2)
        logger.info("Recorded %.2fs of audio.", duration_s)
        return audio

    def start(self):
        if self._oww_active:
            threading.Thread(target=self._listen_loop, daemon=True).start()

    def stop(self):
        self._stop_event.set()
