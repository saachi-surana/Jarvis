#!/usr/bin/env bash
# download_voice.sh — Download Piper TTS binary + en_US-ryan-high voice model
# Run once: bash ~/Projects/Jarvis/download_voice.sh

set -e

JARVIS_DIR="$HOME/Projects/Jarvis"
PIPER_DIR="$JARVIS_DIR/piper"
VOICES_DIR="$JARVIS_DIR/voices"

mkdir -p "$PIPER_DIR" "$VOICES_DIR"

# ── 1. Detect Mac architecture ─────────────────────────────────────────────────
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    PIPER_ARCH="aarch64"
else
    PIPER_ARCH="x86_64"
fi

echo "========================================"
echo " Jarvis Voice Setup"
echo " Architecture: macOS $ARCH ($PIPER_ARCH)"
echo "========================================"
echo ""

# ── 2. Download Piper binary ───────────────────────────────────────────────────
PIPER_VERSION="2023.11.14-2"
PIPER_ARCHIVE="piper_macos_${PIPER_ARCH}.tar.gz"
PIPER_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/${PIPER_ARCHIVE}"

echo "Downloading Piper binary..."
echo "  from: $PIPER_URL"
curl -L --progress-bar "$PIPER_URL" -o "/tmp/$PIPER_ARCHIVE"

echo "Extracting..."
tar -xzf "/tmp/$PIPER_ARCHIVE" -C "$PIPER_DIR" --strip-components=1
chmod +x "$PIPER_DIR/piper"
rm -f "/tmp/$PIPER_ARCHIVE"

echo "  ✓ Piper binary: $PIPER_DIR/piper"
"$PIPER_DIR/piper" --version 2>/dev/null || true
echo ""

# ── 3. Download en_US-ryan-high voice model ────────────────────────────────────
# Ryan High — American male voice, closest available to a JARVIS tone in Piper
HF_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high"
MODEL_NAME="en_US-ryan-high"

echo "Downloading voice model ($MODEL_NAME)..."
echo "  source: Hugging Face rhasspy/piper-voices"
curl -L --progress-bar "$HF_BASE/${MODEL_NAME}.onnx"      -o "$VOICES_DIR/${MODEL_NAME}.onnx"
curl -L --progress-bar "$HF_BASE/${MODEL_NAME}.onnx.json" -o "$VOICES_DIR/${MODEL_NAME}.onnx.json"

echo "  ✓ Model: $VOICES_DIR/${MODEL_NAME}.onnx"
echo "  ✓ Config: $VOICES_DIR/${MODEL_NAME}.onnx.json"
echo ""

# ── 4. Smoke test ──────────────────────────────────────────────────────────────
echo "Running voice smoke test..."
echo "Jarvis online." | \
    "$PIPER_DIR/piper" \
        --model "$VOICES_DIR/${MODEL_NAME}.onnx" \
        --output_raw 2>/dev/null | \
    afplay -f raw -r 22050 -b 16 -c 1 - && \
    echo "  ✓ Voice test passed — you should have heard speech." || \
    echo "  ✗ Voice test failed. Check that afplay is available (it ships with macOS)."

echo ""
echo "========================================"
echo " Setup complete!"
echo " Run Jarvis with:"
echo "   cd $JARVIS_DIR && python main.py"
echo "========================================"
