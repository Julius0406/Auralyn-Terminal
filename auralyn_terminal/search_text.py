"""Text normalization for matching only; never used to rewrite shell input."""
from __future__ import annotations
import re
import unicodedata


def normalize(text: str) -> str:
    text = text.casefold().replace('ß', 'ss')
    text = ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+', text))
