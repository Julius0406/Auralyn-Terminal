"""Validated settings. No command lines, passwords or terminal output are saved."""
from __future__ import annotations
import json
import os
import re
import tempfile
from pathlib import Path

DEFAULTS = {
    "update_use_keyring": False,
    "update_auto_confirm": True,
    "transparency": 75,
    "font": "Monospace 13",
    "suggestions": True,
    "native_completion": True,
    "suggestion_rows": 3,
    "cursor_blink": True,
    "cursor_shape": "block",
    "scrollback": 10000,
    "window_width": 1100,
    "window_height": 720,
    "smart_ai_enabled": False,
    "smart_ai_model": "qwen3:4b",
    "smart_web_enabled": False,
    "smart_web_provider": "duckduckgo",
}

def validate(data: object) -> dict:
    result = dict(DEFAULTS)
    if not isinstance(data, dict):
        return result
    for key in ("transparency", "suggestion_rows", "scrollback", "window_width", "window_height"):
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            lo, hi = {
                "transparency": (0, 100), "suggestion_rows": (2, 3),
                "scrollback": (1000, 100000), "window_width": (640, 7680),
                "window_height": (420, 4320),
            }[key]
            result[key] = max(lo, min(hi, value))
    for key in ("suggestions", "native_completion", "cursor_blink", "smart_ai_enabled", "smart_web_enabled", "update_use_keyring", "update_auto_confirm"):
        if isinstance(data.get(key), bool):
            result[key] = data[key]
    font = data.get("font")
    if isinstance(font, str) and 0 < len(font) < 180 and not any(ord(c) < 32 for c in font):
        result["font"] = font
    if data.get("cursor_shape") in ("block", "ibeam", "underline"):
        result["cursor_shape"] = data["cursor_shape"]
    if data.get("smart_web_provider") in ("duckduckgo", "ollama"):
        result["smart_web_provider"] = data["smart_web_provider"]
    model = data.get("smart_ai_model")
    if (isinstance(model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,119}", model)
            and "cloud" not in model.casefold() and "://" not in model
            and ".." not in model and model.count(":") <= 1):
        result["smart_ai_model"] = model
    return result

class Settings:
    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "auralyn-terminal" / "settings.json"
        self.data = dict(DEFAULTS)
        self.runtime_overrides = {}
        self.error = ""
        try:
            self.data = validate(json.loads(self.path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeError) as exc:
            self.error = f"Einstellungen konnten nicht gelesen werden: {exc}"

    def __getitem__(self, key: str):
        return self.runtime_overrides.get(key, self.data[key])

    def set(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        self.runtime_overrides.pop(key, None)
        self.data = validate({**self.data, key: value})
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".settings-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass

    @property
    def alpha(self) -> float:
        """Transparency is NOT opacity: 75% transparent means alpha 0.25."""
        return (100 - self.data["transparency"]) / 100.0
