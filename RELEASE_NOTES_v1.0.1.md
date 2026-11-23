# Auralyn Terminal v1.0.1 Stable

- Native GTK minimize/maximize/close buttons adapt to GNOME left/right arrangement live.
- The active GTK 3 theme (including WhiteSur-Dark) styles the buttons.
- No custom traffic-light buttons, no changes to GNOME preferences.
- All prior Auralyn Terminal features and application settings retained.

Quality notes: three new unit tests and a native GTK/WhiteSur window test passed. CSS parsed at three transparency values; the package installed and upgraded successfully. The full legacy test suite was not green on this live desktop: repeated Gtk.Application registration collided on D-Bus and two environment-dependent tests failed. No claim is made that full regression has passed.

Pending explicit user OK for GitHub publication.
