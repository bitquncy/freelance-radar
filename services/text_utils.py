"""Text utilities for safe HTML/Markdown rendering."""
import html as _html
import re


def esc(text: str) -> str:
    """HTML-escape text safely."""
    return _html.escape(str(text)) if text else ""


def esc_md(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    if not text:
        return ""
    chars = r"[_*\[\]()~`>#+\-=|{}.!]"
    return re.sub(chars, r"\\\g<0>", str(text))


def truncate(text: str, max_len: int = 200, suffix: str = "\u2026") -> str:
    """Truncate text to max_len characters."""
    if not text or len(text) <= max_len:
        return text or ""
    return text[:max_len].rsplit(" ", 1)[0] + suffix
