"""Optional actual GTK/VTE construction; never run package updates or save a password."""
import unittest
from unittest.mock import Mock, patch
import test_gtk_smoke as gtk_tests

@unittest.skipUnless(gtk_tests.AVAILABLE, gtk_tests.REASON)
class UpdateGtkTests(unittest.TestCase):
    def setUp(self):
        self.host=gtk_tests.RealGtkSmokeTests()
        self.host.setUp()
        self.window=self.host.window
    def tearDown(self):self.host.tearDown()

    def test_actual_toolbar_has_adjacent_update_and_search(self):
        children=self.window.get_titlebar().get_children()
        self.assertIn(self.window.update_button,children)
        self.assertIn(self.window.smart_button,children)
        self.assertEqual(self.window.update_button.get_tooltip_text(),'Systemupdate · APT + Flatpak')

    def test_actual_keyring_dialog_is_masked_and_reopens(self):
        from auralyn_terminal.update_secrets import UpdateSecretStore
        with patch.object(UpdateSecretStore,'exists',return_value=False),patch.object(UpdateSecretStore,'lookup') as lookup:
            for _ in range(2):
                self.window.open_update_settings()
                dialog=self.window.update_dialog
                self.assertIsNotNone(dialog)
                self.assertTrue(gtk_tests.drain_until(lambda:not dialog._busy))
                self.assertFalse(dialog.password.get_visibility())
                self.assertEqual(dialog.password.get_text(),'')
                self.assertIs(dialog._owner_window,self.window)
                dialog.response(gtk_tests.Gtk.ResponseType.CLOSE)
                self.assertIsNone(self.window.update_dialog)
            lookup.assert_not_called()

    def test_actual_button_requests_new_tab_only(self):
        # Deliberately replace add_tab: no APT/Flatpak is invoked in this test.
        with patch('os.geteuid',return_value=1000),patch.object(self.window,'add_tab') as add:
            self.window.update_button.clicked()
            add.assert_called_once()
            self.assertTrue(add.call_args.kwargs['update_session'])

    def test_actual_auto_confirm_switch_persists_without_reading_password(self):
        from auralyn_terminal.update_secrets import UpdateSecretStore
        from auralyn_terminal.settings import Settings
        with patch.object(UpdateSecretStore,'exists',return_value=False),patch.object(UpdateSecretStore,'lookup') as lookup:
            self.window.open_update_settings()
            dialog=self.window.update_dialog
            self.assertTrue(gtk_tests.drain_until(lambda:not dialog._busy))
            self.assertTrue(dialog.auto_confirm.get_active())
            dialog.auto_confirm.set_active(False)
            self.assertTrue(gtk_tests.drain_until(lambda:self.window.save_timer==0))
            self.assertFalse(Settings(self.window.settings.path)['update_auto_confirm'])
            dialog.response(gtk_tests.Gtk.ResponseType.CLOSE)
            self.window.open_update_settings()
            self.assertFalse(self.window.update_dialog.auto_confirm.get_active())
            lookup.assert_not_called()
