# ── Model / service URLs ──────────────────────────────────────────────────────
OLLAMA_MODEL     = "llama3.2"
OLLAMA_URL       = "http://localhost:11434"
STUDYSYNC_URL    = "http://localhost:8000"
NOTION_PLANNER_DIR = "~/.notion-planner"
WEATHER_CITY     = "Seattle"

# ── Voice / TTS ───────────────────────────────────────────────────────────────
WAKE_WORD    = "jarvis"
PIPER_BINARY = "python3 -m piper"
PIPER_MODEL  = "~/Projects/Jarvis/voices/en_GB-alan-low.onnx"

# ── Audio ─────────────────────────────────────────────────────────────────────
CHIME_SOUND        = "/System/Library/Sounds/Ping.aiff"   # wake-word confirmation
TIMER_CHIME_SOUND  = "/System/Library/Sounds/Glass.aiff"  # timer done

# ── Wake-word / recording ─────────────────────────────────────────────────────
WAKE_WORD_THRESHOLD  = 0.5   # openwakeword confidence threshold
WAKE_WORD_COOLDOWN   = 2.0   # seconds after speaker finishes before re-arming
SILENCE_THRESHOLD    = 900   # RMS below this is considered silence
MAX_RECORD_SECONDS   = 12    # hard cap on recording length
MIN_RECORD_SECONDS   = 1.0   # recordings shorter than this are discarded

# ── Polling intervals (seconds) ───────────────────────────────────────────────
SPOTIFY_POLL_INTERVAL   = 30
WEATHER_POLL_INTERVAL   = 600
STUDYSYNC_POLL_INTERVAL = 1800

# ── Brain ─────────────────────────────────────────────────────────────────────
MAX_HISTORY = 10   # conversation turns kept in LLM context (each turn = 2 messages)
