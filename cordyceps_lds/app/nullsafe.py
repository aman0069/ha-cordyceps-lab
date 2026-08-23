"""Contractual handling for unavailable readings."""
from __future__ import annotations

import math
from typing import Any

_MISSING = {"unknown", "unavailable", "none", ""}


def coerce(value: Any) -> tuple[Any | None, str]:
    """Preserve readings or record unavailable input as SQL NULL with missing source."""
    if value is None or (isinstance(value, str) and value.strip().lower() in _MISSING):
        return None, "missing"
    return value, "sensor"


def vpd_kpa(temp: float | None, rh: float | None) -> float | None:
    """Calculate vapour pressure deficit in kPa only when both inputs exist."""
    if temp is None or rh is None:
        return None
    saturation_vapour_pressure = 0.6108 * math.exp((17.27 * float(temp)) / (float(temp) + 237.3))
    return saturation_vapour_pressure * (1.0 - float(rh) / 100.0)
