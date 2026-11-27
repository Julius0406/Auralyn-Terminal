# Auralyn Terminal v1.2.0 Stable – Testbericht

- Orbit Global Menu 1.1.4 parser accepted the Auralyn mapping: 7 menus, 17 actions, no validation warnings.
- 2 Orbit integration unit tests passed: mapping/action coverage and safe per-user installation with backup/reload.
- GTK shortcut smoke passed for Ctrl+Shift+U (system update), Ctrl+Shift+I (About), Ctrl+Q (safe close path) and Ctrl+Shift+N (opens a second window).
- Live GNOME Shell resolution matched the focused Auralyn window to the custom mapping; Orbit displayed no Auralyn mapping warnings.
- Full regression: 723 tests run, 700 passed, 21 skipped and 2 failed. The failures are in the existing completion cache and process-name force-stop tests, not in Orbit integration.
- The Orbit extension itself is not modified; integration uses its supported per-user shortcut mapping and works without the optional D-Bus companion.
