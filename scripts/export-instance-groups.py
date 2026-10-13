#!/usr/bin/env python3
"""Инстанс-группы instance-group-<database-id> по уже выгруженным описаниям баз YDB."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from yc_snippets.instance_groups import main

raise SystemExit(main())
