"""Controller regressions against explicitly fake GTK objects.

The exact methods/classes from app.py are compiled, but this is NOT a real
PyGObject/VTE/window-system test. Run test_gtk_smoke.py with those dependencies
for the additional real GUI smoke test.
"""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest
from types import MethodType
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from auralyn_terminal.completion import Candidate, Context, parse_context, replacement
from auralyn_terminal.command_help import HelpText
from auralyn_terminal.settings import DEFAULTS
from auralyn_terminal.terminal_state import suggestion_viewport_row

TREE = ast.parse((ROOT / 'auralyn_terminal/app.py').read_text())


class Widget:
    def __init__(self, *args, **kwargs):
        self.children = []
        self.signals = []
        self.visible = False
        self.label = kwargs.get('label', '')
        self.value = kwargs.get('value', 0)
        self.active = kwargs.get('active', False)
        self.classes = []
        self._content = None

    @classmethod
    def new_with_range(cls, *args):
        return cls()

    @classmethod
    def new_with_font(cls, font):
        result = cls()
        result.font = font
        return result

    def __getattr__(self, name):
        if name.startswith('set_') or name in ('add_mark', 'append'):
            return lambda *args, **kwargs: None
        raise AttributeError(name)

    def get_style_context(self):
        return self

    def add_class(self, name):
        self.classes.append(name)

    def add(self, child):
        self.children.append(child)

    def pack_start(self, child, *args):
        self.children.append(child)

    pack_end = pack_start

    def attach(self, child, *args):
        self.children.append(child)

    def get_children(self):
        return list(self.children)

    def remove(self, child):
        self.children.remove(child)

    def show(self):
        self.visible = True

    def show_all(self):
        self.visible = True
        for child in self.children:
            child.show_all()

    def hide(self):
        self.visible = False

    def present(self):
        self.visible = True

    def get_visible(self):
        return self.visible

    def connect(self, name, callback, *args):
        self.signals.append((name, callback, args))

    def destroy(self):
        self.visible = False
        for name, callback, args in self.signals:
            if name == 'destroy':
                callback(self, *args)

    def get_content_area(self):
        if self._content is None:
            self._content = Widget()
        return self._content

    def add_button(self, *args):
        return Widget()

    def set_text(self, text):
        self.label = text

    def set_value(self, value):
        self.value = value

    def get_value(self):
        return self.value

    def get_value_as_int(self):
        return int(self.value)

    def get_active(self):
        return self.active


class Menu(Widget):
    last_instance = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        Menu.last_instance = self

    def append(self, child):
        self.children.append(child)

    def popup_at_pointer(self, _event):
        self.show()


class Dialog(Widget):
    # Model the conflicting GI field explicitly. This test double cannot prove
    # ABI compatibility, but a future `self.window = ...` reliably fails here.
    @property
    def window(self):
        return None

    @window.setter
    def window(self, value):
        raise RuntimeError('field is not writable')


Gtk = NS(Dialog=Dialog, Menu=Menu, MenuItem=Widget, Button=Widget, EventBox=Widget, Box=Widget, Label=Widget, Scale=Widget,
         Grid=Widget, FontButton=Widget, Switch=Widget, SpinButton=Widget,
         Separator=Widget, ComboBoxText=Widget,
         Orientation=NS(VERTICAL=1, HORIZONTAL=0), Align=NS(START=0, END=1),
         ResponseType=NS(CLOSE=-7), PositionType=NS(BOTTOM=1))
Pango = NS(EllipsizeMode=NS(END=3), WrapMode=NS(WORD_CHAR=2))
Gdk = NS(ModifierType=NS(CONTROL_MASK=4, SHIFT_MASK=1, MOD1_MASK=8,
                         MOD4_MASK=64, SUPER_MASK=1 << 26, META_MASK=1 << 28),
         KEY_a=97, KEY_c=99, KEY_v=118, KEY_h=104, KEY_Insert=65379, KEY_space=32,
         KEY_Tab=65289, KEY_ISO_Left_Tab=65056, KEY_Return=65293,
         KEY_KP_Enter=65421, KEY_Right=65363, KEY_Escape=65307,
         keyval_to_lower=lambda value: ord(chr(value).lower()) if 65 <= value <= 90 else value)


