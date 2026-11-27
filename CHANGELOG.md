# Auralyn Terminal v1.2.0 Stable — Changelog

## v1.2.0 — Orbit Global Menu integration

- Add dedicated Auralyn menus to Orbit Global Menu: Auralyn, File, Edit, Search, Terminal, View and Help.
- Add keyboard actions for New Window, About, System Update and Quit.
- Include a per-user Orbit shortcut mapping and installer command.
- Works with Orbit shortcut menus on Wayland; no optional D-Bus companion required.

---

# Auralyn Terminal v1.1.0 Stable — Changelog

## v1.1.0 — Auto-update on login

- Optional per-user desktop autostart, disabled by default.
- Launch the existing APT/Flatpak update workflow in a new tab at login.
- Preserve the existing confirmation, keyring and sudo-cleanup logic.

---

# Auralyn Terminal v1.0.1 Stable — Changelog

## v1.0.1 — GNOME-native title buttons

- Use native GTK 3 minimize, maximize and close button appearance from the active desktop theme, including WhiteSur-Dark.
- Live sync with GNOME window button placement (left/right) through the desktop button-layout preference.
- Preserve existing header bar actions, transparent background, tabs, Bash, Smart Search and updater.
- No user-specific GNOME/extension settings are changed; no GitHub release published yet.

---

# Auralyn Terminal v1.0.0 Stable — Changelog

Released: 12 November 2026

This release collects the existing Auralyn Terminal functions in a stable-labeled package; there are no new features or behavioral changes.

## Included features

- Native Bash terminal powered by GTK/VTE, tabs and sudo support
- Compact command suggestions with Tab and H explanations
- Transparency control from 0–100%, default 75%
- Smart Search, offline help, optional Ollama and opt-in web research
- Update button for APT/Flatpak with optional desktop keyring support
- Run/kill commands and Faceman fun commands
- Copy, paste, select-all shortcuts and improved popup positioning after repeated clear

## Quality status

- 714 automated test cases: 693 successful, 21 graphical tests skipped, zero failures
- Debian package internally uses version `1:1.0.0` to support upgrades from previously installed development builds
- Complete Ubuntu GUI and live external AI tests have not been performed in the build environment
