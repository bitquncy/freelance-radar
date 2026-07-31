"""Одноразовая миграция: эмодзи-литералы -> emoji_config.E / emoji_config.P.

Правило выбора набора (важно, иначе тег протечёт пользователю):
    * строка с ``InlineKeyboardButton`` / ``ReplyKeyboardMarkup`` / ``show_alert``
      / ``BotCommand`` -> plain ``P.*``;
    * файл с ``parse_mode="HTML"`` -> в остальных строках ``E.*``;
    * файл на Markdown или без parse_mode -> всегда ``P.*``.

Скрипт идемпотентен: уже миграированные строки не содержат литералов.
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import emoji_config  # noqa: E402

#: Unicode -> имя константы в P/E. Строится из P, чтобы имена не расходились.
NAME_BY_ICON = {
    value: name
    for name, value in vars(emoji_config.P).items()
    if isinstance(value, str) and not name.startswith("_")
}

# Литералы, встречающиеся в коде как \U0001f4cb и т.п.
# Составные эмодзи (например «⚠️» = знак + VS16) не имеют
# одного escape-кода, поэтому берём только односимвольные.
ESCAPED = {
    f"\\U{ord(icon):08x}": icon for icon in NAME_BY_ICON if len(icon) == 1
}

PLAIN_MARKERS = (
    "InlineKeyboardButton",
    "ReplyKeyboardMarkup",
    "show_alert",
    "BotCommand",
    "keyboard = [",
)

TARGETS_PLAIN = [
    "bot/keyboards.py",
    "bot/handlers/broadcast_handler.py",
    "bot/handlers/kwork_filters_handler.py",
    "bot/handlers/profile_handler.py",
    "bot/handlers/settings_handler.py",
    "bot/handlers/sources_handler.py",
    "bot/handlers/tg_analysis_handler.py",
    "constants.py",
    "services/charts.py",
]
TARGETS_HTML = [
    "bot/handlers/jobs_handler.py",
    "services/formatters.py",
    "services/scheduler.py",
]

STRING_RE = re.compile(r"""(['"])(?:\\.|(?!\1).)*\1""")


def _icon_pattern() -> re.Pattern[str]:
    icons = sorted(NAME_BY_ICON, key=len, reverse=True)
    escaped = sorted(ESCAPED, key=len, reverse=True)
    return re.compile("|".join(re.escape(token) for token in icons + escaped))


ICON_RE = _icon_pattern()


def _convert_line(line: str, cls: str) -> tuple[str, int]:
    """Заменить иконки внутри строковых литералов на ``cls.NAME``."""
    count = 0

    def replace_string(match: re.Match[str]) -> str:
        nonlocal count
        literal = match.group(0)
        quote = literal[0]
        body = literal[1:-1]
        if not ICON_RE.search(body):
            return literal
        # Собираем f-string: иконки становятся {P.NAME} / {E.NAME}.
        def sub_icon(icon_match: re.Match[str]) -> str:
            nonlocal count
            token = icon_match.group(0)
            icon = ESCAPED.get(token, token)
            name = NAME_BY_ICON.get(icon)
            if name is None:
                return token
            count += 1
            return f"{{{cls}.{name}}}"

        new_body = ICON_RE.sub(sub_icon, body)
        if new_body == body:
            return literal
        new_body = new_body.lstrip()
        prefix = "f"
        if literal_is_fstring(match, line):
            prefix = ""
        return f"{prefix}{quote}{new_body}{quote}"

    return STRING_RE.sub(replace_string, line), count


def literal_is_fstring(match: re.Match[str], line: str) -> bool:
    """Уже ли этот литерал является f-строкой (тогда префикс не дублируем)."""
    start = match.start()
    return start > 0 and line[start - 1] in "fF"


def _ensure_import(lines: list[str], names: set[str]) -> list[str]:
    """Добавить ``from emoji_config import ...`` после последнего импорта."""
    if not names:
        return lines
    joined = "".join(lines)
    if "from emoji_config import" in joined:
        return lines
    statement = f"from emoji_config import {', '.join(sorted(names))}\n"
    last_import = -1
    for index, line in enumerate(lines):
        if line.startswith(("import ", "from ")):
            last_import = index
    if last_import == -1:  # модуль без импортов — после docstring
        insert_at = 1 if lines and lines[0].startswith('"""') else 0
        return lines[:insert_at] + [statement] + lines[insert_at:]
    return lines[: last_import + 1] + [statement] + lines[last_import + 1 :]


def migrate(path: Path, html: bool) -> int:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    changed = 0
    used: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("#", '"""', "'''")) or not ICON_RE.search(line):
            out.append(line)
            continue
        plain = any(marker in line for marker in PLAIN_MARKERS) or not html
        cls = "P" if plain else "E"
        new_line, count = _convert_line(line, cls)
        if count:
            used.add(cls)
        changed += count
        out.append(new_line)
    if changed:
        out = _ensure_import(out, used)
        path.write_text("".join(out), encoding="utf-8")
    return changed


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    total = 0
    for rel in TARGETS_PLAIN:
        total += migrate(ROOT / rel, html=False)
    for rel in TARGETS_HTML:
        total += migrate(ROOT / rel, html=True)
    print(f"replaced {total} icon literals")


if __name__ == "__main__":
    main()
