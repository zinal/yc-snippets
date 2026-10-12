#!/usr/bin/env python3
"""Пересобрать каталог команд из локальной справки yc.

Каталог — слепок CLI, а не ручной список. Запускайте после обновления yc:

    python scripts/refresh_catalog.py
    python scripts/refresh_catalog.py --yc ~/yandex-cloud/bin/yc
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yc_snippets.catalog import catalog_path, load_catalog, validate_catalog  # noqa: E402
from yc_snippets.classify import build_entries  # noqa: E402
from yc_snippets.yc_walk import walk_list_commands  # noqa: E402


def yc_version(yc: str) -> str:
    completed = subprocess.run([yc, "version"], capture_output=True, text=True, check=False)
    line = (completed.stdout or completed.stderr).strip().splitlines()
    return line[0] if line else "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Обновить src/yc_snippets/data/inventory.json из yc --help")
    parser.add_argument("--yc", default="yc", help="Путь к бинарнику yc")
    args = parser.parse_args()
    raw_commands = walk_list_commands(args.yc)
    entries = build_entries(raw_commands)
    payload = {
        "source": {
            "interface": "yc",
            "version": yc_version(args.yc),
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "docs": "https://yandex.cloud/ru/docs/cli/cli-ref/",
            "api": "https://github.com/yandex-cloud/cloudapi",
            "notes": (
                "Команды собраны из локальной справки yc, без обращений к API. "
                "default=true только у метаданных созданных ресурсов. "
                "Вложенные команды (scope=parent) описаны, но раннер их не выполняет: "
                "для них нужен идентификатор родителя."
            ),
        },
        "commands": [entry.to_json() for entry in entries],
    }
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    errors = validate_catalog(load_catalog(path))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    defaults = sum(1 for entry in entries if entry.default)
    print(f"wrote {path} commands={len(entries)} default={defaults}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