def load(name, method=None, extra=None):
    node = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == name)
    if method:
        node = next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == method)
    namespace = dict(Gtk=Gtk, Gdk=Gdk, Pango=Pango, Vte=NS(Format=NS(TEXT=1)), Candidate=Candidate,
                     Context=Context, HelpText=HelpText, replacement=replacement,
                     APPLY_SEQUENCE=b'\x1b[989;2~', suggestion_viewport_row=suggestion_viewport_row)
    namespace.update(extra or {})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(ROOT / 'auralyn_terminal/app.py'), 'exec'), namespace)
    return namespace[method or name]


SettingsDialog = load('SettingsDialog')
Suggestions = load('Suggestions')
key_handler = load('TerminalPage', '_on_key')
select_all_handler = load('TerminalPage', 'select_terminal_all')
mouse_handler = load('TerminalPage', '_on_mouse')
accept_handler = load('TerminalPage', 'accept_suggestion')
paste_received_handler = load('TerminalPage', '_paste_received')
position_handler = load('TerminalPage', 'position_suggestions')


def context(line):
    return parse_context(line, len(line.encode()))


def page():
    obj = NS(window=NS(settings=dict(DEFAULTS), open_settings=Mock(), add_tab=Mock()), context=context('s'), cwd='/',
             closed=False, help_worker=Mock(), safe_to_query=Mock(return_value=True),
             position_suggestions=Mock(), terminal=Mock(),
             overlay=NS(get_allocated_height=Mock(return_value=720)),
             accept_suggestion=Mock(), request_paste=Mock(), invalidate=Mock(), schedule_snapshot=Mock())
    obj.popup = Suggestions(obj)
    obj.select_terminal_all = MethodType(select_all_handler, obj)
    return obj


def event(key, state=0):
    return NS(keyval=key, state=state)


def flatten(widget):
    for child in widget.get_children():
        yield child
        yield from flatten(child)


class SettingsControllerTests(unittest.TestCase):
    def test_old_assignment_is_a_read_only_field(self):
        # Test-double validation, not an actual GTK reproduction.
        with self.assertRaisesRegex(RuntimeError, 'field is not writable'):
            Dialog().window = Widget()

    def test_settings_construction_uses_own_field(self):
        owner = NS(settings=dict(DEFAULTS), change_setting=Mock())
        dialog = SettingsDialog(owner)
        self.assertIs(dialog._owner_window, owner)
        self.assertIsNone(dialog.window)
        self.assertEqual(dialog.percent.label, '75 %')

    def test_transparency_endpoints_reach_owner(self):
        owner = NS(settings=dict(DEFAULTS), change_setting=Mock())
        dialog = SettingsDialog(owner)
        for value in (0, 75, 100):
            dialog._transparency(Widget(value=value))
            self.assertEqual(dialog.percent.label, f'{value} %')
            owner.change_setting.assert_called_with('transparency', value)

    def test_other_settings_reach_owner(self):
        owner = NS(settings=dict(DEFAULTS), change_setting=Mock())
        dialog = SettingsDialog(owner)
        for name, value in [('font', 'Monospace 16'), ('suggestion_rows', 2), ('suggestions', False)]:
            dialog._set(name, value)
            owner.change_setting.assert_called_with(name, value)

    def test_reopen_reuses_live_dialog_then_recreates(self):
        open_settings = load('MainWindow', 'open_settings', {'SettingsDialog': SettingsDialog})
        owner = NS(settings=dict(DEFAULTS), change_setting=Mock(), settings_dialog=None, show_error=Mock())
        open_settings(owner)
        first = owner.settings_dialog
        self.assertTrue(first.get_visible())
        open_settings(owner)
        self.assertIs(owner.settings_dialog, first)
        first.destroy()
        self.assertIsNone(owner.settings_dialog)
        open_settings(owner)
        self.assertIsNot(owner.settings_dialog, first)
        owner.show_error.assert_not_called()


