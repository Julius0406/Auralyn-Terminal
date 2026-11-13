"""Opt-in update password settings. No secrets enter Settings.data or the AI.

Secret-Service calls happen off the GTK main loop; the dialog stays responsive.
No password is ever prefilled, shown, copied or printed by this UI.
"""
from __future__ import annotations
import threading
from gi.repository import Gtk, GLib
from .update_secrets import UpdateSecretStore, SecretError, validate_password


class UpdateSettingsDialog(Gtk.Dialog):
    def __init__(self, owner):
        super().__init__(title='Update-Button · Einstellungen', transient_for=owner, modal=False)
        self._owner_window = owner
        self._closed = False
        self._busy = False
        self._syncing = False
        self._store = UpdateSecretStore()
        self.set_destroy_with_parent(True)
        self.set_default_size(570, 540)
        self.get_style_context().add_class('settings-dialog')
        self.add_button('Fertig', Gtk.ResponseType.CLOSE)
        self.connect('response', self._response)
        self.connect('delete-event', self._delete_event)
        self.connect('destroy', self._destroyed)
        content = self.get_content_area()
        content.set_border_width(20)
        content.set_spacing(12)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(380)
        content.pack_start(scroll, True, True, 0)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        scroll.add(body)

        def label(text, muted=False):
            w = Gtk.Label(label=text, xalign=0)
            w.set_line_wrap(True)
            w.set_max_width_chars(62)
            if muted:
                w.get_style_context().add_class('muted')
            body.pack_start(w, False, False, 0)
            return w

        label('Systemupdates mit einem Klick')
        label('Der Pfeilkreis links neben der Lupe startet in einem neuen Tab:\nsudo apt update → sudo apt full-upgrade → flatpak update')
        confirm_row = Gtk.Box(spacing=10)
        confirm_label = Gtk.Label(label='Paketfragen automatisch bestätigen', xalign=0)
        confirm_label.set_line_wrap(True)
        self.auto_confirm = Gtk.Switch(active=owner.settings['update_auto_confirm'])
        self.auto_confirm.set_tooltip_text('Ja/Yes für diesen Update-Button. Änderungen gelten ab dem nächsten Start.')
        confirm_row.pack_start(confirm_label, True, True, 0)
        confirm_row.pack_end(self.auto_confirm, False, False, 0)
        body.pack_start(confirm_row, False, False, 0)
        self.auto_confirm.connect('notify::active', self._toggle_confirm)
        label('Standard: eingeschaltet. APT nutzt -y, Flatpak --assumeyes – keine Buchstaben-Erkennung nötig. full-upgrade kann dabei auch Pakete entfernen. Ausgeschaltet bleiben die Paketfragen interaktiv. Die Wahl gilt nur für den nächsten Button-Start, nicht für eigene Befehle.', True)
        label('Das Passwort wird ausschließlich im System-Schlüsselbund gespeichert, nicht in settings.json. Auralyn verwendet es nur für die zwei sudo-Aufrufe dieses Buttons. Smart Search und selbst eingegebene Befehle erhalten es nicht.', True)
        row = Gtk.Box(spacing=10)
        text = Gtk.Label(label='Passwort für Update-Button verwenden', xalign=0)
        self.enabled = Gtk.Switch(active=owner.settings['update_use_keyring'])
        row.pack_start(text, True, True, 0)
        row.pack_end(self.enabled, False, False, 0)
        body.pack_start(row, False, False, 0)
        self.enabled.connect('notify::active', self._toggle)
        label('Dein Linux-/sudo-Passwort (wird nicht angezeigt):')
        self.password = Gtk.Entry()
        self.password.set_visibility(False)
        self.password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.password.set_placeholder_text('Passwort eingeben oder ersetzen')
        self.password.set_max_length(1024)
        body.pack_start(self.password, False, False, 0)
        self.password.connect('activate', lambda *_: self._save())
        controls = Gtk.Box(spacing=10)
        self.save_button = Gtk.Button(label='Im Schlüsselbund speichern')
        self.delete_button = Gtk.Button(label='Gespeichertes Passwort löschen')
        self.save_button.connect('clicked', lambda *_: self._save())
        self.delete_button.connect('clicked', lambda *_: self._remove())
        controls.pack_start(self.save_button, True, True, 0)
        controls.pack_start(self.delete_button, True, True, 0)
        body.pack_start(controls, False, False, 0)
        self.status = label('Schlüsselbund wird geprüft…', True)
        label('Nach dem Update wird die sudo-Anmeldung mit sudo -K gelöscht – auch die bisherige Freigabe in anderen Terminals. Es wird keine dauerhafte NOPASSWD-Regel eingerichtet.', True)
        label('Konfigurationsfragen, ein gesperrter Schlüsselbund oder Flatpaks eigene Berechtigungsprüfung können weiterhin nachfragen. Unbekannte Dialoge werden nicht mit Tastendrücken bestätigt; keine erzwungenen Paketänderungen und kein automatischer Neustart.', True)
        label('Nur auf deinem vertrauenswürdigen Benutzerkonto speichern. Ein entsperrter Schlüsselbund ist kein Schutz vor schädlichen Programmen, die bereits unter deinem Konto laufen. Beim Speichern wird dein Systempasswort nicht geändert.', True)
        self._task('status')

    def _response(self, *_):
        if not self._busy:
            self.destroy()

    def _delete_event(self, *_):
        return self._busy

    def _destroyed(self, *_):
        self._closed = True
        self.password.set_text('')

    def _toggle(self, *_):
        if not self._syncing and not self._closed:
            self._owner_window.change_setting('update_use_keyring', self.enabled.get_active())

    def _toggle_confirm(self, *_):
        if not self._closed:
            self._owner_window.change_setting('update_auto_confirm', self.auto_confirm.get_active())

    def _save(self):
        if self._busy or self._closed:
            return
        text = self.password.get_text()
        self.password.set_text('')
        try:
            validate_password(text)
        except SecretError as exc:
            self.status.set_text(str(exc))
            return
        self._task('save', text)
        text = None

    def _remove(self):
        if self._busy or self._closed:
            return
        # Disable immediately, even when a locked keyring denies deletion.
        self.enabled.set_active(False)
        self.password.set_text('')
        self._task('delete')

    def _task(self, operation, password=None):
        self._busy = True
        for widget in (self.enabled, self.password, self.save_button, self.delete_button):
            widget.set_sensitive(False)
        self.set_response_sensitive(Gtk.ResponseType.CLOSE, False)
        self.status.set_text('Schlüsselbund wird geprüft…' if operation == 'status' else
                             'Bitte gegebenenfalls den Ubuntu-Schlüsselbund entsperren…')
        def work():
            nonlocal password
            ok = False
            exists = False
            message = ''
            try:
                if operation == 'save':
                    self._store.save(password)
                    message = 'Gespeichert. Beim nächsten Button-Update wird das Passwort verwendet. sudo prüft es erst beim Ausführen.'
                    exists = True
                elif operation == 'delete':
                    self._store.delete()
                    message = 'Passwort gelöscht. Der Button verwendet wieder die normale sudo-Abfrage.'
                else:
                    exists = self._store.exists()
                    message = ('Ein Passwort ist im Schlüsselbund hinterlegt.' if exists else
                               'Noch kein Passwort gespeichert. Ohne Eintrag bleibt die normale sudo-Abfrage.')
                ok = True
            except SecretError as exc:
                message = str(exc)
            except Exception:
                message = 'Schlüsselbund-Aufruf fehlgeschlagen. Es wurde kein Klartext-Passwort gespeichert.'
            finally:
                password = None
            GLib.idle_add(self._done, operation, ok, exists, message)
        threading.Thread(target=work, name='auralyn-keyring', daemon=True).start()

    def _done(self, operation, ok, exists, message):
        self._busy = False
        if self._closed:
            return False
        if operation == 'save' and ok:
            self.enabled.set_active(True)
        elif operation == 'status' and ok and not exists:
            self.enabled.set_active(False)
        for widget in (self.enabled, self.password, self.save_button, self.delete_button):
            widget.set_sensitive(True)
        self.set_response_sensitive(Gtk.ResponseType.CLOSE, True)
        self.status.set_text(message)
        return False
