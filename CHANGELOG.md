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
