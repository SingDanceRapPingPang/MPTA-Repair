#!/usr/bin/env python3
"""CLI wrapper for the multi-property clock-bound repair engine."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.repair.multi_property_repair import main


if __name__ == "__main__":
    raise SystemExit(main())

