#!/usr/bin/env python3
"""Выгрузка метаданных баз YDB по файлу путей /<region>/<cloud-id>/<database-id>."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yc_snippets.ydb_export import main

raise SystemExit(main())
