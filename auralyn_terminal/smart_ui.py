"""Small GTK Smart Search popover and explicit local-AI configuration dialog."""
from __future__ import annotations
import os
from pathlib import Path
import threading
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango

from .local_ai import AIError, OllamaClient, valid_model_name
from .smart_catalog import ENTRIES, get_action
from .smart_search import Answer, SearchWorker
from .web_sources import public_url, WebError, read_web_key, save_web_key


def label(text='', style='', width=60):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_line_wrap(True)
    widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    widget.set_max_width_chars(width)
    if style:
        widget.get_style_context().add_class(style)
    return widget


class SmartPopover(Gtk.Popover):
    def __init__(self, owner, anchor):
        super().__init__(relative_to=anchor)
        self._owner_window = owner
        self._serial = 0
        self._destroyed = False
        self._answer: Answer | None = None
        self._question = ''
        self._origin_cwd = str(Path.home())
        self._launched = False
        self.worker = SearchWorker(lambda serial, answer: GLib.idle_add(self._receive, serial, answer),
                                   progress=lambda serial, text: GLib.idle_add(self._progress, serial, text))
        self.set_modal(True)
        self.set_position(Gtk.PositionType.BOTTOM)
        self.set_constrain_to(Gtk.PopoverConstraint.WINDOW)
        self.get_style_context().add_class('smart-popover')
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        self.body.set_border_width(16)
        self.body.set_size_request(520, -1)
        self.add(self.body)

        top = Gtk.Box(spacing=12)
        top.pack_start(label('SMART SEARCH', 'smart-title'), True, True, 0)
        self.mode_label = label('', 'micro')
        top.pack_end(self.mode_label, False, False, 0)
        self.body.pack_start(top, False, False, 0)
        search = Gtk.Box(spacing=8)
        self.entry = Gtk.SearchEntry()
        self.entry.set_placeholder_text('Wie stelle ich die Transparenz ein?')
        self.entry.set_max_length(800)
        self.entry.set_hexpand(True)
        self.entry.connect('activate', lambda *_: self._search())
        self.entry.connect('changed', self._changed)
        search.pack_start(self.entry, True, True, 0)
        self.search_button = Gtk.Button(label='Suchen')
        self.search_button.get_style_context().add_class('smart-primary')
        self.search_button.connect('clicked', lambda *_: self._search())
        search.pack_end(self.search_button, False, False, 0)
        self.body.pack_start(search, False, False, 0)
        samples = Gtk.Box(spacing=5)
        for title, question in (('System updaten', 'Wie update ich mein System?'),
                                ('RAM', 'Wie viel RAM ist frei?'),
                                ('GitHub', 'Wie kann ich Sachen von GitHub runterladen?'),
                                ('Auralyn-Hilfe', 'Was kann Auralyn Terminal?')):
            sample = Gtk.Button(label=title)
            sample.get_style_context().add_class('smart-chip')
            sample.connect('clicked', self._example, question)
            samples.pack_start(sample, False, False, 0)
        self.body.pack_start(samples, False, False, 0)
        self.body.pack_start(Gtk.Separator(), False, False, 0)

        self.result_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        self.result_scroll = Gtk.ScrolledWindow()
        self.result_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.result_scroll.set_min_content_height(95)
        self.result_scroll.set_max_content_height(240)
        self.result_scroll.set_propagate_natural_height(True)
        self.result_scroll.add(self.result_box)
        self.body.pack_start(self.result_scroll, True, True, 0)
        self.result_title = label('Befehl finden. Prüfen. Ausführen.', 'smart-result-title')
        self.result_box.pack_start(self.result_title, False, False, 0)
        self.answer_label = label('Stelle eine Frage zu Linux-Befehlen oder Auralyn Terminal.')
        self.answer_label.set_selectable(True)
        self.result_box.pack_start(self.answer_label, False, False, 0)
        self.command_row = Gtk.Box(spacing=8)
        self.command_label = label('', 'smart-command', width=45)
        self.command_label.set_selectable(True)
        self.command_label.set_hexpand(True)
        self.command_row.pack_start(self.command_label, True, True, 0)
        self.copy_button = Gtk.Button.new_from_icon_name('edit-copy-symbolic', Gtk.IconSize.BUTTON)
        self.copy_button.set_tooltip_text('Befehl kopieren (nicht ausführen)')
        self.copy_button.connect('clicked', self._copy)
        self.command_row.pack_end(self.copy_button, False, False, 0)
        self.execute_button = Gtk.Button(label='Ausführen')
        self.execute_button.get_style_context().add_class('smart-primary')
        self.execute_button.set_tooltip_text('Geprüfte Aktion in einem neuen Terminal-Tab starten')
        self.execute_button.connect('clicked', self._execute)
        self.command_row.pack_end(self.execute_button, False, False, 0)
        self.result_box.pack_start(self.command_row, False, False, 0)
        self.ui_button = Gtk.Button(label='Einstellungen öffnen')
        self.ui_button.set_halign(Gtk.Align.START)
        self.ui_button.connect('clicked', self._ui_action)
        self.result_box.pack_start(self.ui_button, False, False, 0)
        self.warning_label = label('', 'smart-warning')
        self.result_box.pack_start(self.warning_label, False, False, 0)
        self.note_label = label('', 'smart-note')
        self.note_label.set_selectable(True)
        self.result_box.pack_start(self.note_label, False, False, 0)
        self.evidence_label = label('', 'smart-note')
        self.evidence_label.set_selectable(True)
        self.result_box.pack_start(self.evidence_label, False, False, 0)
        self.install_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        self.install_box.pack_start(label('Installation (noch nicht ausgeführt)', 'smart-result-title'), False, False, 0)
        self.install_note_label = label('', 'smart-note')
        self.install_box.pack_start(self.install_note_label, False, False, 0)
        self.install_row = Gtk.Box(spacing=8)
        self.install_label = label('', 'smart-command', width=45)
        self.install_label.set_selectable(True)
        self.install_row.pack_start(self.install_label, True, True, 0)
        self.install_copy = Gtk.Button(label='Kopieren')
        self.install_copy.set_tooltip_text('Installationsvorschlag kopieren, nicht ausführen')
        self.install_copy.connect('clicked', self._copy_install)
        self.install_row.pack_end(self.install_copy, False, False, 0)
        self.install_box.pack_start(self.install_row, False, False, 0)
        self.recheck_button = Gtk.Button(label='Nach Installation erneut prüfen')
        self.recheck_button.connect('clicked', lambda *_: self._search())
        self.install_box.pack_start(self.recheck_button, False, False, 0)
        self.result_box.pack_start(self.install_box, False, False, 0)
        self.links_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.result_box.pack_start(self.links_box, False, False, 0)
        self.source_label = label('', 'micro')
        self.result_box.pack_start(self.source_label, False, False, 0)
        self.error_copy_button = Gtk.Button(label='Fehlerdetails kopieren')
        self.error_copy_button.set_halign(Gtk.Align.START)
        self.error_copy_button.set_tooltip_text('Technische Details kopieren – keine Suchfrage, KI-Antwort oder Zugangsdaten')
        self.error_copy_button.connect('clicked', self._copy_error)
        self.result_box.pack_start(self.error_copy_button, False, False, 0)

        bottom = Gtk.Box(spacing=8)
        self.spinner = Gtk.Spinner()
        bottom.pack_start(self.spinner, False, False, 0)
        bottom.pack_start(label('Auralyn- & Befehlshilfe · keine automatische Ausführung', 'micro'), True, True, 0)
        setup = Gtk.Button(label='Lokale KI…')
        setup.set_relief(Gtk.ReliefStyle.NONE)
        setup.connect('clicked', self._open_ai)
        bottom.pack_end(setup, False, False, 0)
        self.body.pack_start(bottom, False, False, 0)
        self.connect('closed', self._closed)
        self.connect('destroy', self._dispose)
        self.connect('key-press-event', self._key)

    def open(self):
        current = self._owner_window.current()
        self._origin_cwd = current.cwd if current and not current.closed else str(Path.home())
        available = self._owner_window.get_allocated_width()
        self.body.set_size_request(max(400, min(520, available - 70)), -1)
        self.result_scroll.set_max_content_height(max(95, min(250, self._owner_window.get_allocated_height() - 220)))
        self.show_all()
        self.refresh_mode()
        self._invalidate()
        self.popup()
        self.entry.grab_focus()

    def refresh_mode(self):
        enabled = self._owner_window.settings['smart_ai_enabled']
        web_enabled = self._owner_window.settings['smart_web_enabled']
        self.mode_label.set_text('KI + WEB' if enabled and web_enabled else 'LOKALE KI' if enabled else 'OFFLINE')

    def _invalidate(self):
        self._serial += 1
        self.worker.cancel()
        self._answer = None
        self._launched = False
        self.spinner.stop()
        self.spinner.hide()
        self.search_button.set_sensitive(bool(self.entry.get_text().strip()))
        self.execute_button.set_sensitive(False)
        self.command_row.hide()
        self.warning_label.hide()
        self.note_label.hide()
        self.ui_button.hide()
        self.source_label.hide()
        self.error_copy_button.hide()
        self.evidence_label.hide()
        self.install_box.hide()
        self.links_box.hide()
        self.result_title.set_text('Befehl finden. Prüfen. Ausführen.')
        self.answer_label.set_text('Stelle eine Frage zu Linux-Befehlen oder Auralyn Terminal.')

    def _changed(self, *_):
        self._invalidate()

    def _example(self, _widget, question):
        self.entry.set_text(question)
        self._search()

    def _search(self):
        question = self.entry.get_text().strip()
        if not question or self._destroyed:
            return
        self._invalidate()
        self._question = question
        current = self._owner_window.current()
        self._origin_cwd = current.cwd if current and not current.closed else str(Path.home())
        self.search_button.set_sensitive(False)
        enabled = self._owner_window.settings['smart_ai_enabled']
        self.result_title.set_text('KI recherchiert passende Befehle…' if enabled else 'Befehlshilfe wird gesucht…')
        self.answer_label.set_text('Befehle ermitteln → Suchpfad und Handbücher prüfen → Antwort. Es wird nichts ausgeführt.'
                                   if enabled else 'Offline-Regelsuche. Es wird nichts ausgeführt.')
        self.spinner.show()
        self.spinner.start()
        settings = self._owner_window.settings
        self.refresh_mode()
        if settings['smart_ai_enabled'] and settings['smart_web_enabled']:
            self.result_title.set_text('1/2 · Web-Recherche wird vorbereitet…')
            self.answer_label.set_text('Online-Dokumentation → 2/2 lokaler Suchpfad/Handbücher → bei Bedarf Installationsquelle. Es wird nichts installiert oder ausgeführt.')
            self.worker.submit(self._serial, question, True, settings['smart_ai_model'],
                               web_enabled=True, web_provider=settings['smart_web_provider'])
        else:
            self.worker.submit(self._serial, question, settings['smart_ai_enabled'], settings['smart_ai_model'])

    def _progress(self, serial, text):
        if (not self._destroyed and self.get_visible() and serial == self._serial
                and self._question == self.entry.get_text().strip() and self._answer is None):
            self.result_title.set_text(text)
        return False

    def _receive(self, serial, answer: Answer):
        if (self._destroyed or not self.get_visible() or serial != self._serial
                or self._question != self.entry.get_text().strip()):
            return False
        self._answer = answer
        self.spinner.stop()
        self.spinner.hide()
        self.search_button.set_sensitive(True)
        self.result_title.set_text(answer.title)
        self.answer_label.set_text(answer.text)
        self.command_label.set_text(answer.command)
        self.command_row.set_visible(bool(answer.command))
        self.execute_button.set_sensitive(answer.executable)
        self.execute_button.set_visible(answer.executable)
        self.copy_button.set_sensitive(bool(answer.command))
        self.copy_button.set_tooltip_text('Befehl kopieren (nicht ausführen)' if answer.executable
                                          else 'Vorlage kopieren — Platzhalter zuerst ersetzen')
        self.warning_label.set_text(answer.warning)
        self.warning_label.set_visible(bool(answer.warning))
        self.note_label.set_text(answer.note)
        self.note_label.set_visible(bool(answer.note))
        self.evidence_label.set_text(answer.evidence)
        self.evidence_label.set_visible(bool(answer.evidence))
        self.install_box.set_visible(bool(answer.install_note or answer.install_command))
        self.install_note_label.set_text(answer.install_note)
        self.install_label.set_text(answer.install_command)
        self.install_row.set_visible(bool(answer.install_command))
        self.install_copy.set_sensitive(bool(answer.install_command))
        for child in self.links_box.get_children():
            self.links_box.remove(child)
        for title, url, kind in answer.sources[:10]:
            try:
                target = public_url(url)
            except WebError:
                continue
            # Full retrieved URL is visible/selectable. Never label arbitrary
            # search results "official" merely because the model says so.
            link = Gtk.LinkButton.new_with_label(target, 'Quelle öffnen' + (' (Suchauszug)' if kind != 'page' else ''))
            link.set_halign(Gtk.Align.START)
            self.links_box.pack_start(link, False, False, 0)
            address = label(target, 'micro', width=64)
            address.set_selectable(True)
            self.links_box.pack_start(address, False, False, 0)
        self.links_box.show_all()
        self.links_box.set_visible(bool(answer.sources))
        self.source_label.set_text(answer.source)
        self.source_label.show()
        self.error_copy_button.set_visible(bool(answer.diagnostic))
        self.ui_button.set_visible(answer.ui in ('settings', 'ai'))
        self.ui_button.set_label('Lokale KI einrichten' if answer.ui == 'ai' else 'Einstellungen öffnen')
        return False

    def _current_answer(self):
        if (self._answer is None or self._launched or self._destroyed or not self.get_visible()
                or self.entry.get_text().strip() != self._question):
            return None
        return self._answer

    def _copy(self, *_):
        answer = self._current_answer()
        if answer and answer.command:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(answer.command, -1)

    def _copy_error(self, *_):
        answer = self._current_answer()
        if answer and answer.diagnostic:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(answer.diagnostic, -1)

    def _copy_install(self, *_):
        answer = self._current_answer()
        if answer and answer.install_command:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(answer.install_command, -1)

    def _execute(self, *_):
        answer = self._current_answer()
        if answer is None or not answer.executable:
            return
        action = get_action(answer.entry_id)
        if action is None:
            return
        # Disable before opening another widget so double-clicks cannot launch
        # another action. Confirmation is tied to this exact immutable entry.
        self._launched = True
        self.execute_button.set_sensitive(False)
        cwd = self._origin_cwd
        self.popdown()
        self._owner_window.launch_smart_action(action.id, cwd)

    def _ui_action(self, *_):
        answer = self._current_answer()
        if not answer:
            return
        entry = ENTRIES.get(answer.entry_id)
        if entry is None or entry.ui != answer.ui:
            return
        self.popdown()
        if entry.ui == 'settings':
            self._owner_window.open_settings()
        elif entry.ui == 'ai':
            self._owner_window.open_ai_settings()

    def _open_ai(self, *_):
        self.popdown()
        self._owner_window.open_ai_settings()

    def _key(self, _widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self.popdown()
            return True
        return False

    def _closed(self, *_):
        self._serial += 1
        self.worker.cancel()
        self._answer = None
        self.execute_button.set_sensitive(False)
        self.spinner.stop()

    def _dispose(self, *_):
        if self._destroyed:
            return
        self._destroyed = True
        self._serial += 1
        self.worker.close()


class LocalAIDialog(Gtk.Dialog):
    def __init__(self, owner):
        super().__init__(title='Smart Search · lokale KI', transient_for=owner, modal=False)
        self._owner_window = owner
        self._closed_flag = False
        self._serial = 0
        self._cancel = threading.Event()
        self._client = OllamaClient()
        self.set_destroy_with_parent(True)
        self.set_default_size(640, 660)
        self.get_style_context().add_class('settings-dialog')
        self.add_button('Fertig', Gtk.ResponseType.CLOSE)
        self.connect('response', lambda *_: self.destroy())
        self.connect('destroy', self._dispose)
        content = self.get_content_area()
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(350)
        scroll.set_propagate_natural_height(True)
        content.pack_start(scroll, True, True, 0)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        scroll.add(outer)
        outer.set_border_width(22)
        outer.set_spacing(14)
        outer.pack_start(label('Smart Search mit lokaler KI', 'smart-title'), False, False, 0)
        outer.pack_start(label('Ohne Modell: sofort nutzbare Offline-Suche, keine KI.\n'
                              'Mit Ollama: lokale KI für Terminalfragen. Mit zusätzlicher Webfreigabe: zuerst echte Online-Dokumentation, dann lokale Prüfung. Eigene Menüfragen bleiben in der Auralyn-Hilfe.'), False, False, 0)
        row = Gtk.Box(spacing=12)
        row.pack_start(label('Lokale KI mit Ollama aktivieren'), True, True, 0)
        toggle = Gtk.Switch()
        toggle.set_active(owner.settings['smart_ai_enabled'])
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.connect('notify::active', lambda widget, _: owner.change_setting('smart_ai_enabled', widget.get_active()))
        row.pack_end(toggle, False, False, 0)
        outer.pack_start(row, False, False, 0)
        outer.pack_start(label('Lokales Modell (bereits in Ollama installiert)', 'muted'), False, False, 0)
        modelrow = Gtk.Box(spacing=8)
        self.models = Gtk.ComboBoxText.new_with_entry()
        self.models.set_hexpand(True)
        self.models.append_text(owner.settings['smart_ai_model'])
        self.models.set_active(0)
        self.models.get_child().set_max_length(120)
        modelrow.pack_start(self.models, True, True, 0)
        apply_button = Gtk.Button(label='Übernehmen')
        apply_button.connect('clicked', self._apply)
        modelrow.pack_end(apply_button, False, False, 0)
        self.scan_button = Gtk.Button(label='Modelle finden')
        self.scan_button.connect('clicked', self._scan)
        modelrow.pack_end(self.scan_button, False, False, 0)
        outer.pack_start(modelrow, False, False, 0)
        self.status = label('Verbindung nur zu 127.0.0.1:11434; kein API-Schlüssel nötig.', 'muted')
        outer.pack_start(self.status, False, False, 0)
        outer.pack_start(Gtk.Separator(), False, False, 0)
        outer.pack_start(label('Web-Recherche (zusätzliche Freigabe)', 'smart-title'), False, False, 0)
        outer.pack_start(label('Eine kurze, vom Modell formulierte Suchanfrage geht an den Suchanbieter; Dokumentationsseiten sehen deine IP und den Seitenabruf. Keine Terminalausgabe oder privaten Dateien werden hochgeladen. Das Sprachmodell bleibt lokal. Bitte keine Geheimnisse eingeben.', 'muted'), False, False, 0)
        webrow = Gtk.Box(spacing=12)
        webrow.pack_start(label('Web-Recherche erlauben'), True, True, 0)
        self.web_toggle = Gtk.Switch()
        self.web_toggle.set_active(owner.settings['smart_web_enabled'])
        self.web_toggle.connect('notify::active', lambda widget, _: owner.change_setting('smart_web_enabled', widget.get_active()))
        webrow.pack_end(self.web_toggle, False, False, 0)
        outer.pack_start(webrow, False, False, 0)
        self.web_provider = Gtk.ComboBoxText()
        self.web_provider.append_text('DuckDuckGo + Online-Doku (ohne Schlüssel)')
        self.web_provider.append_text('Ollama Web Search (API-Schlüssel erforderlich)')
        self.web_provider.set_active(1 if owner.settings['smart_web_provider'] == 'ollama' else 0)
        self.web_provider.connect('changed', lambda widget: owner.change_setting('smart_web_provider', 'ollama' if widget.get_active() == 1 else 'duckduckgo'))
        outer.pack_start(self.web_provider, False, False, 0)
        outer.pack_start(label('DuckDuckGo kann Anfragen begrenzen oder blockieren. Dann werden direkte Online-Handbücher versucht; ein gescheiterter Abruf wird nicht als „kein Befehl vorhanden“ ausgegeben.', 'muted'), False, False, 0)
        keyrow = Gtk.Box(spacing=8)
        self.web_key = Gtk.Entry()
        self.web_key.set_visibility(False)
        self.web_key.set_max_length(500)
        self.web_key.set_placeholder_text('Optionaler Ollama-Web-API-Schlüssel (nicht der lokale Modellname)')
        self.web_key.set_hexpand(True)
        keyrow.pack_start(self.web_key, True, True, 0)
        save = Gtk.Button(label='Schlüssel speichern')
        save.connect('clicked', self._save_key)
        keyrow.pack_end(save, False, False, 0)
        remove = Gtk.Button(label='Löschen')
        remove.connect('clicked', self._remove_key)
        keyrow.pack_end(remove, False, False, 0)
        outer.pack_start(keyrow, False, False, 0)
        self.web_status = label('Web-Schlüssel gespeichert.' if read_web_key() else 'Kein Schlüssel gespeichert. Für DuckDuckGo nicht nötig.', 'muted')
        outer.pack_start(self.web_status, False, False, 0)
        keylink = Gtk.LinkButton.new_with_label('https://ollama.com/settings/keys', 'Ollama-Webschlüssel verwalten (optional)')
        keylink.set_halign(Gtk.Align.START)
        outer.pack_start(keylink, False, False, 0)
        outer.pack_start(Gtk.Separator(), False, False, 0)
        outer.pack_start(label('Noch kein Modell? Ollama separat installieren, dann zum Beispiel:'), False, False, 0)
        sample = label('ollama pull qwen3:4b', 'smart-command')
        sample.set_selectable(True)
        outer.pack_start(sample, False, False, 0)
        link = Gtk.LinkButton.new_with_label('https://docs.ollama.com/linux', 'Offizielle Ollama-Linux-Anleitung')
        link.set_halign(Gtk.Align.START)
        outer.pack_start(link, False, False, 0)
        outer.pack_start(label('Kein automatischer Download und keine Cloud-Sprachmodelle. Ohne Webfreigabe kein Internetzugriff durch Smart Search. An das lokale Ollama gehen die Suchfrage, eine begrenzte Auswahl installierter Befehlsnamen und relevante lokale Handbuchauszüge, bei Programmfragen auch die Auralyn-Hilfe. Kein Terminalverlauf, keine privaten Dateiinhalte oder ausgelesenen Passwörter. Bitte keine Geheimnisse in die Frage schreiben. Neue KI-Befehle sind nur Vorlagen; Ausführen bleibt auf feste Aktionen beschränkt. Nach der Recherche wird das Modell zum Entladen freigegeben; bei Abbruch kann es kurz geladen bleiben.', 'muted'), False, False, 0)

    def _save_key(self, *_):
        value = self.web_key.get_text().strip()
        if not value:
            self.web_status.set_text('Bitte einen Schlüssel eingeben oder die separate Löschen-Taste verwenden.')
            return
        try:
            save_web_key(value)
        except (WebError, OSError) as exc:
            self.web_status.set_text('Schlüssel nicht gespeichert: ' + str(exc))
            return
        self.web_key.set_text('')
        self.web_status.set_text('Schlüssel gespeichert (private Datei, Modus 600). Nur an ollama.com/api/web_search gesendet; niemals an das Modell.')
        if self._owner_window.smart_popover is not None:
            self._owner_window.smart_popover._invalidate()

    def _remove_key(self, *_):
        try:
            save_web_key('')
        except OSError:
            self.web_status.set_text('Schlüsseldatei konnte nicht gelöscht werden.')
            return
        self.web_key.set_text('')
        self.web_status.set_text('Web-Schlüssel gelöscht.')
        if self._owner_window.smart_popover is not None:
            self._owner_window.smart_popover._invalidate()

    def _apply(self, *_):
        model = self.models.get_child().get_text().strip()
        if not valid_model_name(model):
            self.status.set_text('Ungültiger Modellname. Nur lokale Modelle, z. B. qwen3:4b; keine Cloud-Modelle.')
            return
        self._owner_window.change_setting('smart_ai_model', model)
        self.status.set_text('Modell gespeichert: ' + model + '. Installation wird beim Suchen geprüft.')

    def _scan(self, *_):
        if self._closed_flag:
            return
        self._serial += 1
        serial = self._serial
        self._cancel.set()
        self._client.cancel()
        self._cancel = threading.Event()
        cancelled = self._cancel
        self.scan_button.set_sensitive(False)
        self.status.set_text('Suche installierte lokale Modelle…')
        def work():
            try:
                names = self._client.list_models(cancelled)
                error = ''
            except AIError as exc:
                names, error = [], str(exc)
            except Exception:
                names, error = [], 'Modellliste konnte nicht gelesen werden.'
            GLib.idle_add(self._models_received, serial, names, error)
        threading.Thread(target=work, name='auralyn-ollama-probe', daemon=True).start()

    def _models_received(self, serial, names, error):
        if self._closed_flag or serial != self._serial:
            return False
        self.scan_button.set_sensitive(True)
        if error:
            self.status.set_text(error)
            return False
        current = self.models.get_child().get_text()
        self.models.remove_all()
        for name in names:
            self.models.append_text(name)
        if current in names:
            self.models.set_active(names.index(current))
        elif names:
            self.models.set_active(0)
        else:
            self.models.get_child().set_text(current)
        self.status.set_text(f'{len(names)} lokale Modelle gefunden. Modell wählen und Übernehmen klicken.'
                             if names else 'Keine lokalen Textmodelle gefunden. Ein Modell muss separat installiert werden.')
        return False

    def _dispose(self, *_):
        self._closed_flag = True
        self._serial += 1
        self._cancel.set()
        self._client.cancel()
