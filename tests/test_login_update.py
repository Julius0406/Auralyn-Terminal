import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from types import SimpleNamespace as NS
from auralyn_terminal import login_update

ROOT = Path(__file__).resolve().parents[1]

class LoginUpdateTests(unittest.TestCase):
    def test_opt_in_and_off(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(login_update.enabled(d))
            login_update.set_enabled(True, d)
            self.assertTrue(login_update.enabled(d))
            p = login_update.entry_path(d)
            self.assertIn('Exec=/usr/bin/auralyn-terminal --login-update', p.read_text())
            login_update.set_enabled(True, d)
            login_update.set_enabled(False, d)
            login_update.set_enabled(False, d)
            self.assertFalse(p.exists())

    def test_desktop_disable_is_respected(self):
        with tempfile.TemporaryDirectory() as d:
            login_update.set_enabled(True, d)
            p = login_update.entry_path(d)
            p.write_text(p.read_text() + 'Hidden=true\n')
            self.assertFalse(login_update.enabled(d))
            login_update.set_enabled(True, d)
            self.assertTrue(login_update.enabled(d))
            p.write_text(p.read_text().replace('X-GNOME-Autostart-enabled=true','X-GNOME-Autostart-enabled=false'))
            self.assertFalse(login_update.enabled(d))

    def test_foreign_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p = login_update.entry_path(d)
            p.parent.mkdir()
            p.write_text('[Desktop Entry]\nExec=/usr/bin/false\n')
            self.assertFalse(login_update.enabled(d))
            for value in (True, False):
                with self.assertRaises(OSError):
                    login_update.set_enabled(value, d)
            self.assertIn('Exec=/usr/bin/false', p.read_text())

    def test_activation_only_for_requested_login_once(self):
        tree = ast.parse((ROOT/'auralyn_terminal/app.py').read_text())
        cls = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Application')
        method = next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='do_activate')
        window = Mock()
        ns = {'Gtk':NS(Settings=NS(get_default=lambda:Mock())), 'MainWindow':Mock(return_value=window)}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<test>','exec'),ns)
        app=NS(settings=None,cwd='/',start_login_update=False)
        ns['do_activate'](app)
        window.launch_updates.assert_not_called()
        app.start_login_update=True
        ns['do_activate'](app)
        ns['do_activate'](app)
        window.launch_updates.assert_called_once()
        self.assertFalse(app.start_login_update)
