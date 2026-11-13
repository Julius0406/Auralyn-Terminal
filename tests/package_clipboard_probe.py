"""Clipboard regression directly against the already extracted .deb, no GTK needed."""
from __future__ import annotations
import ast
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock

root = Path(sys.argv[1]).resolve() / 'usr/share/auralyn-terminal'
source = root / 'auralyn_terminal/app.py'
tree = ast.parse(source.read_text())
klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'TerminalPage')
flags = NS(CONTROL_MASK=4, SHIFT_MASK=1, MOD1_MASK=8, MOD4_MASK=64, SUPER_MASK=128, META_MASK=256)
Gdk = NS(ModifierType=flags, KEY_a=97, KEY_c=99, KEY_v=118, KEY_Insert=65379, KEY_space=32,
         keyval_to_lower=lambda value: ord(chr(value).lower()) if 65 <= value <= 90 else value)
Vte = NS(Format=NS(TEXT=2))

def extract(name):
    node = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {'Gdk': Gdk, 'Vte': Vte}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), 'exec'), scope)
    return scope[name]

key = extract('_on_key')
paste = extract('_paste_received')
popup = NS(clear=Mock(), get_visible=Mock(return_value=False))
page = NS(closed=False, popup=popup, terminal=Mock(), request_paste=Mock(),
          select_terminal_all=Mock(), invalidate=Mock(), schedule_snapshot=Mock())
combo = flags.CONTROL_MASK | flags.SHIFT_MASK
assert key(page, page.terminal, NS(keyval=Gdk.KEY_c, state=combo))
page.terminal.copy_clipboard_format.assert_called_once_with(Vte.Format.TEXT)
assert key(page, page.terminal, NS(keyval=Gdk.KEY_v, state=combo))
page.request_paste.assert_called_once_with()
assert not key(page, page.terminal, NS(keyval=Gdk.KEY_c, state=flags.CONTROL_MASK))
assert not key(page, page.terminal, NS(keyval=Gdk.KEY_v, state=flags.CONTROL_MASK))
paste(page, None, 'echo eins\r\necho zwei\n')
page.terminal.paste_text.assert_called_once_with('echo eins\necho zwei')
page.terminal.feed_child.assert_not_called()
popup.clear.assert_called_once()
page.terminal.grab_focus.assert_called_once()
assert 'Gtk.MessageDialog' not in ast.get_source_segment(source.read_text(), next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == '_paste_received'))
print('PASS: extracted copy/paste shortcuts and direct multiline paste without confirmation popup')
print('PASS: extracted Ctrl+C/V unmodified shell behavior, normalized LF and final LF removal')
print('No GUI/clipboard manager, external programs or shell commands were executed.')
