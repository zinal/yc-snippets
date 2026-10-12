"""Обход локальной справки ``yc`` и сбор команд ``list``.

Справка не ходит в API и не требует аутентификации. Так каталог остаётся
слепком установленного CLI, а не списком команд по памяти.
"""

from __future__ import annotations

import re
import subprocess
from collections import deque

from yc_snippets.classify import RawListCommand

_SECTION_RE = re.compile(r"^(Groups|Commands|Flags):")
_ENTRY_RE = re.compile(r"^  (\S+)\s+(.*)$")
_FLAG_RE = re.compile(r"^\s+(--\S+)\s*(.*)$")


def parse_help(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str], str]:
    """Вернуть группы, команды, имена флагов и первую строку описания."""

    groups: list[tuple[str, str]] = []
    commands: list[tuple[str, str]] = []
    flags: list[str] = []
    section: str | None = None
    description = ""
    for line in text.splitlines():
        if not description and line.strip() and not line.startswith("Usage:") and not line.startswith(" "):
            description = line.strip()
        header = _SECTION_RE.match(line)
        if header:
            section = header.group(1)
            continue
        if section in {"Groups", "Commands"}:
            if line.startswith("Use ") or line.startswith("Flags:") or line.startswith("Aliases:"):
                section = "Flags" if line.startswith("Flags:") else None
                continue
            match = _ENTRY_RE.match(line)
            if match:
                name, desc = match.group(1), match.group(2).strip()
                if name in {"-h", "--help"}:
                    continue
                (groups if section == "Groups" else commands).append((name, desc))
            elif line and not line.startswith(" "):
                section = None
        elif section == "Flags":
            if line.startswith("Use ") or (line and not line.startswith(" ")):
                section = None
                continue
            match = _FLAG_RE.match(line)
            if match:
                flags.append(match.group(1))
    return groups, commands, flags, description


def _help_text(yc: str, args: list[str]) -> str:
    completed = subprocess.run([yc, *args, "--help"], capture_output=True, text=True, check=False)
    return f"{completed.stdout}\n{completed.stderr}"


def walk_list_commands(yc: str = "yc") -> list[RawListCommand]:
    """Обойти дерево групп ``yc`` и собрать команды, которые заканчиваются на ``list``."""

    seen: set[tuple[str, ...]] = set()
    queue: deque[list[str]] = deque([[]])
    found: dict[str, RawListCommand] = {}

    while queue:
        path = queue.popleft()
        key = tuple(path)
        if key in seen or "v0" in key:
            continue
        seen.add(key)
        groups, commands, _, _ = parse_help(_help_text(yc, path))
        for name, _desc in groups:
            if name == "v0":
                continue
            queue.append([*path, name])
        if any(name == "list" for name, _desc in commands):
            list_path = [*path, "list"]
            _, _, flags, description = parse_help(_help_text(yc, list_path))
            argv = tuple(list_path)
            command_key = ".".join(list_path[:-1])
            found[command_key] = RawListCommand(argv=argv, description=description, flags=tuple(flags))
    return [found[key] for key in sorted(found)]
