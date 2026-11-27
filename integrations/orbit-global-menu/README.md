# Orbit Global Menu integration

Auralyn Terminal supplies a per-app shortcut menu for Orbit Global Menu.

The mapping adds Auralyn-specific menus: Auralyn, Datei, Bearbeiten, Suche,
Terminal, Ansicht and Hilfe. It works with Orbit's shortcut-menu fallback,
including Wayland, and does not require the optional global-menu D-Bus
companion daemon.

Install the mapping for the current user:

    auralyn-orbit-menu-install

The installer backs up an existing custom Auralyn mapping before replacing it.
It only writes ~/.config/global-menu/shortcuts/apps/auralyn-terminal.json
(or the equivalent XDG config path), and reloads Orbit only if it is enabled.

The mapping invokes real Auralyn keyboard shortcuts. The optional Orbit
companion daemon can be installed separately if real exported GTK application
menus are desired in the future.
