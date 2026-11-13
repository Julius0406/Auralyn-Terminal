"""Validate the actual app stylesheet with installed GTK3, without PyGObject.

This checks GTK CSS syntax, NOT the VTE UI or compositor transparency.
Usage: xvfb-run -a python3 tests/check_gtk_css.py
"""
import ast
import ctypes
import ctypes.util
from pathlib import Path

root = Path(__file__).resolve().parent.parent
module = ast.parse((root / 'auralyn_terminal/app.py').read_text())
window = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'MainWindow')
method = next(node for node in window.body if isinstance(node, ast.FunctionDef) and node.name == 'apply_style')
value = next(node.value for node in method.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'css' for t in node.targets))
expr = compile(ast.fix_missing_locations(ast.Expression(value)), '<app-css>', 'eval')

lib = ctypes.CDLL(ctypes.util.find_library('gtk-3'))
lib.gtk_init_check.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
lib.gtk_init_check.restype = ctypes.c_int
lib.gtk_css_provider_new.restype = ctypes.c_void_p
lib.gtk_css_provider_load_from_data.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_ssize_t, ctypes.POINTER(ctypes.c_void_p)]
lib.gtk_css_provider_load_from_data.restype = ctypes.c_int
if not lib.gtk_init_check(None, None):
    raise SystemExit('No display; run under xvfb-run.')

class GError(ctypes.Structure):
    _fields_ = [('domain', ctypes.c_uint), ('code', ctypes.c_int), ('message', ctypes.c_char_p)]

for alpha in (0.0, .25, 1.0):
    css = eval(expr, {'__builtins__': {}, 'alpha': alpha, 'min': min}).encode()
    error = ctypes.c_void_p()
    ok = lib.gtk_css_provider_load_from_data(lib.gtk_css_provider_new(), css, len(css), ctypes.byref(error))
    if not ok:
        detail = ctypes.cast(error, ctypes.POINTER(GError)).contents.message.decode()
        raise SystemExit(detail)
    print(f'GTK CSS valid: alpha={alpha}')
