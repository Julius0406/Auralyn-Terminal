<div align="center">

# ✨ Auralyn Terminal

### A smarter terminal. Your Linux. Your rules.

**A modern GTK/VTE terminal for Ubuntu 26.04 — made by Julius.**

[![Version](https://img.shields.io/badge/Version-v1.1.0%20Stable-17a398?style=for-the-badge)](https://github.com/Julius0406/Auralyn-Terminal/releases)
![Ubuntu](https://img.shields.io/badge/Ubuntu-26.04-E95420?style=for-the-badge&logo=ubuntu&logoColor=white)
![Python](https://img.shields.io/badge/Python-3-3776AB?style=for-the-badge&logo=python&logoColor=white)
[![License](https://img.shields.io/badge/License-MIT-6874c9?style=for-the-badge)](LICENSE)

**[📦 Releases](https://github.com/Julius0406/Auralyn-Terminal/releases) · [📖 Documentation](docs/AURALYN-HILFE.md) · [🐛 Report a bug](https://github.com/Julius0406/Auralyn-Terminal/issues)**

</div>

---

## 🚀 What is Auralyn Terminal?

**Auralyn Terminal** is a real Linux Bash terminal with a transparent interface and useful extras: compact live command suggestions, quick explanations, optional AI-powered command research, and a one-click system updater.

**v1.1.0 Stable** adds optional system updates at desktop login and retains GNOME-native window controls and all existing terminal features.

## ✨ Features

### 🍎 Native GNOME / WhiteSur window controls

The **minimize, maximize and close** buttons automatically follow the system’s **left/right button layout** and use the **active GTK 3 theme** (including WhiteSur-Dark). Change them in GNOME Tweaks, the GNOME desktop settings, or a compatible extension. Auralyn updates automatically; there is no competing application-specific left/right setting. The macOS traffic-light appearance requires a GTK theme that provides it; a GNOME Shell theme alone may not style GTK windows.


| Feature | Description |
| :--- | :--- |
| 🪟 **Modern interface** | Dark, transparent UI, tabs, customizable font, and 0–100% background transparency (75% by default). |
| ⚡ **Live autocomplete** | Up to 3 visible suggestions beside your prompt. Navigate with **Tab** and press **H** for a short explanation. |
| 💻 **Real Bash and sudo** | True GTK/VTE terminal supporting normal Linux permissions, interactive commands, Bash completions, and installed third-party CLI tools. |
| 🔎 **Smart Search** | Describe what you want to do in everyday language, view explanations, and copy command suggestions. |
| 🧠 **Optional local AI** | Connect Ollama (for example, Qwen3). Optional web research can help identify commands and check installed tools. |
| ↻ **One-click updates** | APT and Flatpak updates in a separate tab, with optional keyring-based password handling. |
| 🔄 **Auto-update on login** | Optional automatic APT/Flatpak updates when signing into the Ubuntu desktop. Off by default. |
| ▶️ **Run and kill** | Launch applications by name or force-stop your own processes. |
| 🧹 **Repeated `clear` fix** | Keep the small suggestion popup beside the prompt, even after clearing the screen many times. |
| 🎭 **Faceman commands** | `face`, `gondelface`, `luiswiththegondelface` repeatedly print `Faceman is here` until **Ctrl+C**. |

### ⌨️ Keyboard shortcuts

| Shortcut | Action |
| :--- | :--- |
| **Tab / Shift+Tab** | Browse suggestions |
| **H** | Show help for a selected command |
| **Ctrl+Shift+A** | Select all terminal text |
| **Ctrl+Shift+C** | Copy selected text |
| **Ctrl+Shift+V** | Paste, including multiple lines without the Auralyn confirmation popup |
| **Ctrl+A** | Jump to the start of the current Bash input line |
| **Ctrl+C** | Interrupt a running command |
| **Ctrl+Shift+F** | Open Smart Search |

> ⚠️ Multi-line pastes can run commands immediately, depending on the program receiving the text. Review copied commands first.

## 📦 Install on Ubuntu 26.04

### Option 1 — Download the `.deb` installer

1. Download **`auralyn-terminal_1.1.0_all.deb`** from [GitHub Releases](https://github.com/Julius0406/Auralyn-Terminal/releases/tag/v1.1.0).
2. Save it to your **Downloads** folder.
3. In your usual Ubuntu terminal, run:

```bash
sudo apt install ~/Downloads/auralyn-terminal_1.1.0_all.deb
```

### Option 2 — Install from source using Git

Clone the tagged stable release, build the Debian package locally and install it:

```bash
sudo apt install git python3 dpkg
git clone --branch v1.1.0 --depth 1 https://github.com/Julius0406/Auralyn-Terminal.git
cd Auralyn-Terminal
bash INSTALLIEREN.sh
```

Git downloads the source code, not a prebuilt installer. The install script builds the `.deb` locally and uses APT to install it and its dependencies. No GitHub account is required for the public repository.

### Launch Auralyn Terminal

Launch from the application menu or run:

```bash
auralyn-terminal
```

**Do not launch the whole application with `sudo`.** Run administrative commands inside Auralyn only when needed. Existing Auralyn settings are preserved when upgrading. The internal Debian package version is `1:1.1.0` to correctly upgrade previous installed versions.

## 🤖 Optional Ollama AI

Auralyn's built-in help works without AI. To enable local model-assisted Smart Search:

1. Install [Ollama](https://ollama.com) separately.
2. Download an example model:

   ```bash
   ollama pull qwen3:4b
   ```

3. In Auralyn, open **🔎 Smart Search → Lokale KI…**.
4. Select your installed model and enable local AI.
5. **Optional:** enable **Web-Recherche erlauben** to allow online searches and documentation lookup.

The language model runs locally; **optional web research sends searches to external services**. AI-generated commands are suggestions, not automatically executed. Always check commands for correctness.

## 🔄 Auto-update on login

Enable **Settings → Auto-Update beim Login** to open Auralyn at the next Ubuntu desktop login and run the existing APT/Flatpak workflow in a new update tab. Disabled by default. Normal app launches never start updates automatically. The per-user XDG autostart entry is removed when disabled. The same package-confirmation and optional keyring settings apply. Package removal and authentication/configuration prompts remain possible. No automatic reboot.

## 🔄 System update button

The **↻** button runs the following steps in a separate terminal tab:

```bash
sudo apt update
sudo apt full-upgrade -y
flatpak update --assumeyes
```

Normal package confirmations are accepted by default (you can turn this off in the updater settings). **`full-upgrade` can remove packages.** Special package configuration or permissions dialogs might still require your input. You can optionally save the sudo password in the desktop keyring (Secret Service); otherwise normal sudo prompts are used. The updater attempts to clear cached sudo credentials after it finishes or handles an error, but interruptions such as power loss can prevent cleanup. There is no automatic reboot.

## 🛡️ Security and development status

- Uses normal Linux user and sudo permissions — not a permanent root shell.
- Smart Search and autocomplete do **not** automatically execute suggested commands.
- Local AI and web research are opt-in features.
- Force-stopping an app can cause data loss from unsaved work.
- The **stable** label describes the release channel, not a guarantee of zero bugs.
- **v1.1.0:** 698 of 721 automated tests passed, 21 graphical tests were skipped in the headless run, and 2 previously observed tests failed. The new login-update tests and an isolated GTK test passed. The project owner confirmed the feature works on their Ubuntu desktop.

## 👨‍💻 Project

**Created by Julius** · Python · GTK 3 · VTE · Bash · optional Ollama

**Development support:** Auralyn Terminal was developed partly with the help of **ChatGPT** and **OpenAI Codex**, using **GPT-6 Astra** with **Ultra Thinking**.

[📜 Changelog](CHANGELOG.md) · [🧪 Current test report](TESTBERICHT.md) · [💬 Issues](https://github.com/Julius0406/Auralyn-Terminal/issues) · [📄 MIT License](LICENSE)

<div align="center">

**⭐ Like Auralyn Terminal? Give the repository a star!**

</div>
