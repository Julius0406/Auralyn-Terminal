"""GTK/GNOME window decoration binding tests, no display needed."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auralyn_terminal.window_chrome import bind_system_window_controls


class FakeHeader:
    def __init__(self):
        self.native = False
        self.layout = None

    def set_show_close_button(self, value):
        self.native = value


class WindowChromeTests(TestCase):
    def test_gnome_layout_binding(self):
        header = FakeHeader()
        calls = []
        schema = SimpleNamespace(has_key=lambda key: key == "button-layout")
        pref = SimpleNamespace(bind=lambda key, obj, prop, flags: calls.append((key, obj, prop, flags)))
        source = SimpleNamespace(lookup=lambda name, recursive: schema)
        gio = SimpleNamespace(
            SettingsSchemaSource=SimpleNamespace(get_default=lambda: source),
            Settings=SimpleNamespace(new_full=lambda *args: pref),
            SettingsBindFlags=SimpleNamespace(GET=42),
        )
        self.assertIs(bind_system_window_controls(header, gio), pref)
        self.assertTrue(header.native)
        self.assertEqual(calls, [("button-layout", header, "decoration-layout", 42)])

    def test_other_desktop_uses_gtk_default(self):
        header = FakeHeader()
        gio = SimpleNamespace(SettingsSchemaSource=SimpleNamespace(get_default=lambda: None))
        self.assertIsNone(bind_system_window_controls(header, gio))
        self.assertTrue(header.native)
        self.assertIsNone(header.layout)

    def test_css_excludes_system_titlebuttons(self):
        source = (Path(__file__).resolve().parents[1] / "auralyn_terminal/app.py").read_text()
        self.assertIn("button:not(.titlebutton)", source)
        self.assertNotIn(".auralyn-window button {{", source)
        self.assertIn("bind_system_window_controls(header, Gio)", source)
