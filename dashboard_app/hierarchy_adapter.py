from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable

from tracker_alert.services.control_manager import auto_assign_control_manager
from tracker_alert.services.schedule_utils import has_manual_override, clear_manual_override


def load_level_grade_data(base_dir: str | None = None) -> list[dict]:
    """Load Level_Grade.json as list of entries."""
    base_dir = base_dir or os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(base_dir, 'config', 'Level_Grade.json')
    if not os.path.exists(path):
        return []
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f) or []


_WORD_CASE_OVERRIDES = {
    'bizdev': 'BizDev',
    'bizdevs': 'BizDevs',
    'bizdevteam': 'BizDevTeam',
    'ios': 'IOS',
    'mb': 'MB',
    'rtb': 'RTB',
    'cpa': 'CPA',
    'c&b': 'C&B',
    'l&d': 'L&D',
    'hr': 'HR',
    'qa': 'QA',
}


def _clean_value(value: object | None) -> str:
    if value in (None, '-', ''):
        return ''
    text = str(value).strip()
    if not text:
        return ''
    if text.lower().endswith(' division'):
        text = text[: -len(' division')].strip()
    return text


def canonicalize_label(value: object | None) -> str:
    text = _clean_value(value)
    if not text:
        return ''
    tokens = re.split(r'(\s+)', text)
    normalized = []
    for token in tokens:
        if not token or token.isspace():
            normalized.append(token)
            continue
        cleaned = token.strip()
        key = cleaned.lower()
        if key in _WORD_CASE_OVERRIDES:
            normalized.append(_WORD_CASE_OVERRIDES[key])
            continue
        if len(cleaned) <= 3 and cleaned.isalpha():
            normalized.append(cleaned.upper())
            continue
        normalized.append(cleaned.capitalize())
    return ''.join(normalized).strip()
    return text


def _normalize_for_match(value: object | None) -> str:
    return _clean_value(value).lower()


def find_level_grade_match(
    manager_name: str | None,
    division: str | None,
    direction: str | None,
    unit: str | None,
    team: str | None,
    entries: Iterable[dict],
) -> dict | None:
    """Find the best Level_Grade entry for provided hierarchy."""
    manager_norm = _normalize_for_match(manager_name)
    if manager_norm:
        for entry in entries:
            entry_manager = _normalize_for_match(entry.get('Manager'))
            if entry_manager and entry_manager == manager_norm:
                return entry

    division_norm = _normalize_for_match(division)
    direction_norm = _normalize_for_match(direction)
    unit_norm = _normalize_for_match(unit)
    team_norm = _normalize_for_match(team)

    best_match = None
    best_score = 0
    for entry in entries:
        entry_division = _normalize_for_match(entry.get('Division'))
        entry_direction = _normalize_for_match(entry.get('Direction'))
        entry_unit = _normalize_for_match(entry.get('Unit'))
        entry_team = _normalize_for_match(entry.get('Team'))

        score = 0
        if direction_norm:
            if entry_direction and entry_direction == direction_norm:
                score += 10
            elif entry_team and entry_team == direction_norm:
                score += 10
            elif entry_unit and entry_unit == direction_norm:
                score += 10
        if unit_norm and entry_unit and entry_unit == unit_norm:
            score += 5
        if team_norm and entry_team and entry_team == team_norm:
            score += 5
        if division_norm and entry_division and entry_division == division_norm:
            score += 1

        if score > best_score:
            best_score = score
            best_match = entry
    return best_match


def build_adapted_hierarchy(entry: dict, fallback_location: str = '') -> dict:
    """Build normalized hierarchy dict from Level_Grade entry."""
    if not entry:
        return {}
    project = canonicalize_label(entry.get('Division'))
    adapted = {
        'project': project,
        'department': canonicalize_label(entry.get('Direction')),
        'unit': canonicalize_label(entry.get('Unit')),
        'team': canonicalize_label(entry.get('Team')),
    }
    location = canonicalize_label(entry.get('Location'))
    adapted['location'] = location or (fallback_location or '')
    division_for_manager = adapted['project'] or project
    adapted['control_manager'] = auto_assign_control_manager(division_for_manager or '')
    return adapted


def apply_adapted_hierarchy(user_info: Dict[str, Any], adapted: dict, *, force: bool = False) -> list[str]:
    """Apply adapted hierarchy values to user_info respecting manual overrides."""
    if not isinstance(user_info, dict) or not adapted:
        return []

    changed: list[str] = []

    def update_field(field: str, value: str | int | None) -> None:
        if value in (None, ''):
            return
        if isinstance(value, str):
            value_to_set = canonicalize_label(value)
        else:
            value_to_set = value
        if has_manual_override(user_info, field):
            if not force:
                return
            clear_manual_override(user_info, field)
        if user_info.get(field) == value_to_set:
            return
        user_info[field] = value_to_set
        changed.append(field)

    mapping = [
        ('division_name', 'project'),
        ('direction_name', 'department'),
        ('unit_name', 'unit'),
        ('team_name', 'team'),
    ]
    for new_field, src_key in mapping:
        update_field(new_field, adapted.get(src_key))

    for key in ('project', 'department', 'unit', 'team'):
        update_field(key, adapted.get(key))

    if adapted.get('location'):
        update_field('location', adapted['location'])

    control_manager = adapted.get('control_manager')
    if control_manager is not None:
        update_field('control_manager', control_manager)

    return changed


def get_adapted_hierarchy_for_user(user_name: str, user_info: dict, entries: list[dict]) -> dict | None:
    """Find and build adapted hierarchy dict for a schedule user."""
    manager_name = user_info.get('team_lead') or user_info.get('manager_name') or ''
    division = user_info.get('division_name') or user_info.get('project') or ''
    direction = user_info.get('direction_name') or user_info.get('department') or ''
    unit = user_info.get('unit_name') or user_info.get('unit') or ''
    team = user_info.get('team_name') or user_info.get('team') or ''

    match = find_level_grade_match(manager_name, division, direction, unit, team, entries)
    if not match:
        return None
    fallback_location = user_info.get('location', '')
    return build_adapted_hierarchy(match, fallback_location=fallback_location)
