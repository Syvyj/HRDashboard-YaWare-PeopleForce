"""Utilities for assigning control managers."""
from __future__ import annotations


def auto_assign_control_manager(division_name: str) -> int:
    """
    Автоматичне призначення control_manager на основі division_name.
    
    - Agency → 1
    - Apps, Adnetwork, Consulting → 2
    - Інші → 2 (значення за замовчуванням)
    """
    division_normalized = (division_name or "").strip().lower()
    
    if division_normalized == "agency":
        return 1
    if division_normalized in ("apps", "adnetwork", "consulting"):
        return 2
    return 3
