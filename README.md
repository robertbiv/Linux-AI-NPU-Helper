# Linux AI NPU Assistant

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue?logo=github)](https://robertbiv.github.io/Linux-AI-NPU-Assistant/)
[![Tests](https://github.com/robertbiv/Linux-AI-NPU-Assistant/actions/workflows/docs.yml/badge.svg)](https://github.com/robertbiv/Linux-AI-NPU-Assistant/actions/workflows/docs.yml)
[![Coverage](https://robertbiv.github.io/Linux-AI-NPU-Assistant/coverage-badge.json)](https://robertbiv.github.io/Linux-AI-NPU-Assistant/coverage/)

A privacy-first AI assistant for Linux that runs entirely on the **AMD Ryzen AI NPU** — no cloud, no telemetry, no API keys required.

📖 **[Full documentation → robertbiv.github.io/Linux-AI-NPU-Assistant](https://robertbiv.github.io/Linux-AI-NPU-Assistant/)**

## Features

- 🧠 **NPU-accelerated inference** via ONNX Runtime + VitisAI (AMD Ryzen AI)
- 🦙 **Ollama & OpenAI-compatible backends** (LM Studio, Jan, etc.)
- 🔒 **100% local** — all data stays on your machine
- 🖥️ **Desktop-native UI** — automatically matches GNOME, KDE, XFCE, MATE, Cinnamon, Pantheon, Deepin, tiling WMs
- 🛠️ **10 built-in tools** — file search, web fetch, man pages, system control, app/process management
- ⚙️ **GUI settings page** — all settings sync instantly to JSON
- 🩺 **Diagnostic menu** — live status of every subsystem + integrated test runner
- 🔑 **Copilot key support** — AMD Ryzen AI laptops, ASUS, Lenovo

## Quick start

```bash
git clone https://github.com/robertbiv/Linux-AI-NPU-Assistant.git
cd Linux-AI-NPU-Assistant
pip install -r requirements.txt

# Start Ollama and pull a model
ollama serve &
ollama pull llama3.2:3b-instruct-q4_K_M

python -m src
```

## Documentation

- [Building the Flatpak locally](https://robertbiv.github.io/Linux-AI-NPU-Assistant/guides/building-flatpak/)
- [AI Model Guide — browse, add, delete models](https://robertbiv.github.io/Linux-AI-NPU-Assistant/guides/model-guide/)
- [Settings Guide](https://robertbiv.github.io/Linux-AI-NPU-Assistant/guides/settings-guide/)
- [API Reference](https://robertbiv.github.io/Linux-AI-NPU-Assistant/api/config/)

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v --cov=src
```

## NPU Model Catalog

No model is preinstalled.  Open **Settings → Models → NPU Catalog** to browse
and download any of the curated NPU-optimised models:

| Model | Publisher | Type | Size | NPU Fit | TOS |
|-------|-----------|------|------|---------|-----|
| **Phi-3-vision-128k (INT4)** | Microsoft | 👁 Vision | ~4.2 GB | ✅ Excellent | MIT |
| **Phi-3.5-vision (INT4)** | Microsoft | 👁 Vision | ~4.5 GB | ✅ Excellent | MIT |
| **PaliGemma 3B (INT4)** | Google | 👁 Vision | ~1.7 GB | ✅ Excellent | Gemma TOS |
| **Gemma 3 4B-IT (INT4)** | Google | 👁 Vision | ~2.5 GB | ✅ Good | Gemma TOS |
| **Florence-2-base** | Microsoft | 👁 Vision | ~0.6 GB | ✅ Excellent | MIT |
| **Moondream 2** | vikhyatk | 👁 Vision | ~1.8 GB | ✅ Good | Apache-2.0 |
| **Phi-3-mini-4k (INT4)** | Microsoft | 💬 Text | ~2.3 GB | ✅ Excellent | MIT |
| **Phi-3.5-mini (INT4)** | Microsoft | 💬 Text | ~2.3 GB | ✅ Excellent | MIT |
| **Qwen2.5-1.5B (INT4)** | Alibaba | 💬 Text | ~1.0 GB | ✅ Excellent | Apache-2.0 |
| **Gemma 2 2B-IT (INT4)** | Google | 💬 Text | ~1.4 GB | ✅ Good | Gemma TOS |

Models marked **Gemma TOS** require accepting [Google's Gemma Terms of Use](https://ai.google.dev/gemma/terms).
A dialog in the app shows the terms and requires your acceptance before downloading.

## License

This project is licensed under the **GNU General Public License v3.0 or later**
(GPL-3.0-or-later).  This means:

- ✅ You can use, copy, modify, and distribute this software freely
- ✅ Derivative works must also be released under the GPL
- ✅ The software will always remain free and open source
- ❌ You cannot incorporate it into proprietary (closed-source) software

See the [LICENSE](LICENSE) file for the full license text, or visit
<https://www.gnu.org/licenses/gpl-3.0.html>.

> **Note on bundled model licenses**: The AI models available in the NPU
> Catalog each carry their own license (MIT, Apache-2.0, or Gemma Terms).
> The models themselves are not part of this GPL-licensed software.