class KeyboardTests(unittest.TestCase):
    def setUp(self):
        self.page = page()
        self.page.popup.update([Candidate('sudo'), Candidate('ssh'), Candidate('systemctl')])

    def handle(self, key, state=0):
        return key_handler(self.page, self.page.terminal, event(key, state))

    def test_right_click_menu_action_selects_all(self):
        self.assertTrue(mouse_handler(self.page, self.page.terminal, NS(button=3)))
        menu = Menu.last_instance
        self.assertTrue(menu.get_visible())
        select = next(item for item in menu.get_children() if item.label == 'Alles markieren (Strg+Umschalt+A)')
        action = next(cb for signal, cb, args in select.signals if signal == 'activate')
        action(select)
        self.page.terminal.select_all.assert_called_once_with()
        self.assertFalse(self.page.popup.get_visible())
        self.page.terminal.feed_child.assert_not_called()

    def test_ctrl_shift_a_selects_entire_terminal_even_with_popup(self):
        self.assertTrue(self.page.popup.get_visible())
        self.assertTrue(self.handle(Gdk.KEY_a, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK))
        self.page.terminal.select_all.assert_called_once_with()
        self.assertFalse(self.page.popup.get_visible())
        self.page.terminal.feed_child.assert_not_called()
        self.page.terminal.copy_clipboard_format.assert_not_called()

    def test_ctrl_shift_a_works_without_suggestions_and_when_foreground_busy(self):
        self.page.popup.hide()
        self.page.safe_to_query.return_value = False
        self.assertTrue(self.handle(ord('A'), Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK))
        self.page.terminal.select_all.assert_called_once_with()
        self.page.terminal.feed_child.assert_not_called()

    def test_ctrl_shift_a_does_not_capture_other_modifiers(self):
        for state in (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.MOD1_MASK,
                      Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.SUPER_MASK,
                      Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.MOD4_MASK,
                      Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.META_MASK):
            self.assertFalse(self.handle(Gdk.KEY_a, state))
        self.page.terminal.select_all.assert_not_called()
        self.assertTrue(self.page.popup.get_visible())

    def test_ctrl_a_is_unhandled_by_auralyn_for_bash_readline(self):
        """Returning False lets VTE send ^A to Bash again (line start)."""
        self.assertTrue(self.page.popup.get_visible())
        self.assertFalse(self.handle(Gdk.KEY_a, Gdk.ModifierType.CONTROL_MASK))
        self.assertFalse(self.handle(ord('A'), Gdk.ModifierType.CONTROL_MASK))
        self.page.terminal.select_all.assert_not_called()
        self.assertTrue(self.page.popup.get_visible())
        self.page.terminal.copy_clipboard_format.assert_not_called()

    def test_ctrl_shift_a_requires_both_modifiers(self):
        for mask in (0, Gdk.ModifierType.SHIFT_MASK, Gdk.ModifierType.CONTROL_MASK):
            with self.subTest(mask=mask):
                self.assertFalse(self.handle(Gdk.KEY_a, mask))
        self.page.terminal.select_all.assert_not_called()

    def test_ctrl_shift_a_then_clipboard_copy_shortcut(self):
        self.assertTrue(self.handle(Gdk.KEY_a, Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK))
        self.assertTrue(self.handle(Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK |
                                     Gdk.ModifierType.SHIFT_MASK))
        self.page.terminal.select_all.assert_called_once_with()
        self.page.terminal.copy_clipboard_format.assert_called_once()
        self.page.terminal.feed_child.assert_not_called()

    def test_ctrl_shift_c_copies_selected_text_without_shell_input(self):
        self.assertTrue(self.handle(Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK |
                                    Gdk.ModifierType.SHIFT_MASK))
        self.page.terminal.copy_clipboard_format.assert_called_once_with(1)
        self.page.terminal.feed_child.assert_not_called()
        self.page.request_paste.assert_not_called()

    def test_ctrl_shift_v_requests_paste_even_with_selected_suggestion(self):
        self.page.popup.cycle(1)
        self.assertTrue(self.handle(Gdk.KEY_v, Gdk.ModifierType.CONTROL_MASK |
                                    Gdk.ModifierType.SHIFT_MASK))
        self.page.request_paste.assert_called_once_with()
        self.page.accept_suggestion.assert_not_called()
        self.page.terminal.feed_child.assert_not_called()

    def test_ctrl_shift_v_uppercase_and_shift_insert(self):
        self.assertTrue(self.handle(ord('V'), Gdk.ModifierType.CONTROL_MASK |
                                    Gdk.ModifierType.SHIFT_MASK))
        self.assertTrue(self.handle(Gdk.KEY_Insert, Gdk.ModifierType.SHIFT_MASK))
        self.assertEqual(self.page.request_paste.call_count, 2)

    def test_copy_paste_does_not_intercept_other_modifier_shortcuts(self):
        for key in (Gdk.KEY_c, Gdk.KEY_v):
            for extra in (Gdk.ModifierType.MOD1_MASK, Gdk.ModifierType.SUPER_MASK,
                          Gdk.ModifierType.MOD4_MASK, Gdk.ModifierType.META_MASK):
                with self.subTest(key=key, extra=extra):
                    self.assertFalse(self.handle(key, Gdk.ModifierType.CONTROL_MASK |
                                                 Gdk.ModifierType.SHIFT_MASK | extra))
        self.page.terminal.copy_clipboard_format.assert_not_called()
        self.page.request_paste.assert_not_called()

    def test_unshifted_ctrl_c_v_remain_terminal_controls(self):
        self.assertFalse(self.handle(Gdk.KEY_c, Gdk.ModifierType.CONTROL_MASK))
        self.assertFalse(self.handle(Gdk.KEY_v, Gdk.ModifierType.CONTROL_MASK))
        self.page.terminal.copy_clipboard_format.assert_not_called()
        self.page.request_paste.assert_not_called()

    def test_context_menu_displays_copy_paste_shortcuts(self):
        self.assertTrue(mouse_handler(self.page, self.page.terminal, NS(button=3)))
        items = Menu.last_instance.get_children()
        copy = next(item for item in items if item.label == 'Kopieren (Strg+Umschalt+C)')
        paste = next(item for item in items if item.label == 'Einfügen (Strg+Umschalt+V)')
        next(cb for signal, cb, args in copy.signals if signal == 'activate')(copy)
        next(cb for signal, cb, args in paste.signals if signal == 'activate')(paste)
        self.page.terminal.copy_clipboard_format.assert_called_once_with(1)
        self.page.request_paste.assert_called_once_with()

    def test_multiline_paste_is_immediate_no_dialog(self):
        # This fake Gtk has NO MessageDialog; any prompt would fail the test.
        paste_received_handler(self.page, None, 'echo eins\r\necho zwei\n')
        self.page.terminal.paste_text.assert_called_once_with('echo eins\necho zwei')
        self.page.terminal.grab_focus.assert_called_once_with()
        self.assertFalse(self.page.popup.get_visible())
        self.page.terminal.feed_child.assert_not_called()

    def test_paste_keeps_internal_breaks_and_removes_controls(self):
        paste_received_handler(self.page, None, 'abc\x1b[31m\rdef\x7f\nxyz\r\n\n')
        self.page.terminal.paste_text.assert_called_once_with('abc[31m\ndef\nxyz')

    def test_single_line_paste_also_works_without_popup(self):
        paste_received_handler(self.page, None, 'git status')
        self.page.terminal.paste_text.assert_called_once_with('git status')
        self.assertFalse(self.page.popup.get_visible())

    def test_empty_and_closed_paste_is_silently_ignored(self):
        for value in (None, '', '\n\n', '\x1b'):
            with self.subTest(value=value):
                paste_received_handler(self.page, None, value)
        self.page.closed = True
        paste_received_handler(self.page, None, 'echo should-not-appear')
        self.page.terminal.paste_text.assert_not_called()
        self.page.terminal.grab_focus.assert_not_called()

    def test_h_without_selection_remains_text(self):
        self.assertFalse(self.handle(ord('h')))
        self.assertFalse(self.page.popup.help_open)
        self.page.help_worker.submit.assert_not_called()

    def test_tab_then_h_opens_help_without_writing(self):
        self.assertTrue(self.handle(Gdk.KEY_Tab))
        self.assertTrue(self.handle(ord('h')))
        self.assertTrue(self.page.popup.help_open)
        self.page.help_worker.submit.assert_called_once()
        self.page.terminal.feed_child.assert_not_called()
        self.page.accept_suggestion.assert_not_called()

    def test_capital_h_works(self):
        self.handle(Gdk.KEY_Tab)
        self.assertTrue(self.handle(ord('H'), Gdk.ModifierType.SHIFT_MASK))
        self.assertTrue(self.page.popup.help_open)

    def test_modified_h_not_intercepted(self):
        self.handle(Gdk.KEY_Tab)
        for mask in (Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.MOD1_MASK,
                     Gdk.ModifierType.MOD4_MASK, Gdk.ModifierType.SUPER_MASK,
                     Gdk.ModifierType.META_MASK):
            self.assertFalse(self.handle(ord('h'), mask))
        self.assertFalse(self.page.popup.help_open)

    def test_h_without_popup_remains_text(self):
        self.page.popup.hide()
        self.assertFalse(self.handle(ord('h')))

    def test_h_during_foreground_program_not_intercepted(self):
        self.handle(Gdk.KEY_Tab)
        self.page.safe_to_query.return_value = False
        self.assertFalse(self.handle(ord('h')))
        self.assertFalse(self.page.popup.get_visible())
        self.page.help_worker.submit.assert_not_called()

    def test_second_h_hides_help_keeps_selection(self):
        self.handle(Gdk.KEY_Tab)
        self.handle(ord('h'))
        self.handle(ord('h'))
        self.assertFalse(self.page.popup.help_open)
        self.assertTrue(self.page.popup.get_visible())
        self.assertEqual(self.page.popup.selected, 0)

    def test_escape_closes_help_before_suggestions(self):
        self.handle(Gdk.KEY_Tab)
        self.handle(ord('h'))
        self.assertTrue(self.handle(Gdk.KEY_Escape))
        self.assertFalse(self.page.popup.help_open)
        self.page.invalidate.assert_not_called()
        self.handle(Gdk.KEY_Escape)
        self.page.invalidate.assert_called_once()

    def test_tab_while_help_open_updates_topic(self):
        self.handle(Gdk.KEY_Tab)
        self.handle(ord('h'))
        generation = self.page.popup.help_generation
        self.handle(Gdk.KEY_Tab)
        args = self.page.help_worker.submit.call_args.args
        self.assertEqual(args[2].value, 'ssh')
        self.assertGreater(args[0], generation)
        self.assertTrue(self.page.popup.help_open)

    def test_shift_tab_wraps(self):
        self.handle(Gdk.KEY_ISO_Left_Tab, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual(self.page.popup.selected, 2)

    def test_enter_accepts_but_no_direct_execution(self):
        self.handle(Gdk.KEY_Tab)
        self.handle(ord('h'))
        self.assertTrue(self.handle(Gdk.KEY_Return))
        self.page.accept_suggestion.assert_called_once()
        self.page.terminal.feed_child.assert_not_called()

    def test_enter_without_selection_passes_to_shell(self):
        self.assertFalse(self.handle(Gdk.KEY_Return))
        self.page.accept_suggestion.assert_not_called()

    def test_ordinary_other_letter_not_intercepted(self):
        self.handle(Gdk.KEY_Tab)
        self.handle(ord('h'))
        self.assertFalse(self.handle(ord('a')))

    def test_accept_keeps_readline_insert_only_protocol(self):
        self.page.context = context('sud')
        self.page.last_snapshot = ('sud', 3)
        self.page.popup.cycle(1)
        self.page.ipc = Mock()
        self.page.serial = 5
        self.page._feed_private = Mock()
        accept_handler(self.page)
        self.page.ipc.write_replacement.assert_called_once_with('sud', 3, 'sudo ', 5)
        self.page._feed_private.assert_called_once_with(b'\x1b[989;2~')
        self.page.terminal.feed_child.assert_not_called()


class SuggestionHelpStateTests(unittest.TestCase):
    def setUp(self):
        self.page = page()
        self.popup = self.page.popup
        self.popup.update([Candidate('sudo'), Candidate('ssh'), Candidate('systemctl'), Candidate('sleep')])
        self.popup.cycle(1)

    def test_tab_alone_does_not_start_help_lookup(self):
        self.page.help_worker.submit.assert_not_called()

    def test_only_three_rows_even_with_help(self):
        self.popup.toggle_help()
        rows = [x for x in self.popup.body.get_children() if 'suggestion-row' in x.classes]
        self.assertEqual(len(rows), 3)

    def test_two_row_setting_still_works(self):
        self.page.window.settings['suggestion_rows'] = 2
        self.popup.toggle_help()
        rows = [x for x in self.popup.body.get_children() if 'suggestion-row' in x.classes]
        self.assertEqual(len(rows), 2)

    def test_small_window_uses_two_rows_with_help(self):
        self.page.overlay.get_allocated_height.return_value = 290
        self.popup.toggle_help()
        rows = [x for x in self.popup.body.get_children() if 'suggestion-row' in x.classes]
        self.assertEqual(len(rows), 2)

    def test_current_result_visible(self):
        self.popup.toggle_help()
        result = HelpText('sudo', 'Führt Befehle als Administrator aus.')
        self.popup.receive_help(self.popup.help_generation, result)
        self.assertEqual(self.popup.help_text, result)
        labels = [x.label for x in flatten(self.popup.body)]
        self.assertIn(result.text, labels)

    def test_stale_result_cannot_replace_new_selection(self):
        self.popup.toggle_help()
        old = self.popup.help_generation
        self.popup.cycle(1)
        self.popup.receive_help(old, HelpText('sudo', 'STALE'))
        self.assertNotEqual(self.popup.help_text.text, 'STALE')
        self.assertEqual(self.popup.help_text.title, 'ssh')

    def test_hide_invalidates_pending_help(self):
        self.popup.toggle_help()
        old = self.popup.help_generation
        self.popup.clear()
        self.popup.receive_help(old, HelpText('sudo', 'STALE'))
        self.assertFalse(self.popup.get_visible())
        self.assertIsNone(self.popup.help_text)
        self.assertEqual(self.popup.selected, -1)

    def test_typing_new_prefix_resets_help(self):
        self.popup.toggle_help()
        self.popup.update([Candidate('sleep')])
        self.assertFalse(self.popup.help_open)
        self.assertIsNone(self.popup.help_text)
        self.assertEqual(self.popup.selected, -1)

    def test_closed_page_drops_late_help(self):
        self.popup.toggle_help()
        self.page.closed = True
        self.popup.receive_help(self.popup.help_generation, HelpText('sudo', 'STALE'))
        self.assertNotEqual(self.popup.help_text.text, 'STALE')

    def test_help_never_uses_markup_for_dynamic_text(self):
        node = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'Suggestions')
        self.assertFalse(any(isinstance(n, ast.Attribute) and n.attr == 'set_markup' for n in ast.walk(node)))


