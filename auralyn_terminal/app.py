"""GTK/VTE frontend. Actual commands and authentication stay in the PTY."""
from __future__ import annotations
import argparse
import os
import re
import signal
import sys
import termios
import time
from pathlib import Path

import gi
import cairo
gi.require_foreign("cairo")
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Vte", "2.91")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, Vte

from . import __version__
from .completion import Candidate, CompletionWorker, Context, parse_context, replacement
from .command_help import HelpText, HelpWorker
from .protocol import SessionIPC
from .settings import DEFAULTS, Settings
from .terminal_state import is_readline_foreground, suggestion_viewport_row
from .smart_catalog import get_action

ROOT = Path(__file__).resolve().parent.parent
QUERY_SEQUENCE = b"\x1b[989;1~"
APPLY_SEQUENCE = b"\x1b[989;2~"


def rgba(value: str, alpha: float | None = None):
    color = Gdk.RGBA()
    color.parse(value)
    if alpha is not None:
        color.alpha = alpha
    return color


def button(icon: str, tooltip: str, callback):
    widget = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
    widget.set_relief(Gtk.ReliefStyle.NONE)
    widget.set_tooltip_text(tooltip)
    widget.connect("clicked", callback)
    return widget


class Suggestions(Gtk.EventBox):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.set_visible_window(False)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)
        self.get_style_context().add_class("suggestions")
        self.connect("draw", self._draw_surface)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.body.set_border_width(9)
        self.add(self.body)
        self.items: list[Candidate] = []
        self.selected = -1
        self.help_open = False
        self.help_text: HelpText | None = None
        self.help_generation = 0
        self.set_no_show_all(True)

    @staticmethod
    def _draw_surface(widget, cr):
        # Windowless EventBoxes otherwise do not paint their CSS background.
        style = widget.get_style_context()
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        Gtk.render_background(style, cr, 0, 0, width, height)
        Gtk.render_frame(style, cr, 0, 0, width, height)
        return False

    def clear(self):
        self.items = []
        self.selected = -1
        self.help_open = False
        self.help_text = None
        self.help_generation += 1
        self.page.help_worker.cancel()
        self.hide()

    def update(self, items: list[Candidate]):
        self.clear()
        self.items = items
        self.render()

    def toggle_help(self):
        if not 0 <= self.selected < len(self.items):
            return
        if self.help_open:
            self.close_help()
            return
        self.help_open = True
        self._request_help()
        self.render()

    def close_help(self):
        self.help_open = False
        self.help_text = None
        self.help_generation += 1
        self.page.help_worker.cancel()
        self.render()

    def _request_help(self):
        self.help_generation += 1
        self.help_text = HelpText(self.items[self.selected].display,
                                  "Kurzbeschreibung wird geladen…", "Lokal · ohne Cloud")
        if self.page.context is not None:
            self.page.help_worker.submit(self.help_generation, self.page.context,
                                         self.items[self.selected], self.page.cwd)

    def receive_help(self, generation: int, result: HelpText):
        if (self.page.closed or generation != self.help_generation or
                not self.help_open or not self.get_visible() or
                not self.page.safe_to_query()):
            return False
        self.help_text = result
        self.render()
        return False

    def cycle(self, direction: int):
        if not self.items:
            return
        if self.selected < 0:
            self.selected = 0 if direction > 0 else len(self.items) - 1
        else:
            self.selected = (self.selected + direction) % len(self.items)
        if self.help_open:
            self._request_help()
        self.render()

    def render(self):
        for child in self.body.get_children():
            self.body.remove(child)
            child.destroy()
        if not self.items:
            self.hide()
            return
        limit = self.page.window.settings["suggestion_rows"]
        if self.help_open and self.page.overlay.get_allocated_height() < 400:
            limit = min(limit, 2)
        start = max(0, self.selected - limit + 1)
        end = min(len(self.items), start + limit)
        heading = Gtk.Box(spacing=20)
        title = Gtk.Label(label="VORSCHLÄGE", xalign=0)
        title.get_style_context().add_class("micro")
        counter = Gtk.Label(label=f"{start + 1}–{end} / {len(self.items)}", xalign=1)
        counter.get_style_context().add_class("micro")
        heading.pack_start(title, True, True, 2)
        heading.pack_end(counter, False, False, 2)
        self.body.pack_start(heading, False, False, 2)
        for index in range(start, end):
            candidate = self.items[index]
            event = Gtk.EventBox()
            event.set_visible_window(False)
            event.get_style_context().add_class("suggestion-row")
            event.connect("draw", self._draw_surface)
            if index == self.selected:
                event.get_style_context().add_class("selected")
            row = Gtk.Box(spacing=12)
            row.set_border_width(7)
            name = Gtk.Label(label=candidate.display, xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.set_max_width_chars(35)
            name.get_style_context().add_class("command-name")
            kind = Gtk.Label(label=candidate.kind)
            kind.get_style_context().add_class("micro")
            row.pack_start(name, True, True, 0)
            row.pack_end(kind, False, False, 0)
            event.add(row)
            event.connect("button-press-event", self._clicked, index)
            self.body.pack_start(event, False, False, 0)
        if self.help_open and self.help_text is not None:
            self.body.pack_start(Gtk.Separator(), False, False, 4)
            info = self.help_text
            help_title = Gtk.Label(label="KURZHILFE · " + info.title, xalign=0)
            help_title.set_ellipsize(Pango.EllipsizeMode.END)
            help_title.set_max_width_chars(40)
            help_title.get_style_context().add_class("help-title")
            self.body.pack_start(help_title, False, False, 2)
            text = Gtk.Label(label=info.text, xalign=0)
            text.set_line_wrap(True)
            text.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            text.set_max_width_chars(42)
            text.set_lines(4)
            text.set_ellipsize(Pango.EllipsizeMode.END)
            text.set_tooltip_text(info.text)
            text.get_style_context().add_class("help-description")
            self.body.pack_start(text, False, False, 2)
            source = Gtk.Label(label=info.source, xalign=0)
            source.get_style_context().add_class("micro")
            self.body.pack_start(source, False, False, 2)
        hint = Gtk.Label(label="Tab  wechseln · Enter  einsetzen\nH  Kurzhilfe · Esc  schließen", xalign=0)
        hint.get_style_context().add_class("hint")
        self.body.pack_start(hint, False, False, 3)
        self.body.show_all()
        self.show()
        self.page.position_suggestions()

    def _clicked(self, _widget, event, index):
        if event.button == 1:
            self.selected = index
            self.page.accept_suggestion()
            return True
        return False


class TerminalPage(Gtk.Box):
    def __init__(self, window, cwd: str, smart_action: str | None = None, *, update_session: bool = False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        if smart_action is not None and get_action(smart_action) is None:
            raise ValueError("Unbekannte Smart-Search-Aktion")
        if smart_action is not None and update_session:
            raise ValueError("Update und Smart Search brauchen getrennte Tabs.")
        self.update_session = update_session
        self.smart_action = smart_action
        self.window = window
        self.cwd = cwd
        self.path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        self.shell_names: list[str] = []
        self.pid = 0
        self.ready = False
        self.closed = False
        self.searching = False
        self.prefix_key = False
        self.injecting = False
        self.serial = 0
        self.snapshot_timer = 0
        self.snapshot_outstanding = False
        self.query_serial = None
        self.last_snapshot: tuple[str, int] | None = None
        self.context: Context | None = None
        self.ipc = SessionIPC()
        self.worker = CompletionWorker(ROOT / "shell" / "native-complete.bash", self._worker_deliver)
        self.help_worker = HelpWorker(self._help_deliver)
        self.io_watch = GLib.io_add_watch(self.ipc.fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self._on_events)

        self.overlay = Gtk.Overlay()
        self.terminal = Vte.Terminal()
        self.terminal.set_hexpand(True)
        self.terminal.set_vexpand(True)
        self.terminal.set_scrollback_lines(window.settings["scrollback"])
        self.terminal.set_scroll_on_output(False)
        self.terminal.set_scroll_on_keystroke(True)
        self.terminal.set_mouse_autohide(True)
        self.terminal.set_audible_bell(False)
        self.terminal.set_allow_hyperlink(True)
        self.terminal.set_bold_is_bright(False)
        self.terminal.get_style_context().add_class("terminal-area")
        self.overlay.add(self.terminal)
        self.popup = Suggestions(self)
        self.overlay.add_overlay(self.popup)
        self.overlay.set_overlay_pass_through(self.popup, False)
        self.pack_start(self.overlay, True, True, 0)

        self.tab_box = Gtk.Box(spacing=8)
        self.tab_label = Gtk.Label(label="Systemupdate" if update_session else "Smart Search" if smart_action else "Bash")
        self.tab_label.set_max_width_chars(22)
        self.tab_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.tab_box.pack_start(self.tab_label, True, True, 0)
        self.tab_box.pack_end(button("window-close-symbolic", "Tab schließen", lambda _: window.close_tab(self)), False, False, 0)
        self.tab_box.show_all()

        self.terminal.connect("commit", self._on_commit)
        self.terminal.connect("key-press-event", self._on_key)
        self.terminal.connect("button-press-event", self._on_mouse)
        self.terminal.connect("child-exited", self._on_exit)
        self.connect("destroy", lambda *_: self.dispose())
        self.terminal.connect("cursor-moved", lambda *_: self.position_suggestions())
        self.terminal.connect("size-allocate", lambda *_: self.position_suggestions())
        self.terminal.get_vadjustment().connect("value-changed", self._on_scroll)
        self.apply_settings()
        GLib.idle_add(self._spawn)

    def _spawn(self):
        if self.closed:
            return False
        env = dict(os.environ)
        env.update({
            "TERM": "xterm-256color", "COLORTERM": "truecolor",
            "TERM_PROGRAM": "AuralynTerminal", "TERM_PROGRAM_VERSION": __version__,
            "AURALYN_EVENT_FIFO": str(self.ipc.fifo),
            "AURALYN_SESSION_DIR": str(self.ipc.directory),
        })
        env.pop("BASH_ENV", None)
        # VTE allocates a real controlling PTY. Ordinary sessions are unchanged.
        # Smart Search receives only a reviewed action ID, in its OWN fresh PTY.
        argv = (["/usr/bin/python3", "-I", str(ROOT / "smart_launcher.py"), self.smart_action]
                if self.smart_action else
                ["/bin/bash", "--rcfile", str(ROOT / "shell" / "bashrc.bash"), "-i"])
        if self.update_session:
            argv = ["/usr/bin/python3", "-I", str(ROOT / "update_launcher.py")]
            if self.window.settings["update_use_keyring"]:
                argv.append("--saved-password")
            if self.window.settings["update_auto_confirm"]:
                argv.append("--assume-yes")
        self.terminal.spawn_async(
            Vte.PtyFlags.DEFAULT, self.cwd,
            argv,
            [f"{key}={value}" for key, value in env.items()],
            GLib.SpawnFlags.DEFAULT, None, None, -1, None, self._spawn_done, None,
        )
        return False

    def _spawn_done(self, _terminal, pid, error, _data=None):
        if self.closed:
            return
        if error is not None:
            self.update_session = False
            self.window.show_error("Terminal konnte nicht gestartet werden", str(error))
            return
        self.pid = pid
        self.terminal.grab_focus()

    def _on_events(self, _fd, condition):
        if self.closed:
            return False
        try:
            messages = self.ipc.receive()
        except OSError:
            return False
        for kind, fields in messages:
            if kind == "P":
                try:
                    shell_pid = int(fields[0])
                except ValueError:
                    continue
                if self.pid and shell_pid != self.pid:
                    continue
                self.pid = shell_pid
                self.cwd, self.path = fields[1:3]
                self.shell_names = fields[3].splitlines()
                self.ready = True
                self.update_session = False  # The wrapper exec'd the ordinary Bash.
                self.searching = False
                self.prefix_key = False
                self.snapshot_outstanding = False
                self.query_serial = None
                self.last_snapshot = None
                self.invalidate()
                self.tab_label.set_text(Path(self.cwd).name or "/")
                self.window.refresh_status()
            elif kind == "B":
                self.mark_busy()
            elif kind == "S":
                self.snapshot_outstanding = False
                if self.query_serial is not None and self.query_serial != self.serial:
                    self.schedule_snapshot(1)
                    continue
                if not self.safe_to_query() or not self.window.settings["suggestions"]:
                    continue
                try:
                    point = int(fields[0])
                except ValueError:
                    continue
                self.cwd, self.path, line = fields[1:]
                self.last_snapshot = (line, point)
                ctx = parse_context(line, point)
                self.context = ctx
                self.serial += 1
                if ctx is None or not line.strip():
                    self.popup.clear()
                    continue
                self.worker.submit(self.serial, ctx, self.cwd, self.path, list(self.shell_names), self.window.settings["native_completion"])
        return True

    def safe_to_query(self) -> bool:
        if self.closed or not self.ready or self.searching or self.prefix_key or self.pid <= 0:
            return False
        try:
            pty = self.terminal.get_pty()
            if pty is None:
                return False
            fd = pty.get_fd()
            # Readline disables BOTH canonical mode and echo. Password reads
            # are gated by PS0 and additionally by foreground/terminal mode.
            return is_readline_foreground(fd, self.pid, self.ready)
        except (OSError, termios.error):
            return False

    def foreground_job(self) -> bool:
        if self.closed or self.pid <= 0:
            return False
        try:
            return os.tcgetpgrp(self.terminal.get_pty().get_fd()) != self.pid or not self.ready
        except (OSError, AttributeError):
            return False

    def invalidate(self):
        self.serial += 1
        self.context = None
        self.popup.clear()
        self.worker.engine.cancel()

    def mark_busy(self):
        self.ready = False
        self.last_snapshot = None
        self.snapshot_outstanding = False
        self.invalidate()
        if self.snapshot_timer:
            GLib.source_remove(self.snapshot_timer)
            self.snapshot_timer = 0
        self.window.refresh_status()

    def _on_commit(self, _terminal, text: str, _length: int):
        if self.injecting or self.closed:
            return
        # Invalidate BEFORE scheduling, so stale results cannot be accepted.
        self.invalidate()
        if any(c in text for c in ("\r", "\n", "\x03", "\x0f")):
            self.mark_busy()
            return
        if "\x04" in text and self.last_snapshot and not self.last_snapshot[0]:
            self.mark_busy()
            return
        if "\x12" in text or "\x13" in text:  # Readline reverse/forward search.
            self.searching = True
            return
        if self.searching:
            if "\x07" in text or text == "\x1b":
                self.searching = False
            else:
                return
        if text == "\x18":  # Do not interrupt a multi-key Readline chord.
            self.prefix_key = True
            return
        if self.prefix_key:
            self.prefix_key = False
        if text == "\x1b":
            return
        self.schedule_snapshot()

    def schedule_snapshot(self, delay: int = 85):
        if self.snapshot_timer:
            GLib.source_remove(self.snapshot_timer)
        self.snapshot_timer = 0
        if self.window.settings["suggestions"] and self.safe_to_query():
            self.snapshot_timer = GLib.timeout_add(delay, self._request_snapshot)

    def _request_snapshot(self):
        self.snapshot_timer = 0
        if self.safe_to_query() and not self.snapshot_outstanding:
            self.snapshot_outstanding = True
            self.query_serial = self.serial
            self._feed_private(QUERY_SEQUENCE)
        return False

    def _feed_private(self, data: bytes):
        self.injecting = True
        try:
            self.terminal.feed_child(data)
        finally:
            self.injecting = False

    def _help_deliver(self, generation: int, result: HelpText):
        GLib.idle_add(self.popup.receive_help, generation, result)

    def _worker_deliver(self, serial, context, candidates):
        GLib.idle_add(self._show_results, serial, context, candidates)

    def _show_results(self, serial, context, candidates):
        if self.closed or serial != self.serial or not self.safe_to_query() or not self.window.settings["suggestions"]:
            return False
        self.context = context
        self.popup.update(candidates)
        return False

    def accept_suggestion(self):
        index = self.popup.selected
        if not self.safe_to_query() or self.context is None or self.last_snapshot is None or not 0 <= index < len(self.popup.items):
            self.popup.clear()
            return
        candidate = self.popup.items[index]
        line, point = self.last_snapshot
        new_line, new_point = replacement(self.context, candidate)
        try:
            self.ipc.write_replacement(line, point, new_line, new_point)
        except OSError as exc:
            self.window.show_error("Vorschlag konnte nicht eingesetzt werden", str(exc))
            return
        self.invalidate()
        self.query_serial = self.serial
        self._feed_private(APPLY_SEQUENCE)
        self.terminal.grab_focus()

    def select_terminal_all(self):
        """Select terminal output/scrollback without sending input to the PTY."""
        self.popup.clear()
        self.terminal.select_all()

    def _on_key(self, _terminal, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(event.state & Gdk.ModifierType.MOD1_MASK)
        key = event.keyval
        other_mod = bool(event.state & (Gdk.ModifierType.MOD4_MASK |
                                        Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.META_MASK))
        if ctrl and shift and not alt and not other_mod and Gdk.keyval_to_lower(key) == Gdk.KEY_a:
            self.select_terminal_all()
            return True
        if ctrl and shift and not alt and not other_mod:
            low = Gdk.keyval_to_lower(key)
            if low == Gdk.KEY_c:
                self.terminal.copy_clipboard_format(Vte.Format.TEXT)
                return True
            if low == Gdk.KEY_v:
                self.request_paste()
                return True
        if shift and not ctrl and key == Gdk.KEY_Insert:
            self.request_paste()
            return True
        if ctrl and key == Gdk.KEY_space:
            self.invalidate()
            self.schedule_snapshot(1)
            return True
        modified = bool(event.state & (Gdk.ModifierType.MOD4_MASK |
                                       Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.META_MASK))
        if self.popup.get_visible() and self.popup.items and not ctrl and not alt and not modified:
            if not self.safe_to_query():
                self.popup.clear()
                return False
            if Gdk.keyval_to_lower(key) == Gdk.KEY_h and self.popup.selected >= 0:
                self.popup.toggle_help()
                return True
            if key in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
                self.popup.cycle(-1 if shift or key == Gdk.KEY_ISO_Left_Tab else 1)
                return True
            if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_Right) and self.popup.selected >= 0:
                self.accept_suggestion()
                return True
            if key == Gdk.KEY_Escape:
                if self.popup.help_open:
                    self.popup.close_help()
                else:
                    self.invalidate()
                return True
        return False

    def _on_mouse(self, _terminal, event):
        if event.button == 3:
            menu = Gtk.Menu()
            for label, action in (
                ("Alles markieren (Strg+Umschalt+A)", self.select_terminal_all),
                ("Kopieren (Strg+Umschalt+C)", lambda: self.terminal.copy_clipboard_format(Vte.Format.TEXT)),
                ("Einfügen (Strg+Umschalt+V)", self.request_paste),
                ("Neuer Tab", lambda: self.window.add_tab(self.cwd)),
                ("Terminal-Einstellungen", self.window.open_settings),
            ):
                item = Gtk.MenuItem(label=label)
                item.connect("activate", lambda _item, callback=action: callback())
                menu.append(item)
            menu.show_all()
            menu.popup_at_pointer(event)
            return True
        if event.button == 2:
            Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY).request_text(self._paste_received, None)
            return True
        if event.button == 1:
            self.popup.clear()
        return False

    def request_paste(self):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).request_text(self._paste_received, None)

    def _paste_received(self, _clipboard, text, _data=None):
        if self.closed or not text:
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = "".join(c for c in text if ord(c) >= 32 and ord(c) != 127 or c in "\n\t")
        if not text:
            return
        # Explicit terminal paste is immediate, including multiline clipboard text.
        # VTE uses bracketed paste when the active terminal program supports it.
        # Preserve internal line breaks, but remove final newlines so a copied
        # command doesn't automatically submit itself just because it ended in LF.
        to_paste = text.rstrip("\n")
        if not to_paste:
            return
        self.popup.clear()  # No stale completion overlay after an explicit paste.
        self.terminal.paste_text(to_paste)
        self.terminal.grab_focus()

    def _on_scroll(self, *_):
        if self.popup.get_visible():
            self.position_suggestions()

    def position_suggestions(self):
        if not self.popup.get_visible() or self.closed:
            return
        width = self.overlay.get_allocated_width()
        height = self.overlay.get_allocated_height()
        if width < 100 or height < 100:
            return
        col, row = self.terminal.get_cursor_position()
        adjustment = self.terminal.get_vadjustment()
        char_h = max(1, self.terminal.get_char_height())
        char_w = max(1, self.terminal.get_char_width())
        # GTK3/VTE usually reports the adjustment in terminal rows.  Some
        # newer configurations use pixels instead, so normalize both forms.
        scroll_unit = char_h if self.terminal.get_scroll_unit_is_pixels() else 1
        on_screen_row = suggestion_viewport_row(
            row, adjustment.get_value() / scroll_unit,
            adjustment.get_upper() / scroll_unit,
            adjustment.get_page_size() / scroll_unit,
            height / char_h,
        )
        if on_screen_row is None:
            self.popup.hide()  # User is reading older scrollback; avoid a ghost popup.
            return
        cursor_y = int(on_screen_row * char_h) + 12
        popup_w = min(400, width - 24)
        self.popup.set_size_request(popup_w, -1)
        # Query the content, not the overlay widget: the latter includes its
        # positioning margins and would create a size/position feedback loop.
        popup_h = self.popup.body.get_preferred_height_for_width(max(1, popup_w - 2))[1] + 2
        prefix_len = len(self.context.prefix) if self.context else 0
        x = max(12, min(width - popup_w - 12, (col - prefix_len) * char_w + 14))
        y = cursor_y - popup_h - 8
        # At the top of the screen there is no room above; stay inside the window.
        if y < 8:
            y = min(height - popup_h - 8, cursor_y + char_h + 8)
        self.popup.set_margin_start(max(0, int(x)))
        self.popup.set_margin_top(max(0, int(y)))

    def apply_settings(self):
        settings = self.window.settings
        self.terminal.set_font(Pango.FontDescription.from_string(settings["font"]))
        self.terminal.set_scrollback_lines(settings["scrollback"])
        self.terminal.set_cursor_blink_mode(Vte.CursorBlinkMode.ON if settings["cursor_blink"] else Vte.CursorBlinkMode.OFF)
        shapes = {"block": Vte.CursorShape.BLOCK, "ibeam": Vte.CursorShape.IBEAM, "underline": Vte.CursorShape.UNDERLINE}
        self.terminal.set_cursor_shape(shapes[settings["cursor_shape"]])
        palette = ["#18202d", "#f07489", "#7bd5a3", "#ebcf83", "#82aaff", "#c5a1ff", "#73daca", "#dfe6f2",
                   "#68758b", "#ff91a4", "#9ce6bd", "#ffe3a2", "#a6c1ff", "#debdff", "#a0f0e3", "#ffffff"]
        self.terminal.set_colors(rgba("#f0f4fc"), rgba("#101622", settings.alpha), [rgba(c) for c in palette])
        self.terminal.set_color_cursor(rgba("#98eddd"))
        self.terminal.set_color_cursor_foreground(rgba("#101622"))
        self.terminal.set_color_highlight(rgba("#5277a5", 0.7))
        self.terminal.set_color_highlight_foreground(rgba("#ffffff"))
        if not settings["suggestions"]:
            self.invalidate()
        elif self.popup.get_visible():
            self.popup.render()

    def _on_exit(self, _terminal, _status):
        if not self.closed:
            self.window.remove_tab(self)

    def dispose(self):
        if self.closed:
            return
        self.closed = True
        self.worker.close()
        self.help_worker.close()
        if self.snapshot_timer:
            GLib.source_remove(self.snapshot_timer)
        if self.io_watch:
            GLib.source_remove(self.io_watch)
        self.ipc.close()


