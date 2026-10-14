#!/usr/bin/env python3
"""Платформа, ядра, память, размер и одна зона существующей инстанс-группы."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from yc_snippets.adjust_instance_group import main

raise SystemExit(main())
