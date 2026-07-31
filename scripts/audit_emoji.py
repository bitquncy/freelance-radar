"""Аудит эмодзи-литералов: находит места, где иконка вписана в код напрямую
вместо :class:`emoji_config.E` / :class:`emoji_config.P`.

Запуск: ``python scripts/audit_emoji.py``

Отдельно предупреждает о самой опасной ошибке — использовании HTML-набора
``E.*`` в подписи ``InlineKeyboardButton`` или в ``show_alert``, где Telegram
не парсит HTML и тег ``<tg-emoji>`` протёк бы пользователю как текст.
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

EMOJI_RANGES = (
    "[\U0001f000-\U0001faff"
    "\u2190-\u21ff\u2600-\u27bf\u2b00-\u2bff"
    "\u23e9-\u23fa\u2705\u274c\u2757\u2b50\u26d4]"
)
EMOJI_RE = re.compile(EMOJI_RANGES)
ESCAPED_RE = re.compile(r"\\U0001f[0-9a-f]{3}")
STRING_RE = re.compile(r"""(['"]).*?\1""", re.S)

SKIP_DIRS = {"venv", "__pycache__", ".mypy_cache", ".git", "tests", "scripts"}
SKIP_FILES = {"emoji_config.py", "emoji_config.py.bak"}


def _iter_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        if SKIP_DIRS & set(path.parts) or path.name in SKIP_FILES:
            continue
        yield path


def audit(root: Path) -> int:
    literals: list[str] = []
    html_in_plain: list[str] = []
    for path in _iter_files(root):
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith(("#", '"""', "'''", "*", ":")):
                continue
            in_string = bool(STRING_RE.search(line))
            if in_string and (EMOJI_RE.search(line) or ESCAPED_RE.search(line)):
                literals.append(f"{path}:{number}: {stripped[:88]}")
            # E.* внутри кнопки/алерта — HTML там не парсится.
            if ("InlineKeyboardButton(" in line or "show_alert" in line) and re.search(
                r"\bE\.[A-Z_]+", line
            ):
                html_in_plain.append(f"{path}:{number}: {stripped[:88]}")

    out = sys.stdout
    if literals:
        out.write(f"Сырые эмодзи-литералы ({len(literals)}):\n")
        out.write("\n".join(f"  {item}" for item in literals) + "\n")
    else:
        out.write("Сырых эмодзи-литералов нет.\n")
    if html_in_plain:
        out.write(f"\nОШИБКА: E.* в plain-контексте ({len(html_in_plain)}):\n")
        out.write("\n".join(f"  {item}" for item in html_in_plain) + "\n")
    else:
        out.write("E.* в кнопках/алертах не найдено.\n")
    return 1 if html_in_plain else 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    raise SystemExit(audit(Path(__file__).resolve().parent.parent))
