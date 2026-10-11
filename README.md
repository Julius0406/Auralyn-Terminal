 
# ✨ Auralyn Terminal

**A modern, intelligent terminal for Ubuntu — Made by Julius.**

![Ubuntu](https://img.shields.io/badge/Ubuntu-26.04-E95420?style=for-the-badge&logo=ubuntu&logoColor=white)
![Version](https://img.shields.io/badge/Version-1.4.3_Beta_11-6366F1?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3-3776AB?style=for-the-badge&logo=python&logoColor=white)
![AI](https://img.shields.io/badge/AI-Ollama-14B8A6?style=for-the-badge)

---

### 🚀 The next generation of your Linux terminal

**Auralyn Terminal** combines the power of a real Linux shell with a modern interface, intelligent command suggestions, customizable transparency, and AI-assisted command discovery.

Built for developers, Linux enthusiasts, and everyone who wants a smarter terminal experience.

## ✨ Features

### 🎨 Modern interface

- Sleek dark design with a transparent background
- Adjustable transparency from **0% to 100%**
- **75% transparency** by default
- Multiple terminal tabs
- Customizable terminal font
- Smooth, compact interface

### ⚡ Smart Autocomplete

Get intelligent command suggestions while typing.

- Up to three visible suggestions
- Navigate suggestions using Tab
- Press H to view command explanations
- Supports Bash commands and compatible third-party completions
- Detects installed command-line tools

### 🧠 AI-Powered Smart Search

Ask questions in natural language instead of memorizing Linux commands.

**Example:**

Question: *How do I check my NVIDIA driver?*

Suggested command: `nvidia-smi`

Smart Search can:

- Understand Linux-related questions
- Research commands using optional web access
- Check whether suggested programs are installed
- Read available local command documentation
- Explain commands in simple language
- Suggest installation steps for missing tools

Powered by an optional **local Ollama AI model**, such as Qwen3.

AI-generated commands are provided for review and copying, rather than blindly executed.

### ▶️ Run & Kill

Auralyn includes additional commands for program management.

| Command | Description |
|---|---|
| `run firefox` | Launch Firefox |
| `kill firefox` | Force-stop a matching user process |
| `run --foreground htop` | Launch an interactive terminal application |

**Warning:** Force-stopping processes may result in unsaved data loss.

### 🔐 Real Linux Terminal

Auralyn isn't a simulated terminal.

It uses a real Bash shell with support for:

- `sudo` and normal Linux permissions
- APT package management
- Git, SSH, Python, and development tools
- Interactive terminal applications
- Third-party command-line programs

## 📦 Installation

**Supported platform:** Ubuntu 26.04

**Step 1 — Download**

Download the latest Ubuntu `.deb` package from [GitHub Releases](https://github.com/Julius0406/Auralyn-Terminal/releases).

**Step 2 — Install**

For version 1.4.3 Beta 11, run:

`sudo apt install ~/Downloads/auralyn-terminal_1.4.3-beta11_all.deb`

**Step 3 — Launch**

Open Auralyn Terminal from your application menu or run:

`auralyn-terminal`

## 🤖 Optional Local AI

Auralyn supports local AI through Ollama.

1. Install [Ollama](https://ollama.com).
2. Download a compatible model, for example `ollama pull qwen3:4b`.
3. Open Auralyn Terminal.
4. Click **Smart Search → Local AI**.
5. Select your model and enable local AI.

The model runs locally. Optional web research uses external search and documentation services and requires network access.

## 🛡️ Security & Privacy

- Normal Linux user permissions are respected.
- Administrator commands use standard `sudo` authentication.
- Search results do not automatically execute commands.
- AI-generated commands are not automatically trusted.
- Optional web research can be disabled.
- Auralyn does not require a cloud AI subscription.

Always inspect commands before running them, especially commands that modify system files or install software.

## 🧪 Development Status

**Current release: v1.4.3 Beta 11**

Auralyn Terminal is actively developed. Features may change, and some functions are still experimental.

Automated tests cover command suggestions, command-search logic, and terminal functionality. Full compatibility across every Linux desktop configuration is not yet guaranteed.

Found a bug or have a feature idea? Open a [GitHub Issue](https://github.com/Julius0406/Auralyn-Terminal/issues).

## 👨‍💻 Developer

**Created by Julius**

Developed with Python, GTK, VTE, Bash, and optional Ollama integration.

Made with ❤️ for Linux.

---

**⭐ If you like Auralyn Terminal, consider giving the repository a star!**

[Releases](https://github.com/Julius0406/Auralyn-Terminal/releases) · [Report a bug](https://github.com/Julius0406/Auralyn-Terminal/issues) · [Source Code](https://github.com/Julius0406/Auralyn-Terminal)
