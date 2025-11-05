from __future__ import annotations
import json
from pathlib import Path
from typing import Dict

from dashboard_app.models import User
from dashboard_app.extensions import db
from tracker_alert.services.schedule_utils import MANUAL_OVERRIDE_KEY


USER_CACHE: Dict[str, dict] | None = None
USER_CACHE_MTIME: float | None = None
USER_CACHE_PATH: Path | None = None


def _should_reload(cache_path: Path) -> bool:
    """Check if cached schedules should be refreshed."""
    global USER_CACHE_MTIME, USER_CACHE_PATH
    if USER_CACHE is None:
        return True

    try:
        current_mtime = cache_path.stat().st_mtime
    except FileNotFoundError:
        return False

    if USER_CACHE_PATH != cache_path:
        return True
    return USER_CACHE_MTIME is None or USER_CACHE_MTIME < current_mtime


def load_user_schedules(path: Path | str = 'config/user_schedules.json', *, force: bool = False) -> Dict[str, dict]:
    """Load schedules from JSON with lightweight caching."""
    global USER_CACHE, USER_CACHE_MTIME, USER_CACHE_PATH

    file_path = Path(path).resolve()

    if force or _should_reload(file_path):
        with open(file_path, encoding='utf-8') as f:
            data = json.load(f)
        USER_CACHE = data.get('users', {})
        try:
            USER_CACHE_MTIME = file_path.stat().st_mtime
        except FileNotFoundError:
            USER_CACHE_MTIME = None
        USER_CACHE_PATH = file_path

    return USER_CACHE


def clear_user_schedule_cache() -> None:
    """Reset in-memory cache (useful for tests or manual reloads)."""
    global USER_CACHE, USER_CACHE_MTIME, USER_CACHE_PATH
    USER_CACHE = None
    USER_CACHE_MTIME = None
    USER_CACHE_PATH = None


def get_user_schedule(name_or_email: str) -> dict | None:
    schedules = load_user_schedules()
    lower = name_or_email.lower()
    for name, info in schedules.items():
        email = (info.get('email') or '').lower()
        if lower == email or lower == name.lower():
            info_copy = dict(info)
            info_copy.pop(MANUAL_OVERRIDE_KEY, None)
            info_copy['name'] = name
            return info_copy
    return None


def upsert_user_from_schedule(name: str, info: dict) -> User:
    email = (info.get('email') or '').strip().lower()
    if not email:
        raise ValueError(f"Користувач {name} не має email")

    user = User.query.filter_by(email=email).first()
    manager = info.get('control_manager')
    manager_filter = str(manager) if manager not in (None, '') else ''

    if not user:
        user = User(
            email=email,
            name=name,
            manager_filter=manager_filter,
            is_admin=False
        )
        user.set_password('ChangeMe123')
        db.session.add(user)
    else:
        user.name = name
        user.manager_filter = manager_filter

    return user


def sync_users_from_schedule(schedule_path: Path | str = 'config/user_schedules.json') -> None:
    data = load_user_schedules(schedule_path, force=True)
    for name, info in data.items():
        upsert_user_from_schedule(name, info)
    db.session.commit()
