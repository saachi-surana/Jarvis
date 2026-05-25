# Setup notes:
# 1. pip install openwakeword sounddevice
#    sounddevice uses Core Audio on macOS natively — no brew packages needed.
# 2. openwakeword auto-downloads the hey_jarvis model on first run (~2 MB).
# 3. No API key required — fully local.

import collections
import math
import queue
import subprocess
import threading
import time

import numpy as np
import sounddevice as sd

SAMPLE_RATE          = 16000
CHANNELS             = 1
DTYPE                = 'int16'
BLOCKSIZE            = 1280     # exactly 80 ms at 16 kHz — required by openwakeword
WAKE_SCORE_THRESHOLD = 0.5
SILENCE_THRESHOLD    = 900      # RMS below this is considered silence
SILENCE_DURATION     = 1.5     # seconds of consecutive silence to end recording
MAX_RECORD_SECONDS   = 12
MIN_RECORD_SECONDS   = 1.0      # discard recordings shorter than this
PIPELINE_START_WAIT  = 20.0    # max seconds to wait for speaker to start after on_audio()
WAKE_COOLDOWN        = 2.0     # seconds to wait after speaker finishes before re-arming

# Rolling pre-buffer: capture ~0.5s of audio before wake word fires so the
# first word of the command (spoken right as OWW locks in) isn't clipped.
PRE_BUFFER_CHUNKS = max(1, int(SAMPLE_RATE / BLOCKSIZE * 0.5))  # ≈ 6 chunks


def _play_chime():
    try:
        subprocess.run(
            ["afplay", "/System/Library/Sounds/Ping.aiff"],
            capture_output=True,
        )
    except Exception as e:
        print(f"[Listener] Chime failed: {e}")


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
        self.on_audio          = on_audio_callback
        self._oww_model        = None
        self._oww_active       = False   # True when OWW model loaded and detection enabled
        self._stop_event       = threading.Event()
        self._audio_q          = queue.Queue()  # detection path
        self._record_q         = queue.Queue()  # recording path
        self._recording        = False          # routes callback output to _record_q when True
        self._record_lock      = threading.Lock()  # prevents concurrent recording sessions
        self._pre_buf          = collections.deque(maxlen=PRE_BUFFER_CHUNKS)  # rolling pre-wake buffer
        self._init_openwakeword()

    def _init_openwakeword(self):
        try:
            from openwakeword.model import Model
            self._oww_model  = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
            self._oww_active = True
            print("[Listener] Wake word 'hey jarvis' active via openwakeword.")
        except Exception as e:
            print(f"[Listener] WARNING: openwakeword init failed ({e}) — mic button only.")

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
        """
        Block the detection loop until the full pipeline finishes:
        transcribe → LLM → speak. Then apply a cooldown before re-arming
        wake word detection to avoid immediately re-triggering.
        """
        # Give the pipeline up to PIPELINE_START_WAIT seconds to start speaking.
        deadline = time.monotonic() + PIPELINE_START_WAIT
        while time.monotonic() < deadline:
            if _speaker_is_speaking():
                break
            time.sleep(0.1)

        # Wait for speaking to finish.
        while _speaker_is_speaking():
            time.sleep(0.1)

        # Cooldown — drain audio that accumulated during the response.
        print(f"[Listener] Response done — {WAKE_COOLDOWN}s cooldown before re-arming.")
        time.sleep(WAKE_COOLDOWN)
        self._drain(self._audio_q)
        self._pre_buf.clear()
        self._oww_model.reset()
        print("[Listener] Wake word detection re-armed.")

    # ── Wake word detection loop ────────────────────────────────────────────

    def _listen_loop(self):
        print("[Listener] Listening for wake word...")
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

                # Skip detection entirely while Jarvis is speaking.
                if _speaker_is_speaking():
                    continue

                # Maintain rolling pre-buffer so we can rescue audio that
                # arrived just before/during wake word confirmation.
                self._pre_buf.append(chunk)

                scores = self._oww_model.predict(chunk.flatten())
                if any(s >= WAKE_SCORE_THRESHOLD for s in scores.values()):
                    print("[Listener] Wake word detected.")
                    # Snapshot pre-buffer before chime introduces a gap.
                    pre_frames = list(self._pre_buf)
                    _play_chime()
                    self._oww_model.reset()
                    audio_bytes = self._collect_recording(pre_frames=pre_frames)
                    if audio_bytes:
                        self.on_audio(audio_bytes)
                        # Block detection until the full pipeline (speak) completes
                        # and the cooldown elapses, so mid-response audio is ignored.
                        self._wait_until_response_done()
                    else:
                        print("[Listener] Discarded short/silent recording after wake word.")

    # ── Core recording logic ────────────────────────────────────────────────

    def _collect_recording(self, pre_frames=None) -> bytes | None:
        """
        Switch to recording mode and collect frames until silence or timeout.
        pre_frames: chunks captured before this call (pre-buffer + chime gap).
        Serialised by _record_lock so two sessions cannot overlap.
        """
        pre_frames = list(pre_frames or [])

        with self._record_lock:
            # Rescue any audio that queued in _audio_q during wake processing
            # and chime playback — afplay blocks ~0.4s, losing the first word.
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
            print(f"[Listener] Recording too short ({len(frames)} chunks < {min_chunks}) — discarding.")
            return None

        audio = np.concatenate(frames).flatten().tobytes()
        duration_s = len(audio) / (SAMPLE_RATE * 2)
        print(f"[Listener] Recorded {duration_s:.2f}s ({n_rescued} rescued pre-recording frames).")
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
        """Manually start a recording — called by the mic button in the HUD."""
        if _speaker_is_speaking():
            print("[Listener] Skipping mic trigger — Jarvis is currently speaking.")
            return

        _play_chime()

        if self._oww_active:
            # Detection stream is already running — reuse it.
            # Drain stale detection chunks so the wake model stays clean.
            self._drain(self._audio_q)
            audio_bytes = self._collect_recording()
        else:
            # No detection stream running — open a temporary one.
            audio_bytes = self._record_standalone()

        if audio_bytes:
            self.on_audio(audio_bytes)
        else:
            print("[Listener] Discarded short/silent recording from mic button.")

    def _record_standalone(self) -> bytes | None:
        """Open a temporary InputStream for recording when wake word is disabled."""
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
            print("[Listener] Recording too short — discarding.")
            return None

        audio = np.concatenate(frames).flatten().tobytes()
        duration_s = len(audio) / (SAMPLE_RATE * 2)
        print(f"[Listener] Recorded {duration_s:.2f}s of audio.")
        return audio

    def start(self):
        if self._oww_active:
            threading.Thread(target=self._listen_loop, daemon=True).start()

    def stop(self):
        self._stop_event.set()
