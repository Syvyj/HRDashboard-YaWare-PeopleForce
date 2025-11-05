"""Utility helpers for working with manual overrides in user schedules."""
from __future__ import annotations

from typing import Any, Dict

MANUAL_OVERRIDE_KEY = "_manual_overrides"


def set_manual_override(info: Dict[str, Any], field: str, enabled: bool = True) -> None:
    """Mark or unmark a field as manually overridden."""
    if not isinstance(info, dict):
        return
    manual = info.setdefault(MANUAL_OVERRIDE_KEY, {})
    if not isinstance(manual, dict):
        manual = {}
        info[MANUAL_OVERRIDE_KEY] = manual
    if enabled:
        manual[field] = True
    else:
        manual.pop(field, None)
        if not manual:
            info.pop(MANUAL_OVERRIDE_KEY, None)


def clear_manual_override(info: Dict[str, Any], field: str) -> None:
    """Remove manual override flag for a field."""
    set_manual_override(info, field, enabled=False)


def has_manual_override(info: Dict[str, Any], field: str) -> bool:
    """Check if a schedule field is marked as manually overridden."""
    if not isinstance(info, dict):
        return False
    manual = info.get(MANUAL_OVERRIDE_KEY)
    if not isinstance(manual, dict):
        return False
    return bool(manual.get(field))
