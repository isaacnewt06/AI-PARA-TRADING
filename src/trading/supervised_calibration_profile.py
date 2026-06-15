"""Load optional supervised calibration profiles for trading quality engines."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


PROFILE_PATH = Path("data/datasets/v56_2025_supervised_calibration_profile.json")


@lru_cache(maxsize=1)
def load_v56_supervised_profile() -> dict[str, Any]:
    """Return the generated v56 supervised calibration profile if available."""
    if not PROFILE_PATH.exists():
        return {}
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def v56_thresholds() -> dict[str, float]:
    profile = load_v56_supervised_profile()
    thresholds = profile.get("thresholds") if isinstance(profile, dict) else None
    if not isinstance(thresholds, dict):
        return {}
    result: dict[str, float] = {}
    for key, value in thresholds.items():
        try:
            result[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return result
