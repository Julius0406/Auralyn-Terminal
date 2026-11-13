"""Optional REAL GTK/VTE smoke tests, skipped when dependencies/display are absent.

Run on Ubuntu with: /usr/bin/python3 -m unittest discover -s tests -p test_gtk_smoke.py -v
This briefly opens test windows with an isolated temporary HOME/configuration.
"""
from pathlib import Path
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
AVAILABLE = False
REASON = 'GTK/VTE not checked'
try:
    import gi
    import cairo
    gi.require_foreign('cairo')
    gi.require_version('Gtk', '3.0')
    gi.require_version('Gdk', '3.0')
    gi.require_version('Vte', '2.91')
    from gi.repository import Gtk, Gdk, GLib
    if not Gtk.init_check()[0]:
        REASON = 'No graphical display available'
    else:
        from auralyn_terminal.app import Application, MainWindow
        from auralyn_terminal.completion import Candidate, parse_context
        from auralyn_terminal.settings import Settings
        AVAILABLE = True
except (ImportError, ValueError) as exc:
    REASON = f'PyGObject/GTK/VTE dependency missing: {exc}'


def drain_until(condition, timeout=4.0):
    deadline = time.monotonic() + timeout
    ctx = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while ctx.pending():
            ctx.iteration(False)
        if condition():
            return True
        time.sleep(0.01)
    return False


