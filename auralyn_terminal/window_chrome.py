"""Use GNOME/GTK native title buttons, following desktop preferences live.

Never draw custom minimize/maximize/close buttons: the active GTK theme
(e.g. WhiteSur) owns their appearance. Binding GNOME's button-layout
also follows changes made by GNOME Tweaks or shell extensions without
touching any global desktop setting.
"""
from __future__ import annotations


def bind_system_window_controls(header, Gio):
    """Enable native controls and follow the system GNOME layout if available.

    On non-GNOME desktops leave decoration-layout unset so GTK uses its
    own gtk-decoration-layout preference. Keep the returned Gio.Settings
    alive for as long as the window exists.
    """
    header.set_show_close_button(True)
    source = Gio.SettingsSchemaSource.get_default()
    if source is None:
        return None
    schema = source.lookup("org.gnome.desktop.wm.preferences", True)
    if schema is None or not schema.has_key("button-layout"):
        return None
    preferences = Gio.Settings.new_full(schema, None, None)
    preferences.bind("button-layout", header, "decoration-layout", Gio.SettingsBindFlags.GET)
    return preferences
