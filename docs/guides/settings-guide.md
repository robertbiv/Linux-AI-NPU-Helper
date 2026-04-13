# Settings Guide

All settings are stored in `~/.config/linux-ai-npu-assistant/settings.json` (mode `0o600` — owner-read/write only). The GUI and JSON file are always in sync: every change made in the Settings window is written to disk immediately.

---

## Opening Settings

- Press the **Copilot key** (or `Ctrl+Alt+Space`) → click **⚙ Settings**, or
- From the tray icon menu → **Settings**.

---

## AI Backend tab

| Setting | JSON key | Default | Description |
|---------|----------|---------|-------------|
| Backend | `backend` | `ollama` | `ollama`, `openai`, or `npu` |
| Ollama URL | `ollama.base_url` | `http://localhost:11434` | Ollama server URL |
| Ollama model | `ollama.model` | `llava` | Model tag |
| Ollama timeout | `ollama.timeout` | `120` | Seconds before request times out |
| OpenAI URL | `openai.base_url` | `http://localhost:1234/v1` | LM Studio / Jan / etc. |
| OpenAI model | `openai.model` | `local-model` | Model identifier |
| OpenAI API key env | `openai.api_key_env` | `` | Env var holding the API key |
| NPU model path | `npu.model_path` | `` | Path to `.onnx` file |
| NPU provider | `npu.provider` | `VitisAIExecutionProvider` | ONNX EP |

---

## Models tab

See the full [AI Model Guide](model-guide.md).

---

## Tools tab

| Setting | JSON key | Default | Description |
|---------|----------|---------|-------------|
| Allowed tools | `tools.allowed` | `["*"]` | Glob patterns of permitted tools |
| Disallowed tools | `tools.disallowed` | `[]` | Tools always blocked |
| Requires approval | `tools.requires_approval` | `["system_control","app"]` | User confirms before run |
| Unload after use | `tools.unload_after_use` | `true` | Free RAM after each tool call |
| Max results | `tools.max_results` | `20` | Limit search tool results |
| Search path | `tools.search_path` | `~` | Root directory for FindFiles/SearchInFiles |

---

## Security tab

| Setting | JSON key | Default | Description |
|---------|----------|---------|-------------|
| Allow external network | `network.allow_external` | `false` | If `false`, AI backend must be on localhost/LAN |
| Rate limit (calls/min) | `security.rate_limit_per_minute` | `0` | `0` = unlimited |
| Check file permissions | `security.check_file_permissions` | `true` | Warn if config/history is world-readable |
| Confirm commands | `safety.confirm_commands` | `true` | Show confirmation dialog before running shell commands |

---

## Appearance tab

| Setting | JSON key | Default | Description |
|---------|----------|---------|-------------|
| Position | `appearance.position` | `top-right` | Where the overlay appears |
| Width (px) | `appearance.width` | `420` | Overlay panel width |
| Opacity | `appearance.opacity` | `0.95` | 0.0–1.0 |
| Font size (pt) | `appearance.font_size` | `0` | `0` = use system default |
| Always on top | `appearance.always_on_top` | `true` | Keep window above other windows |

---

## Example `settings.json`

```json
{
  "backend": "ollama",
  "hotkey": "copilot",
  "ollama": {
    "base_url": "http://localhost:11434",
    "model": "llama3.2:3b-instruct-q4_K_M",
    "timeout": 120
  },
  "network": {
    "allow_external": false
  },
  "security": {
    "rate_limit_per_minute": 30,
    "check_file_permissions": true
  },
  "safety": {
    "confirm_commands": true
  },
  "tools": {
    "allowed": ["*"],
    "disallowed": [],
    "requires_approval": ["system_control", "app"],
    "unload_after_use": true,
    "max_results": 20
  }
}
```
