# Auralyn Terminal v1.0.0 Stable

The first stable-labeled release of Auralyn Terminal for Ubuntu 26.04.

The package retains the established features of Auralyn Terminal: real Bash/GTK/VTE terminal, compact command suggestions, tabs, adjustable transparency, H command help, Smart Search with optional local Ollama and opt-in web research, one-click APT/Flatpak updater, keyboard shortcuts, run/kill, and Faceman commands.

## Download & installation

Download `auralyn-terminal_1.0.0_all.deb` and install:

```bash
sudo apt install ./auralyn-terminal_1.0.0_all.deb
```

The package has Debian version `1:1.0.0` for seamless upgrades from older installed versions, without resetting your settings. Run Auralyn as a regular user.

## Testing

693 tests passed and 21 GTK/VTE graphical tests were skipped because the required UI runtime was unavailable in the build environment. Full Ubuntu 26.04 desktop testing and real internet-backed AI responses remain unverified; the stable label is not a guarantee of zero bugs.