class SettingsDialog(Gtk.Dialog):
    def __init__(self, window):
        super().__init__(title="Terminal-Einstellungen", transient_for=window, modal=False)
        # Do NOT assign self.window: GtkDialog has a read-only C field with
        # that name. That caused "RuntimeError: field is not writable" in an early implementation.
        self._owner_window = window
        self.set_destroy_with_parent(True)
        self.set_default_size(590, 680)
        self.get_style_context().add_class("settings-dialog")
        self.add_button("Fertig", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda *_: self.destroy())
        outer = self.get_content_area()
        outer.set_border_width(22)
        outer.set_spacing(16)
        title = Gtk.Label(xalign=0)
        title.set_markup("<span size='x-large' weight='bold'>Dein Terminal. Dein Look.</span>")
        outer.pack_start(title, False, False, 0)
        desc = Gtk.Label(label="Änderungen werden sofort übernommen und gespeichert.", xalign=0)
        outer.pack_start(desc, False, False, 0)
        row = Gtk.Box()
        row.pack_start(Gtk.Label(label="Hintergrund-Transparenz", xalign=0), True, True, 0)
        self.percent = Gtk.Label(label=f"{window.settings['transparency']} %")
        self.percent.get_style_context().add_class("accent")
        row.pack_end(self.percent, False, False, 0)
        outer.pack_start(row, False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        scale.set_draw_value(False)
        scale.set_value(window.settings["transparency"])
        for value in (0, 25, 50, 75, 100):
            scale.add_mark(value, Gtk.PositionType.BOTTOM, str(value) + " %")
        scale.connect("value-changed", self._transparency)
        outer.pack_start(scale, False, False, 0)
        explanation = Gtk.Label(label="0 % = deckend · 100 % = Hintergrund unsichtbar\nSchrift und Cursor bleiben sichtbar. Standard: 75 %.", xalign=0)
        explanation.set_line_wrap(True)
        explanation.get_style_context().add_class("muted")
        outer.pack_start(explanation, False, False, 0)
        outer.pack_start(Gtk.Separator(), False, False, 3)
        grid = Gtk.Grid(column_spacing=24, row_spacing=14)
        font = Gtk.FontButton.new_with_font(window.settings["font"])
        font.set_use_font(False)
        font.connect("font-set", lambda widget: self._set("font", widget.get_font_name()))
        self._grid_row(grid, 0, "Terminal-Schrift", font)
        suggestion_switch = Gtk.Switch(active=window.settings["suggestions"])
        suggestion_switch.connect("notify::active", lambda widget, _: self._set("suggestions", widget.get_active()))
        self._grid_row(grid, 1, "Live-Befehlsvorschläge", suggestion_switch)
        count = Gtk.SpinButton.new_with_range(2, 3, 1)
        count.set_value(window.settings["suggestion_rows"])
        count.connect("value-changed", lambda widget: self._set("suggestion_rows", widget.get_value_as_int()))
        self._grid_row(grid, 2, "Sichtbare Vorschläge", count)
        native = Gtk.Switch(active=window.settings["native_completion"])
        native.connect("notify::active", lambda widget, _: self._set("native_completion", widget.get_active()))
        self._grid_row(grid, 3, "Installierte Bash-Completions nutzen", native)
        blink = Gtk.Switch(active=window.settings["cursor_blink"])
        blink.connect("notify::active", lambda widget, _: self._set("cursor_blink", widget.get_active()))
        self._grid_row(grid, 4, "Cursor blinkt", blink)
        cursor = Gtk.ComboBoxText()
        for ident, label in (("block", "Block"), ("ibeam", "Strich"), ("underline", "Unterstrich")):
            cursor.append(ident, label)
        cursor.set_active_id(window.settings["cursor_shape"])
        cursor.connect("changed", lambda widget: self._set("cursor_shape", widget.get_active_id()))
        self._grid_row(grid, 5, "Cursor-Form", cursor)
        manage_updates = Gtk.Button(label="Optionen & Passwort…")
        manage_updates.connect("clicked", lambda *_: window.open_update_settings())
        self._grid_row(grid, 6, "Update-Button", manage_updates)
        outer.pack_start(grid, False, False, 0)
        help_note = Gtk.Label(label="Befehl mit Tab markieren → H zeigt eine kurze Erklärung.\nNoch einmal H oder Esc schließt die Erklärung.", xalign=0)
        help_note.set_line_wrap(True)
        help_note.get_style_context().add_class("muted")
        outer.pack_start(help_note, False, False, 0)
        note = Gtk.Label(label="Transparenz braucht einen Desktop-Compositor.\nEs wird kein Blur-Effekt und keine GNOME-Erweiterung installiert.", xalign=0)
        note.set_line_wrap(True)
        note.get_style_context().add_class("muted")
        outer.pack_start(note, False, False, 0)

    @staticmethod
    def _grid_row(grid, row, label, control):
        text = Gtk.Label(label=label, xalign=0)
        text.set_hexpand(True)
        control.set_halign(Gtk.Align.END)
        grid.attach(text, 0, row, 1, 1)
        grid.attach(control, 1, row, 1, 1)

    def _transparency(self, scale):
        value = round(scale.get_value())
        self.percent.set_text(f"{value} %")
        self._set("transparency", value)

    def _set(self, key, value):
        self._owner_window.change_setting(key, value)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application, settings: Settings, cwd: str):
        super().__init__(application=application, title="Auralyn Terminal")
        self.settings = settings
        self.settings_dialog = None
        self.smart_popover = None
        self.ai_dialog = None
        self.update_dialog = None
        self.save_timer = 0
        self.destroying = False
        self.set_default_size(settings["window_width"], settings["window_height"])
        self.set_size_request(640, 420)
        self.set_icon_name("auralyn-terminal")
        self.get_style_context().add_class("auralyn-window")
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.connect("draw", self._clear_background)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("Auralyn Terminal")
        header.set_subtitle("BASH  ·  LOKAL  ·  BY JULIUS")
        header.get_style_context().add_class("auralyn-header")
        header.pack_start(button("tab-new-symbolic", "Neuer Tab · Strg+Umschalt+T", lambda _: self.add_tab()))
        header.pack_end(button("emblem-system-symbolic", "Terminal-Einstellungen · Strg+,", lambda _: self.open_settings()))
        header.pack_end(button("help-about-symbolic", "Über Auralyn Terminal", lambda _: self.about()))
        # pack_end appends inward: magnifier is directly LEFT of the info icon.
        self.smart_button = button("system-search-symbolic", "Smart Search · Strg+Umschalt+F", lambda _: self.open_smart())
        header.pack_end(self.smart_button)
        self.update_button = button("view-refresh-symbolic", "Systemupdate · APT + Flatpak", lambda _: self.launch_updates())
        header.pack_end(self.update_button)
        self.set_titlebar(header)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.notebook = Gtk.Notebook()
        self.notebook.set_scrollable(True)
        self.notebook.set_show_border(False)
        self.notebook.get_style_context().add_class("terminal-notebook")
        self.notebook.connect("switch-page", lambda *_: GLib.idle_add(self._after_switch))
        outer.pack_start(self.notebook, True, True, 0)
        status = Gtk.Box(spacing=14)
        status.set_border_width(0)
        status.get_style_context().add_class("statusbar")
        self.status_label = Gtk.Label(xalign=0)
        self.status_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.status_label.set_margin_start(15)
        self.status_label.set_margin_top(7)
        self.status_label.set_margin_bottom(7)
        self.transparency_label = Gtk.Label()
        self.transparency_label.set_margin_end(15)
        self.transparency_label.get_style_context().add_class("accent")
        status.pack_start(self.status_label, True, True, 0)
        status.pack_end(self.transparency_label, False, False, 0)
        outer.pack_end(status, False, False, 0)
        self.add(outer)
        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(screen, self.css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 10)
        self.apply_style()
        self.connect("key-press-event", self._on_key)
        self.connect("delete-event", self._on_delete)
        self.connect("destroy", self._on_destroy)
        self.add_tab(cwd)

    def _clear_background(self, _widget, cr):
        # Clear the native ARGB surface without making text/window controls fade.
        import cairo
        cr.save()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.restore()
        return False

    def pages(self):
        return [self.notebook.get_nth_page(i) for i in range(self.notebook.get_n_pages())]

    def current(self):
        return self.notebook.get_nth_page(self.notebook.get_current_page())

    def add_tab(self, cwd: str | None = None, smart_action: str | None = None, *, update_session: bool = False):
        if cwd is None:
            current = self.current()
            cwd = current.cwd if current else str(Path.home())
        if not os.path.isdir(cwd):
            cwd = str(Path.home())
        page = TerminalPage(self, cwd, smart_action, update_session=update_session)
        index = self.notebook.append_page(page, page.tab_box)
        self.notebook.set_tab_reorderable(page, True)
        page.show_all()
        self.notebook.set_current_page(index)
        page.terminal.grab_focus()
        self.refresh_status()
        return page

    def _after_switch(self):
        if not self.destroying:
            self.refresh_status()
            page = self.current()
            if page:
                page.terminal.grab_focus()
        return False

    def refresh_status(self):
        if self.destroying:
            return
        page = self.current()
        if page:
            cwd = page.cwd
            home = str(Path.home())
            if cwd == home or cwd.startswith(home + "/"):
                cwd = "~" + cwd[len(home):]
            mode = "Vorschläge an" if self.settings["suggestions"] and page.ready else "Programm läuft" if not page.ready else "Vorschläge aus"
            root = "ROOT  ·  " if os.geteuid() == 0 else ""
            self.status_label.set_text(f"{root}{cwd}  ·  {mode}")
        self.transparency_label.set_text(f"{self.settings['transparency']} % transparent")

    def close_tab(self, page):
        if page.update_session and not page.ready:
            self.show_error("Systemupdate läuft noch", "Bitte den Paketmanager zuerst fertig laufen lassen. Nicht mitten in einer Installation schließen. Strg+C bricht den Ablauf ab; dabei werden die sudo-Anmeldedaten gelöscht.")
            return
        if page.foreground_job() and not self.confirm_close("In diesem Tab läuft möglicherweise noch ein Programm."):
            return
        self.remove_tab(page)

    def remove_tab(self, page):
        index = self.notebook.page_num(page)
        if index < 0:
            return
        page.dispose()
        self.notebook.remove_page(index)
        page.destroy()  # Destroying VTE closes its PTY and hangs up the session.
        if self.notebook.get_n_pages() == 0 and not self.destroying:
            self.destroy()
        else:
            self.refresh_status()

    def confirm_close(self, message: str) -> bool:
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text="Terminal wirklich schließen?")
        dialog.format_secondary_text(message + "\nNicht gespeicherte Arbeit kann verloren gehen.")
        dialog.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL, "Schließen", Gtk.ResponseType.OK)
        result = dialog.run()
        dialog.destroy()
        return result == Gtk.ResponseType.OK

    def _on_delete(self, *_):
        if any(page.update_session and not page.ready for page in self.pages()):
            self.show_error("Systemupdate läuft noch", "Bitte das Update vor dem Schließen abschließen. Strg+C im Update-Tab kann den Ablauf abbrechen; eine laufende Paketinstallation möglichst nicht unterbrechen.")
            return True
        if any(page.foreground_job() for page in self.pages()):
            return not self.confirm_close("In mindestens einem Tab läuft möglicherweise noch ein Programm.")
        return False

    def _on_destroy(self, *_):
        self.destroying = True
        if self.smart_popover is not None:
            self.smart_popover.destroy()
        if self.ai_dialog is not None:
            self.ai_dialog.destroy()
        if self.update_dialog is not None:
            self.update_dialog.destroy()
        for page in self.pages():
            page.dispose()
        if self.save_timer:
            GLib.source_remove(self.save_timer)
        try:
            width, height = self.get_size()
            self.settings.data["window_width"] = width
            self.settings.data["window_height"] = height
            self.settings.save()
        except OSError:
            pass
        Gtk.StyleContext.remove_provider_for_screen(self.get_screen(), self.css)

    def apply_style(self):
        alpha = self.settings.alpha
        css = f"""
        window.auralyn-window, .auralyn-window decoration {{ background-color: transparent; background-image: none; }}
        .auralyn-window {{ color: #edf2fc; }}
        headerbar.auralyn-header {{ background-image: none; background-color: rgba(16,22,34,{alpha:.3f}); border-bottom: 1px solid rgba(151,186,219,0.17); box-shadow: none; }}
        .auralyn-header .title {{ font-weight: 700; }}
        .auralyn-header .subtitle {{ color: #9cb9c8; font-size: 9px; }}
        .auralyn-window button {{ color: #e7eefb; background-image: none; background-color: transparent; border-color: transparent; box-shadow: none; }}
        .auralyn-window button:hover {{ background-color: rgba(116,190,199,0.16); }}
        notebook.terminal-notebook, notebook.terminal-notebook > stack {{ background-color: transparent; border: none; }}
        notebook.terminal-notebook > header {{ background-image: none; background-color: rgba(16,22,34,{alpha:.3f}); border: none; padding: 0 9px; }}
        notebook.terminal-notebook > header tabs {{ background-color: transparent; }}
        notebook.terminal-notebook > header tab {{ background-color: transparent; border: none; border-bottom: 2px solid transparent; padding: 2px 10px; min-height: 31px; color: #afbccd; }}
        notebook.terminal-notebook > header tab:checked {{ color: #effaf7; border-bottom-color: #8fe1d1; }}
        .terminal-area {{ padding: 12px 14px; background-color: transparent; }}
        .suggestions {{ background-color: rgba(14,22,36,{alpha:.3f}); border: 1px solid rgba(149,202,217,0.45); border-radius: 12px; box-shadow: 0 5px 18px rgba(0,0,0,0.16); color: #ffffff; }}
        .suggestion-row {{ border: 1px solid transparent; border-radius: 7px; }}
        .suggestion-row.selected {{ background-color: rgba(113,193,186,{min(alpha, 0.22):.3f}); border-color: rgba(142,226,213,0.65); }}
        .command-name {{ font-family: monospace; font-size: 14px; font-weight: 600; text-shadow: 0 1px 2px rgba(0,0,0,0.7); }}
        .micro {{ font-size: 10px; color: #bfd3e3; }}
        .hint {{ font-size: 10px; color: #d2deea; }}
        .help-title {{ font-size: 10px; font-weight: 700; color: #a5efdf; }}
        .help-description {{ font-size: 12px; color: #f2f6ff; text-shadow: 0 1px 2px rgba(0,0,0,0.75); }}
        .statusbar {{ background-color: rgba(16,22,34,{alpha:.3f}); border-top: 1px solid rgba(151,186,219,0.14); font-size: 11px; color: #bdcada; }}
        .accent {{ color: #8fe1d1; font-weight: 600; }}
        .settings-dialog {{ background-color: #171f2e; color: #edf2fc; }}
        .settings-dialog .muted {{ color: #aebcce; font-size: 11px; }}
        .settings-dialog scale highlight {{ background-color: #83d7c8; }}
        .settings-dialog scale slider {{ background-color: #a6e6db; }}
        popover.smart-popover {{ background-color: rgba(17,25,39,0.97); background-image: none; color: #edf2fc; border: 1px solid rgba(143,225,209,0.38); border-radius: 14px; padding: 2px; }}
        .smart-title {{ font-size: 14px; font-weight: 700; color: #a5efdf; }}
        .smart-result-title {{ font-size: 13px; font-weight: 700; color: #eef7ff; }}
        .smart-command {{ font-family: monospace; font-size: 12px; color: #b3efdf; padding: 8px; background-color: rgba(4,10,18,0.5); border-radius: 7px; }}
        .smart-note {{ font-size: 11px; color: #b7c6d6; }}
        .smart-warning {{ font-size: 11px; color: #efd391; }}
        .smart-popover entry {{ background-color: #212e42; color: #edf2fc; border-color: #547786; border-radius: 8px; }}
        .smart-popover button {{ color: #eaf4fd; background-image: none; background-color: rgba(105,156,172,0.12); border-color: rgba(139,180,195,0.22); border-radius: 7px; box-shadow: none; }}
        .smart-popover button:hover {{ background-color: rgba(115,198,186,0.22); }}
        .smart-popover button.smart-primary {{ background-color: #326e68; color: #ffffff; font-weight: 600; }}
        .smart-popover button:disabled {{ opacity: 0.45; }}
        .smart-popover .smart-chip {{ font-size: 10px; padding: 3px 7px; min-height: 20px; }}
        """
        try:
            self.css.load_from_data(css.encode())
        except GLib.Error as exc:
            print(f"Auralyn: CSS error: {exc}", file=sys.stderr)
        for page in self.pages():
            page.apply_settings()
        self.refresh_status()
        self.queue_draw()

    def change_setting(self, key, value):
        from .settings import validate
        self.settings.runtime_overrides.pop(key, None)
        self.settings.data = validate({**self.settings.data, key: value})
        if key in ("smart_ai_enabled", "smart_ai_model", "smart_web_enabled", "smart_web_provider") and self.smart_popover is not None:
            self.smart_popover.refresh_mode()
            self.smart_popover._invalidate()
        self.apply_style()
        if self.save_timer:
            GLib.source_remove(self.save_timer)
        self.save_timer = GLib.timeout_add(250, self._save_settings)

    def _save_settings(self):
        self.save_timer = 0
        try:
            self.settings.save()
        except OSError as exc:
            self.show_error("Einstellungen konnten nicht gespeichert werden", str(exc))
        return False

    def open_settings(self):
        if self.settings_dialog is not None:
            self.settings_dialog.present()
            return
        try:
            dialog = SettingsDialog(self)
        except Exception as exc:
            # Keep the live terminal usable if a future dialog-only error occurs.
            import traceback
            traceback.print_exc()
            self.show_error("Einstellungen konnten nicht geöffnet werden", str(exc))
            return
        self.settings_dialog = dialog
        self.settings_dialog.connect("destroy", lambda *_: setattr(self, "settings_dialog", None))
        self.settings_dialog.show_all()
        self.settings_dialog.present()

    def open_smart(self):
        try:
            if self.smart_popover is None:
                from .smart_ui import SmartPopover
                self.smart_popover = SmartPopover(self, self.smart_button)
            if self.smart_popover.get_visible():
                self.smart_popover.popdown()
            else:
                self.smart_popover.open()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.show_error("Smart Search konnte nicht geöffnet werden", str(exc))

    def open_ai_settings(self):
        if self.ai_dialog is not None:
            self.ai_dialog.present()
            return
        try:
            from .smart_ui import LocalAIDialog
            self.ai_dialog = LocalAIDialog(self)
            self.ai_dialog.connect("destroy", lambda *_: setattr(self, "ai_dialog", None))
            self.ai_dialog.show_all()
            self.ai_dialog.present()
        except Exception as exc:
            self.ai_dialog = None
            import traceback
            traceback.print_exc()
            self.show_error("Lokale KI-Einstellungen konnten nicht geöffnet werden", str(exc))

    def launch_smart_action(self, ident: str, cwd: str):
        action = get_action(ident)
        if self.destroying or action is None:
            return False
        if action.warning:
            dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
                text="Diesen Befehl ausführen?")
            dialog.format_secondary_text(action.command + "\n\n" + action.warning +
                                         "\n\nStartet in einem neuen Terminal-Tab. sudo fragt dort normal nach dem Passwort.")
            dialog.add_buttons("Abbrechen", Gtk.ResponseType.CANCEL, "Ausführen", Gtk.ResponseType.OK)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.OK or self.destroying:
                return False
        # Never paste commands/Enter into a live tab or reuse a password/editor/SSH PTY.
        self.add_tab(cwd, smart_action=action.id)
        return True

    def open_update_settings(self):
        if self.update_dialog is not None:
            self.update_dialog.present()
            return
        try:
            from .update_ui import UpdateSettingsDialog
            self.update_dialog = UpdateSettingsDialog(self)
            self.update_dialog.connect("destroy", lambda *_: setattr(self, "update_dialog", None))
            self.update_dialog.show_all()
            self.update_dialog.present()
        except Exception:
            self.update_dialog = None
            self.show_error("Update-Einstellungen nicht verfügbar", "Der Passwortdialog konnte nicht geöffnet werden. Es wurde kein Passwort gespeichert.")

    def launch_updates(self):
        if self.destroying:
            return False
        if os.geteuid() == 0:
            self.show_error("Bitte normal starten", "Auralyn nicht mit sudo starten. Nur die zwei APT-Befehle bekommen kurz Administratorrechte.")
            return False
        for page in self.pages():
            if page.update_session and not page.ready:
                self.notebook.set_current_page(self.notebook.page_num(page))
                page.terminal.grab_focus()
                return False
        # A deliberate button click is the start action; APT/Flatpak retain
        # their native transaction confirmation, no -y flags are added.
        self.add_tab(str(Path.home()), update_session=True)
        return True

    def about(self):
        dialog = Gtk.AboutDialog(transient_for=self, modal=True)
        dialog.set_program_name("Auralyn Terminal")
        dialog.set_version(f"v{__version__} Stable")
        dialog.set_comments("Echtes Bash-Terminal. Kleine Vorschläge. Dein Glas-Look.\n\nTab: auswählen · Enter: einsetzen · H: Kurzhilfe\nEsc: Hilfe/Vorschläge schließen\nStrg+Umschalt+A: Alles markieren · Strg+A: Zeilenanfang\nStrg+Umschalt+C/V: kopieren/einfügen (ohne Mehrzeilen-Nachfrage)\nLupe / Strg+Umschalt+F: Smart Search\nStrg+Leertaste: Vorschläge neu laden\n\nLive-Vorschläge gelten für die lokale Bash.\nIn SSH, Root-Shells und anderen Shells bleibt deren normale Vervollständigung aktiv.")
        dialog.set_authors(["Idee und Gestaltung: Julius", "Implementierung: mit ChatGPT erstellt"])
        dialog.set_license_type(Gtk.License.MIT_X11)
        dialog.run()
        dialog.destroy()

    def show_error(self, title, detail):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(detail)
        dialog.run()
        dialog.destroy()

    def _on_key(self, _widget, event):
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(event.state & Gdk.ModifierType.MOD1_MASK)
        key = Gdk.keyval_to_lower(event.keyval)
        if ctrl and shift and key == Gdk.KEY_f:
            self.open_smart()
            return True
        if ctrl and shift and key == Gdk.KEY_t:
            self.add_tab()
            return True
        if ctrl and shift and key == Gdk.KEY_w:
            page = self.current()
            if page:
                self.close_tab(page)
            return True
        if ctrl and event.keyval == Gdk.KEY_comma:
            self.open_settings()
            return True
        if ctrl and event.keyval in (Gdk.KEY_Page_Up, Gdk.KEY_Page_Down):
            size = self.notebook.get_n_pages()
            if size:
                step = 1 if event.keyval == Gdk.KEY_Page_Down else -1
                self.notebook.set_current_page((self.notebook.get_current_page() + step) % size)
            return True
        if alt and Gdk.KEY_1 <= key <= Gdk.KEY_9:
            index = key - Gdk.KEY_1
            if index < self.notebook.get_n_pages():
                self.notebook.set_current_page(index)
            return True
        if ctrl and event.keyval in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_minus, Gdk.KEY_0):
            page = self.current()
            if page:
                scale = page.terminal.get_font_scale()
                if event.keyval == Gdk.KEY_0:
                    scale = 1.0
                else:
                    scale += -0.1 if event.keyval == Gdk.KEY_minus else 0.1
                page.terminal.set_font_scale(min(3.0, max(0.5, scale)))
            return True
        return False


class Application(Gtk.Application):
    def __init__(self, settings, cwd):
        # Like other terminals, multiple launcher invocations may open windows.
        super().__init__(application_id="de.julius.AuralynTerminal", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.settings = settings
        self.cwd = cwd

    def do_activate(self):
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        window = MainWindow(self, self.settings, self.cwd)
        window.show_all()
        window.present()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Auralyn Terminal – echtes Bash-Terminal mit kompakten Live-Vorschlägen.")
    parser.add_argument("--version", action="version", version=f"Auralyn Terminal v{__version__} Stable")
    parser.add_argument("--working-directory", metavar="ORDNER", default=str(Path.home()))
    parser.add_argument("--no-suggestions", action="store_true", help="Für diesen Start ohne Live-Vorschläge öffnen")
    args = parser.parse_args(argv)
    cwd = os.path.abspath(os.path.expanduser(args.working_directory))
    if not os.path.isdir(cwd):
        parser.error(f"Ordner existiert nicht: {cwd}")
    settings = Settings()
    if args.no_suggestions:
        settings.runtime_overrides["suggestions"] = False
    app = Application(settings, cwd)
    return app.run(["auralyn-terminal"])
