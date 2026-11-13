"""Actual password-dialog controller with explicit fake GTK/keyring objects.

No GNOME/keyring or real password is used. Separate optional GTK tests validate
widget construction when GTK/VTE is available.
"""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
from auralyn_terminal.settings import DEFAULTS
from auralyn_terminal.update_secrets import SecretError, validate_password
from test_smart_ui import W, Dialog, Gtk as BaseGtk

ROOT=Path(__file__).resolve().parent.parent

class Switch(W):
    def set_active(self, value):
        if self.active == value:return
        self.active=value
        for name,fn,args in self.signals:
            if name=='notify::active':fn(self,None,*args)

class SecretEntry(W):
    def set_visibility(self,value):self.password_visible=value
    def set_input_purpose(self,value):self.purpose=value

class ImmediateThread:
    def __init__(self,target,**_):self.target=target
    def start(self):self.target()

class LifecycleTests(unittest.TestCase):
    def create(self, exists=False, enabled=False):
        store=Mock();store.exists.return_value=exists
        gtk=NS(**vars(BaseGtk));gtk.Entry=SecretEntry;gtk.Switch=Switch
        gtk.InputPurpose=NS(PASSWORD=8)
        node=next(n for n in ast.parse((ROOT/'auralyn_terminal/update_ui.py').read_text()).body
                  if isinstance(n,ast.ClassDef) and n.name=='UpdateSettingsDialog')
        ns={'Gtk':gtk,'GLib':NS(idle_add=lambda fn,*a:fn(*a)),
            'threading':NS(Thread=ImmediateThread),'UpdateSecretStore':Mock(return_value=store),
            'SecretError':SecretError,'validate_password':validate_password}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<real-dialog-controller>','exec'),ns)
        owner=NS(settings={**DEFAULTS,'update_use_keyring':enabled},change_setting=Mock())
        dialog=ns['UpdateSettingsDialog'](owner)
        return dialog,owner,store

    def test_dialog_field_no_readonly_window_collision(self):
        dialog,owner,_=self.create()
        self.assertIs(dialog._owner_window,owner)
        self.assertIsNone(dialog.window)

    def test_password_field_always_masked_and_empty(self):
        dialog,_,store=self.create(exists=True,enabled=True)
        self.assertFalse(dialog.password.password_visible)
        self.assertEqual(dialog.password.purpose,8)
        self.assertEqual(dialog.password.get_text(),'')
        store.lookup.assert_not_called()
        self.assertTrue(dialog.enabled.get_active())

    def test_open_only_checks_metadata_no_auth(self):
        dialog,_,store=self.create()
        store.exists.assert_called_once();store.save.assert_not_called();store.lookup.assert_not_called()
        self.assertFalse(dialog._busy)

    def test_save_uses_keyring_clears_entry_and_only_saves_boolean(self):
        dialog,owner,store=self.create()
        dialog.password.set_text('DUMMY secret test')
        def check(password):
            self.assertEqual(dialog.password.get_text(),'')
            self.assertEqual(password,'DUMMY secret test')
        store.save.side_effect=check
        dialog._save()
        store.save.assert_called_once_with('DUMMY secret test')
        self.assertTrue(dialog.enabled.get_active())
        owner.change_setting.assert_called_once_with('update_use_keyring',True)
        self.assertNotIn('DUMMY secret test',str(owner.change_setting.call_args_list))
        self.assertNotIn('DUMMY secret test',dialog.status.get_text())

    def test_invalid_password_not_stored(self):
        dialog,owner,store=self.create()
        dialog.password.set_text('')
        dialog._save()
        store.save.assert_not_called();owner.change_setting.assert_not_called()

    def test_failed_save_does_not_turn_on_storage(self):
        dialog,owner,store=self.create()
        store.save.side_effect=SecretError('Schlüsselbund gesperrt')
        dialog.password.set_text('DUMMY')
        dialog._save()
        self.assertFalse(dialog.enabled.get_active());owner.change_setting.assert_not_called()
        self.assertEqual(dialog.password.get_text(),'')
        self.assertIn('gesperrt',dialog.status.get_text())

    def test_arbitrary_backend_exception_secret_not_displayed(self):
        dialog,_,store=self.create()
        store.save.side_effect=ValueError('DO-NOT-DISPLAY-SECRET')
        dialog.password.set_text('DUMMY');dialog._save()
        self.assertNotIn('DO-NOT-DISPLAY-SECRET',dialog.status.get_text())

    def test_delete_disables_before_trying_keyring(self):
        dialog,owner,store=self.create(exists=True,enabled=True)
        def delete():self.assertFalse(dialog.enabled.get_active())
        store.delete.side_effect=delete
        dialog._remove()
        owner.change_setting.assert_called_once_with('update_use_keyring',False)
        store.delete.assert_called_once()

    def test_failed_delete_does_not_claim_removed_and_stays_disabled(self):
        dialog,_,store=self.create(exists=True,enabled=True)
        store.delete.side_effect=SecretError('Passwort NICHT gelöscht')
        dialog._remove()
        self.assertFalse(dialog.enabled.get_active())
        self.assertIn('NICHT gelöscht',dialog.status.get_text())

    def test_missing_keyring_item_disables_old_checkbox(self):
        dialog,owner,store=self.create(exists=False,enabled=True)
        self.assertFalse(dialog.enabled.get_active())
        owner.change_setting.assert_called_once_with('update_use_keyring',False)

    def test_destroy_clears_masked_entry(self):
        dialog,_,_=self.create()
        dialog.password.set_text('DUMMY')
        dialog._destroyed()
        self.assertEqual(dialog.password.get_text(),'')
        self.assertTrue(dialog._closed)
        self.assertFalse(dialog._done('save',True,True,'saved'))

    def test_busy_dialog_not_destroyed_mid_operation(self):
        dialog,_,_=self.create()
        dialog._busy=True
        self.assertTrue(dialog._delete_event())
        dialog._save();dialog._remove()
        self.assertTrue(dialog._busy)
