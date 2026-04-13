# Linux AI NPU Assistant

> A privacy-first AI assistant for Linux that runs **entirely on your AMD Ryzen AI NPU** — no cloud, no telemetry, no API keys required.

<div class="grid cards" markdown>

-   :material-chip:{ .lg .middle } **NPU-accelerated**

    ---

    Runs AI inference on the AMD Ryzen AI NPU for ultra-low power consumption.
    CPU and GPU fallbacks are supported automatically.

-   :material-lock:{ .lg .middle } **100 % local**

    ---

    All data stays on your machine. Supports Ollama, LM Studio, and direct ONNX
    model files. No API keys needed.

-   :material-tools:{ .lg .middle } **AI-powered tools**

    ---

    File search, web fetch, system control, man pages, app management,
    process info — all driven by natural language.

-   :material-cog:{ .lg .middle } **Desktop-native UI**

    ---

    Automatically matches your desktop environment (GNOME, KDE, XFCE, MATE,
    Cinnamon, Pantheon, Deepin, tiling WMs, and more).

</div>

## Quick start

```bash
# 1. Clone and install
git clone https://github.com/robertbiv/Linux-AI-NPU-Assistant.git
cd Linux-AI-NPU-Assistant
pip install -r requirements.txt

# 2. Start Ollama (or LM Studio) with any model
ollama serve &
ollama pull llama3.2:3b-instruct-q4_K_M

# 3. Run the assistant
python -m src

# 4. (Optional) build and install as a Flatpak
# See the Flatpak guide → Guides → Building the Flatpak
```

## Documentation

| Section | Description |
|---------|-------------|
| [Building the Flatpak](guides/building-flatpak.md) | Build and install a sandboxed Flatpak package locally |
| [AI Model Guide](guides/model-guide.md) | How to browse, add, and delete AI models through the GUI |
| [Settings Guide](guides/settings-guide.md) | All settings explained, with GUI and JSON reference |
| [API Reference](api/config.md) | Auto-generated module documentation |

## Test coverage

The test suite and coverage report are generated automatically on every push
and published to GitHub Pages alongside this documentation.

👉 **[View coverage report](https://robertbiv.github.io/Linux-AI-NPU-Assistant/coverage/index.html)**

## Architecture overview

```
src/
├── ai_assistant.py      # LLM client (Ollama / OpenAI-compat / NPU)
├── config.py            # YAML config with sane defaults
├── settings.py          # SettingsManager — JSON ↔ GUI sync
├── security.py          # URL guard, sanitisation, rate limiter, file perms
├── model_selector.py    # Model listing, NPU compatibility warnings
├── conversation.py      # Thread-safe chat history with secure persistence
├── os_detector.py       # Distro / DE / pkg-manager / shell detection
├── npu_manager.py       # ONNX Runtime + VitisAI provider management
├── command_executor.py  # Safe shell command execution with user confirmation
├── tools/               # Tool plugin system (FindFiles, WebFetch, ManPage …)
└── gui/
    ├── theme.py             # Desktop-environment adaptive theming
    ├── settings_window.py   # PyQt5 settings dialog (all tabs, JSON sync)
    ├── model_manager.py     # Model browser, drag-and-drop, delete
    └── diagnostic_window.py # Live status dashboard + integrated test runner
```

## Supported desktop environments

| Desktop Environment | Style | Accent |
|---------------------|-------|--------|
| GNOME / Pop!\_OS / Budgie | Fusion (Adwaita palette) | Blue `#3584e4` |
| KDE Plasma / LXQt | Native (Breeze) | Plasma blue `#3daee9` |
| XFCE | Fusion | Slate `#2d7db3` |
| MATE | Fusion | Cobalt `#729fcf` |
| Cinnamon | Fusion | Mint green `#4caf50` |
| elementary OS (Pantheon) | Fusion | Elementary blue `#0d52bf` |
| Deepin | Fusion | Deepin blue `#0081ff` |
| Tiling WMs (i3, Sway, Hyprland, Openbox) | Fusion | Indigo `#5c6bc0` |
| Unknown / fallback | Fusion | Blue `#3584e4` |