@unittest.skipUnless(AVAILABLE, REASON)
class RealGtkSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='auralyn-gtk-test-')
        self.home = Path(self.temp.name)
        self.environ = patch.dict(os.environ, {'HOME': str(self.home),
                                              'XDG_CONFIG_HOME': str(self.home / 'config')})
        self.environ.start()
        self.settings = Settings(self.home / 'settings.json')
        self.app = Application(self.settings, str(self.home))
        self.app.register(None)
        self.window = MainWindow(self.app, self.settings, str(self.home))
        self.window.show_all()
        self.assertTrue(drain_until(lambda: self.window.current().safe_to_query()),
                        'Test Bash did not reach its Readline prompt')

    def tearDown(self):
        self.window.destroy()
        drain_until(lambda: True, 0.1)
        self.environ.stop()
        self.temp.cleanup()

    def test_real_settings_open_close_reopen(self):
        for _ in range(3):
            self.window.open_settings()
            dialog = self.window.settings_dialog
            self.assertIsNotNone(dialog)
            self.assertTrue(dialog.get_visible())
            self.assertIs(dialog._owner_window, self.window)
            self.assertTrue(dialog.get_destroy_with_parent())
            dialog.response(Gtk.ResponseType.CLOSE)
            self.assertIsNone(self.window.settings_dialog)

    def test_real_transparency_control_and_persistence(self):
        self.window.open_settings()
        dialog = self.window.settings_dialog
        scales = [w for w in dialog.get_content_area().get_children() if isinstance(w, Gtk.Scale)]
        self.assertEqual(len(scales), 1)
        for value in (0, 100, 75):
            scales[0].set_value(value)
            self.assertEqual(self.settings['transparency'], value)
            self.assertTrue(drain_until(lambda: self.window.save_timer == 0))
            self.assertEqual(Settings(self.settings.path)['transparency'], value)

    def test_real_ctrl_shift_a_selects_vte_terminal_text(self):
        page = self.window.current()
        key = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        key.state = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        key.keyval = Gdk.KEY_a
        self.assertTrue(page._on_key(page.terminal, key))
        self.assertTrue(page.terminal.get_has_selection())
        page.terminal.unselect_all()
        self.assertFalse(page.terminal.get_has_selection())

    def test_real_ctrl_a_reaches_normal_terminal_processing(self):
        page = self.window.current()
        key = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        key.state = Gdk.ModifierType.CONTROL_MASK
        key.keyval = Gdk.KEY_a
        self.assertFalse(page._on_key(page.terminal, key))
        self.assertFalse(page.terminal.get_has_selection())

    def test_clear_keeps_live_suggestions_available_after_next_input(self):
        page = self.window.current()
        # Real VTE and Bash test (only runs when GTK is available).
        for _ in range(2):
            page.terminal.feed_child(b'clear\r')
            self.assertTrue(drain_until(lambda: page.ready and page.safe_to_query(), 4.0))
            page.terminal.feed_child(b'sud')
            self.assertTrue(drain_until(lambda: page.popup.get_visible() and
                                       any(c.value == 'sudo' for c in page.popup.items), 4.0),
                            'Popup disappeared after clear despite a new Bash prefix')
            page.terminal.feed_child(b'\x15')  # Clear typed test input.
            self.assertTrue(drain_until(lambda: page.ready and page.safe_to_query()))

    def test_real_help_widgets_and_h_callback(self):
        page = self.window.current()
        page.context = parse_context('sud', 3)
        page.popup.update([Candidate('sudo'), Candidate('ssh')])
        key = Gdk.Event.new(Gdk.EventType.KEY_PRESS)
        key.state = Gdk.ModifierType(0)
        key.keyval = Gdk.KEY_h
        self.assertFalse(page._on_key(page.terminal, key))
        page.popup.cycle(1)
        self.assertTrue(page._on_key(page.terminal, key))
        self.assertTrue(drain_until(lambda: page.popup.help_text is not None and
                                   'Administrator' in page.popup.help_text.text))
        self.assertTrue(page.popup.help_open)
        page.popup.cycle(1)
        self.assertTrue(drain_until(lambda: page.popup.help_text is not None and
                                   'verschlüsselt' in page.popup.help_text.text))
        self.assertTrue(page._on_key(page.terminal, key))
        self.assertFalse(page.popup.help_open)


    def test_real_smart_popover_reopens_and_has_magnifier(self):
        self.assertEqual(self.window.smart_button.get_tooltip_text(),
                         'Smart Search · Strg+Umschalt+F')
        for _ in range(3):
            self.window.open_smart()
            popover = self.window.smart_popover
            self.assertIsNotNone(popover)
            self.assertTrue(popover.get_visible())
            self.assertIs(popover._owner_window, self.window)
            self.assertFalse(popover.execute_button.get_sensitive())
            popover.popdown()
            self.assertTrue(drain_until(lambda: not popover.get_visible()))

    def test_real_smart_offline_answer_does_not_execute_apt(self):
        original = self.window.current()
        self.window.open_smart()
        popover = self.window.smart_popover
        popover.entry.set_text('Wie update ich mein System?')
        popover.entry.emit('activate')
        self.assertTrue(drain_until(lambda: popover._answer is not None))
        self.assertEqual(popover.command_label.get_text(), 'sudo apt update && sudo apt upgrade')
        self.assertTrue(popover.execute_button.get_sensitive())
        self.assertTrue(popover.warning_label.get_visible())
        self.assertEqual(self.window.notebook.get_n_pages(), 1)
        self.assertIs(self.window.current(), original)
        self.assertTrue(original.safe_to_query())
        # Deliberately do NOT click this system-changing action in a test.

    def test_real_smart_foreign_question_rejected(self):
        self.window.open_smart()
        popover = self.window.smart_popover
        popover.entry.set_text('Wie alt ist Elon Musk?')
        popover.entry.emit('activate')
        self.assertTrue(drain_until(lambda: popover._answer is not None))
        self.assertEqual(popover.answer_label.get_text(), 'Anfrage Abgelehnt')
        self.assertFalse(popover.command_row.get_visible())
        self.assertFalse(popover.execute_button.get_sensitive())
        self.assertEqual(self.window.notebook.get_n_pages(), 1)

    def test_real_local_ai_dialog_without_network(self):
        from auralyn_terminal.local_ai import OllamaClient
        with patch.object(OllamaClient, 'list_models') as network:
            for _ in range(2):
                self.window.open_ai_settings()
                dialog = self.window.ai_dialog
                self.assertTrue(dialog.get_visible())
                self.assertIs(dialog._owner_window, self.window)
                self.assertFalse(self.settings['smart_ai_enabled'])
                self.assertEqual(dialog.models.get_child().get_text(), 'qwen3:4b')
                dialog.response(Gtk.ResponseType.CLOSE)
                self.assertIsNone(self.window.ai_dialog)
            network.assert_not_called()

    def test_real_smart_readonly_action_new_tab_preserves_old_input(self):
        original = self.window.current()
        pending = 'echo SMART_SEARCH_KEEP_UNEXECUTED'
        original.terminal.feed_child(pending.encode())
        def old_text():
            return original.terminal.get_text(None, None)[0]
        self.assertTrue(drain_until(lambda: pending in old_text()))
        self.window.open_smart()
        popover = self.window.smart_popover
        popover.entry.set_text('Wie viel RAM ist frei?')
        popover.entry.emit('activate')
        self.assertTrue(drain_until(lambda: popover._answer is not None))
        popover.execute_button.clicked()
        self.assertEqual(self.window.notebook.get_n_pages(), 2)
        current = self.window.current()
        self.assertIsNot(current, original)
        self.assertEqual(current.smart_action, 'memory.usage')
        self.assertTrue(drain_until(current.safe_to_query))
        text = current.terminal.get_text(None, None)[0]
        self.assertIn('Smart Search beendet', text)
        self.assertIn('free -h', text)
        self.assertIn(pending, old_text())
        self.assertTrue(original.safe_to_query())


    def test_real_reported_transparents_question_opens_settings_not_a_shell_action(self):
        self.window.open_smart()
        popover = self.window.smart_popover
        popover.entry.set_text('Wie kann ich die transparents einstellen')
        popover.entry.emit('activate')
        self.assertTrue(drain_until(lambda: popover._answer is not None))
        self.assertEqual(popover._answer.entry_id, 'app.transparency')
        self.assertIn('Hintergrund-Transparenz', popover.answer_label.get_text())
        self.assertTrue(popover.ui_button.get_visible())
        self.assertFalse(popover.command_row.get_visible())
        self.assertFalse(popover.execute_button.get_sensitive())
        self.assertIsNone(self.window.settings_dialog)
        popover.ui_button.clicked()
        self.assertTrue(drain_until(lambda: self.window.settings_dialog is not None))
        self.assertTrue(self.window.settings_dialog.get_visible())
        self.assertEqual(self.window.notebook.get_n_pages(), 1)
        self.assertEqual(self.settings['transparency'], 75)

    def test_real_known_program_help_bypasses_enabled_ai(self):
        from auralyn_terminal.local_ai import OllamaClient
        self.settings.data['smart_ai_enabled'] = True
        with patch.object(OllamaClient, 'choose', side_effect=AssertionError('No model needed')) as network:
            self.window.open_smart()
            popover = self.window.smart_popover
            popover.entry.set_text('Wie kann ich die transperenz einstellen?')
            popover.entry.emit('activate')
            self.assertTrue(drain_until(lambda: popover._answer is not None))
            self.assertEqual(popover._answer.entry_id, 'app.transparency')
            self.assertIn('Programmhilfe', popover.source_label.get_text())
            network.assert_not_called()

    def test_real_github_question_shows_copyable_template_without_execution(self):
        self.window.open_smart()
        popover = self.window.smart_popover
        popover.entry.set_text('wie kann ich sachen von github runterladen')
        popover.entry.emit('activate')
        self.assertTrue(drain_until(lambda: popover._answer is not None))
        self.assertEqual(popover._answer.entry_id, 'git.clone')
        self.assertEqual(popover.command_label.get_text(), 'git clone REPOSITORY_URL')
        self.assertTrue(popover.command_row.get_visible())
        self.assertFalse(popover.execute_button.get_visible())
        self.assertFalse(popover.execute_button.get_sensitive())
        popover._execute()
        self.assertEqual(self.window.notebook.get_n_pages(), 1)
        self.assertTrue(self.window.current().safe_to_query())

    def test_real_template_then_action_restores_execute_button(self):
        self.window.open_smart()
        popover = self.window.smart_popover
        for query, action in (('Wie lade ich Sachen von GitHub herunter?', False),
                              ('Wie viel RAM ist frei?', True)):
            popover.entry.set_text(query)
            popover.entry.emit('activate')
            self.assertTrue(drain_until(lambda: popover._answer is not None))
            self.assertEqual(popover.execute_button.get_visible(), action)
            self.assertEqual(popover.execute_button.get_sensitive(), action)
        self.assertEqual(self.window.notebook.get_n_pages(), 1)

    def test_real_web_configuration_widgets(self):
        self.window.open_ai_settings()
        dialog = self.window.ai_dialog
        self.assertIsNotNone(dialog)
        self.assertFalse(dialog.web_toggle.get_active())
        dialog.web_toggle.set_active(True)
        self.assertTrue(self.settings['smart_web_enabled'])
        self.assertFalse(dialog.web_key.get_visibility())
        dialog.response(Gtk.ResponseType.CLOSE)

    def test_real_web_install_and_source_widgets_without_network(self):
        from auralyn_terminal.smart_search import Answer
        self.window.open_smart()
        view = self.window.smart_popover
        view.entry.set_text('Web source UI test')
        view._question = view.entry.get_text()
        view._receive(view._serial, Answer('Test', 'Keine echte Recherche.', command='nvidia-smi',
            sources=(('NVIDIA', 'https://docs.nvidia.com/deploy/nvidia-smi/index.html', 'page'),),
            install_command='sudo apt install git', install_note='Nur Testvorlage; nichts ausgeführt.'))
        self.assertTrue(view.links_box.get_visible())
        self.assertTrue(view.install_box.get_visible())
        self.assertFalse(view.execute_button.get_visible())
        view.entry.set_text('Neue Frage')
        self.assertFalse(view.install_box.get_visible())


if __name__ == '__main__':
    unittest.main()
