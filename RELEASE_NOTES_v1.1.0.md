# Auralyn Terminal v1.1.0 Stable

- Optional auto-update at desktop login (Settings → Auto-Update beim Login).
- Runs existing APT and Flatpak update workflow in a new tab.
- Uses existing confirmation and keyring preferences, no automatic reboot.
- See TESTBERICHT.md for testing limitations.

## Installation

Download the attached Debian package, or clone the stable source and run the installation script:

```bash
sudo apt install git python3 dpkg
git clone --branch v1.1.0 --depth 1 https://github.com/Julius0406/Auralyn-Terminal.git
cd Auralyn-Terminal
bash INSTALLIEREN.sh
```