class ClearScreenCompletionOverlayTests(unittest.TestCase):
    """Regression for clear resetting VTE absolute cursor before scroll adjustment."""

    def setUp(self):
        self.page = page()
        self.page.overlay.get_allocated_width = Mock(return_value=760)
        self.page.overlay.get_allocated_height = Mock(return_value=480)
        self.page.popup.update([Candidate('sudo'), Candidate('ssh'), Candidate('systemctl')])
        self.page.popup.body.get_preferred_height_for_width = Mock(return_value=(120, 120))
        self.page.popup.set_size_request = Mock()
        self.page.popup.set_margin_start = Mock()
        self.page.popup.set_margin_top = Mock()
        self.page.terminal.get_char_height.return_value = 20
        self.page.terminal.get_char_width.return_value = 10
        self.page.terminal.get_scroll_unit_is_pixels.return_value = False
        self.page.context = context('s')
        self.adjustment = Mock()
        self.page.terminal.get_vadjustment.return_value = self.adjustment
        self.adjustment.get_page_size.return_value = 24
        self.adjustment.get_upper.return_value = 300

    def test_clear_uses_new_top_cursor_despite_old_bottom_adjustment(self):
        self.assertTrue(self.page.popup.get_visible())
        self.page.terminal.get_cursor_position.return_value = (5, 0)
        self.adjustment.get_value.return_value = 276  # stale before CSI 3J reflow
        position_handler(self.page)
        self.assertTrue(self.page.popup.get_visible())
        self.page.popup.set_margin_top.assert_called()
        self.page.popup.set_margin_start.assert_called()

    def test_clear_when_value_resets_before_old_upper_limit(self):
        self.page.terminal.get_cursor_position.return_value = (5, 0)
        self.adjustment.get_value.return_value = 0
        self.adjustment.get_upper.return_value = 300  # old range, not yet reflowed
        position_handler(self.page)
        self.assertTrue(self.page.popup.get_visible())

    def test_after_many_clears_popup_stays_near_visible_prompt_not_bottom(self):
        """The screenshot bug was a *visible* box placed at the bottom."""
        self.adjustment.get_value.return_value = 276
        self.adjustment.get_upper.return_value = 300
        for count in (1, 2, 4, 10, 30):
            # CSI 2J/3J may retain a monotonically increasing absolute row.
            self.page.terminal.get_cursor_position.return_value = (9, 276 + 24 * count)
            self.page.popup.set_margin_top.reset_mock()
            position_handler(self.page)
            self.assertTrue(self.page.popup.get_visible())
            self.page.popup.set_margin_top.assert_called_once_with(40)

    def test_overflow_after_clear_recovers_top_and_then_normal_cursor_row(self):
        self.adjustment.get_value.return_value = 276
        self.page.terminal.get_cursor_position.return_value = (7, 650)
        position_handler(self.page)
        self.page.popup.set_margin_top.assert_called_with(40)
        # As soon as VTE's adjustment catches up, the ordinary placement wins.
        self.page.terminal.get_cursor_position.return_value = (7, 280)
        self.page.popup.set_margin_top.reset_mock()
        position_handler(self.page)
        self.page.popup.set_margin_top.assert_called_once_with(120)

    def test_overflow_in_pixel_scroll_mode_recovers_top(self):
        self.page.terminal.get_scroll_unit_is_pixels.return_value = True
        self.page.terminal.get_cursor_position.return_value = (9, 580)
        self.adjustment.get_value.return_value = 276 * 20
        self.adjustment.get_upper.return_value = 300 * 20
        self.adjustment.get_page_size.return_value = 24 * 20
        position_handler(self.page)
        self.page.popup.set_margin_top.assert_called_once_with(40)

    def test_manual_scrollback_overflow_does_not_recover_top(self):
        self.page.terminal.get_cursor_position.return_value = (9, 700)
        self.adjustment.get_value.return_value = 140
        position_handler(self.page)
        self.assertFalse(self.page.popup.get_visible())

    def test_live_completion_after_normal_scrollback(self):
        self.page.terminal.get_cursor_position.return_value = (18, 287)
        self.adjustment.get_value.return_value = 276
        position_handler(self.page)
        self.assertTrue(self.page.popup.get_visible())

    def test_manually_scrolled_history_does_not_show_ghost_suggestions(self):
        self.page.terminal.get_cursor_position.return_value = (3, 287)
        self.adjustment.get_value.return_value = 140
        position_handler(self.page)
        self.assertFalse(self.page.popup.get_visible())

    def test_pixel_based_adjustment_is_supported(self):
        self.page.terminal.get_scroll_unit_is_pixels.return_value = True
        self.page.terminal.get_cursor_position.return_value = (9, 287)
        self.adjustment.get_value.return_value = 276 * 20
        self.adjustment.get_upper.return_value = 300 * 20
        self.adjustment.get_page_size.return_value = 24 * 20
        position_handler(self.page)
        self.assertTrue(self.page.popup.get_visible())

    def test_repeated_clear_and_subsequent_typing_can_show_popup_again(self):
        self.page.terminal.get_cursor_position.return_value = (1, 0)
        self.adjustment.get_value.return_value = 276
        for _ in range(4):
            self.page.popup.clear()   # When Bash starts executing clear.
            self.assertFalse(self.page.popup.get_visible())
            self.page.popup.update([Candidate('sudo'), Candidate('ssh')])  # next input 's'
            position_handler(self.page)
            self.assertTrue(self.page.popup.get_visible())


if __name__ == '__main__':
    unittest.main()
