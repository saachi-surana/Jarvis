# Jarvis

Iron Man-style voice AI assistant running locally on macOS.

## Requirements

```
pip install -r requirements.txt
```

Ollama must be running with the llama3.2 model:

```
ollama serve
ollama pull llama3.2
```

## Voice (TTS)

Jarvis uses a three-tier TTS chain:

### 1. ElevenLabs (primary)

Deep, calm voice via the ElevenLabs API (Josh voice).

1. Get a free API key at [elevenlabs.io](https://elevenlabs.io)
2. Export it before running Jarvis:

```
export ELEVENLABS_API_KEY="your_key_here"
```

Free tier includes **10,000 characters/month**. If the key is not set or the quota is exceeded, Jarvis falls back automatically.

### 2. Piper TTS (fallback)

British male voice using the `en_GB-alan-low` model.

```
pip install piper-tts
```

Download the voice model:

```
mkdir -p ~/Projects/Jarvis/voices
curl -L "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/low/en_GB-alan-low.onnx" \
     -o ~/Projects/Jarvis/voices/en_GB-alan-low.onnx
curl -L "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/low/en_GB-alan-low.onnx.json" \
     -o ~/Projects/Jarvis/voices/en_GB-alan-low.onnx.json
```

### 3. macOS say (last resort)

Uses the built-in `say -v Daniel` (British male, ships with macOS). No setup required.

## Running

```
python main.py
```

The HUD opens in a Brave Browser app window at `http://localhost:5001`.

## Wake word

Say **"Jarvis"** to activate the microphone, or click the mic button in the HUD.

## MCP Server — Connect Jarvis to Claude Desktop

Jarvis exposes its skills as MCP (Model Context Protocol) tools so Claude Desktop can call them directly.

### Install the MCP dependency

```
pip install mcp
```

### Register with Claude Desktop

Add the Jarvis MCP server to Claude's config file:

```
~/Library/Application Support/Claude/claude_desktop_config.json
```

If the file already has an `mcpServers` key, merge in the Jarvis entry. If the file doesn't exist yet, create it. The content should be:

```json
{
  "mcpServers": {
    "jarvis": {
      "command": "python3",
      "args": ["/Users/saachisurana/Projects/Jarvis/mcp_server.py"],
      "env": {}
    }
  }
}
```

The ready-to-copy config is also saved at `jarvis_mcp_config.json` in this repo.

Restart Claude Desktop after editing the file. Claude will show a hammer icon (🔨) in the chat input when MCP tools are active.

### Available tools

| Tool | What it does |
|---|---|
| `jarvis_calendar` | Read today/tomorrow/week/next event, or create a new event |
| `jarvis_tasks` | List all tasks, list today's tasks, add a task, mark done |
| `jarvis_spotify` | Play, pause, skip, search songs/artists, set volume |
| `jarvis_studysync` | List courses, list lectures, search course materials |
| `jarvis_search` | Search across tasks, calendar, and StudySync at once |
| `jarvis_system` | Get current time or Seattle weather |

### Running the server standalone (for testing)

```
python3 mcp_server.py
```

The server communicates over stdio and is launched automatically by Claude Desktop — you don't need to keep it running manually.
