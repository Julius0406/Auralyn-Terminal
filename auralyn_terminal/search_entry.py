"""Immutable, reviewed help entries; never interpolate user text into actions."""
from __future__ import annotations
from dataclasses import dataclass
import shlex


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    text: str
    examples: tuple[str, ...]
    steps: tuple[tuple[str, ...], ...] = ()
    warning: str = ''
    ui: str = ''
    preview: str = ''  # Display-only template: NEVER grants execution permission.

    @property
    def command(self) -> str:
        return ' && '.join(shlex.join(argv) for argv in self.steps) if self.steps else self.preview

    @property
    def executable(self) -> bool:
        return bool(self.steps)

