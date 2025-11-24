from __future__ import annotations

import os
import json
import logging
from collections import defaultdict
from functools import lru_cache
from html import escape
from datetime import datetime, date, timedelta
from io import BytesIO
from urllib.parse import unquote
from importlib import import_module
import threading

from flask import Blueprint, request, jsonify, send_file, abort, current_app
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash
from sqlalchemy import or_
from openpyxl import Workbook
from openpyxl.styles import Alignment, PatternFill, Font, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.cell.cell import MergedCell
from .extensions import db
from .models import AttendanceRecord, User, AdminAuditLog
from .user_data import get_user_schedule, load_user_schedules, clear_user_schedule_cache
from tracker_alert.services import user_manager as schedule_user_manager
from tracker_alert.services.schedule_utils import (
    set_manual_override,
    clear_manual_override,
    has_manual_override,
)
from tracker_alert.services.attendance_monitor import AttendanceMonitor
from tracker_alert.client.peopleforce_api import PeopleForceClient
from tracker_alert.services.control_manager import auto_assign_control_manager
from .hierarchy_adapter import (
    load_level_grade_data,
    find_level_grade_match,
    build_adapted_hierarchy,
    apply_adapted_hierarchy,
    get_adapted_hierarchy_for_user,
    canonicalize_label,
)

logger = logging.getLogger(__name__)
from tracker_alert.client.yaware_v2_api import YaWareV2Client
from tasks.update_attendance import update_for_date

try:
    from reportlab.lib import colors  # type: ignore[import]
    from reportlab.lib.pagesizes import A4, landscape  # type: ignore[import]
    from reportlab.lib.units import mm  # type: ignore[import]
    from reportlab.pdfbase import pdfmetrics  # type: ignore[import]
    from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import]
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle, Paragraph  # type: ignore[import]
    from reportlab.lib.styles import ParagraphStyle  # type: ignore[import]
except ImportError:  # pragma: no cover
    colors = A4 = landscape = mm = None
    SimpleDocTemplate = Spacer = Table = TableStyle = Paragraph = None
    ParagraphStyle = None
    pdfmetrics = TTFont = None

api_bp = Blueprint('api', __name__)

DEFAULT_SYNC_PASSWORD = 'ChangeMe123'


@lru_cache(maxsize=1024)
def _password_matches_default(hash_value: str | None) -> bool:
    if not hash_value:
        return False
    try:
        return check_password_hash(hash_value, DEFAULT_SYNC_PASSWORD)
    except Exception:  # pragma: no cover
        return False


_LOCATION_REPLACEMENTS: dict[str, str] = {
    'remote ukraine': 'UA',
    'remote other countries': 'Remote',
    'Warsaw office Warsaw, PL': 'Warsaw, PL',
    'Prague office': 'Prague, CZ'
}


_MANUAL_PROTECTED_FIELDS = {'start_time', 'location'}


def _normalize_location_label(raw: object | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    replacement = _LOCATION_REPLACEMENTS.get(value.casefold())
    return replacement if replacement is not None else value


def _generate_telegram_username(full_name: str) -> str:
    """
    Генерує telegram username з повного імені у форматі Прізвище_Ім'я.
    Наприклад: "Kutkovskyi Mykhailo" -> "Kutkovskyi_Mykhailo"
    """
    if not full_name:
        return ''
    
    # Видаляємо зайві пробіли та розділяємо
    parts = full_name.strip().split()
    if len(parts) < 2:
        # Якщо тільки одне слово - повертаємо як є
        return parts[0] if parts else ''
    
    # Беремо перше слово (прізвище) та друге слово (ім'я)
    surname = parts[0]
    first_name = parts[1]
    
    return f"{surname}_{first_name}"

@lru_cache(maxsize=1)
def _schedule_identity_sets() -> tuple[set[str], set[str], set[str]]:
    schedules = load_user_schedules()
    names: set[str] = set()
    emails: set[str] = set()
    ids: set[str] = set()
    for name, info in schedules.items():
        if name:
            names.add(name.strip().lower())
        if isinstance(info, dict):
            email = str(info.get('email') or '').strip().lower()
            if email:
                emails.add(email)
            user_id = str(info.get('user_id') or '').strip().lower()
            if user_id:
                ids.add(user_id)
    return names, emails, ids


def _get_scheduler():
    """Дістати активний APScheduler."""
    try:
        sched = current_app.config.get('SCHEDULER')
        if sched:
            return sched
    except Exception:
        pass
    try:
        module = import_module('dashboard_app.tasks')
        sched = getattr(module, 'SCHEDULER', None)
        if not sched and current_app:
            register_fn = getattr(module, 'register_tasks', None)
            if register_fn and current_app.config.get("ENABLE_SCHEDULER"):
                register_fn(current_app)
                sched = getattr(module, 'SCHEDULER', None)
        return sched
    except Exception:
        return None


def _get_scheduler_logs():
    try:
        logs = current_app.config.get('SCHEDULER_LOG')
        if logs is not None:
            return logs
    except Exception:
        pass
    try:
        module = import_module('dashboard_app.tasks')
        return getattr(module, 'SCHEDULER_LOG', [])
    except Exception:
        return []


def _append_scheduler_log(job_id: str, status: str, message: str = "") -> None:
    try:
        module = import_module('dashboard_app.tasks')
        append_fn = getattr(module, 'append_scheduler_log', None)
        if append_fn:
            append_fn(job_id, status, message)
    except Exception:
        pass


def _job_to_dict(job):
    next_run = job.next_run_time.isoformat() if job.next_run_time else None
    return {
        'id': job.id,
        'name': getattr(job.func, '__name__', str(job.func)),
        'trigger': str(job.trigger),
        'next_run_time': next_run,
        'pending': getattr(job, 'pending', False),
        'paused': getattr(job, 'paused', False),
    }

MANUAL_FLAG_MAP = {
    'scheduled_start': 'manual_scheduled_start',
    'actual_start': 'manual_actual_start',
    'minutes_late': 'manual_minutes_late',
    'non_productive_minutes': 'manual_non_productive_minutes',
    'not_categorized_minutes': 'manual_not_categorized_minutes',
    'productive_minutes': 'manual_productive_minutes',
    'total_minutes': 'manual_total_minutes',
    'corrected_total_minutes': 'manual_corrected_total_minutes',
    'status': 'manual_status',
    'notes': 'manual_notes',
    'leave_reason': 'manual_leave_reason',
}
MANUAL_TRACKED_FIELDS = tuple(MANUAL_FLAG_MAP.keys())




def _minutes_to_str(minutes: int | None) -> str:
    if minutes is None:
        return ''
    hrs = minutes // 60
    mins = minutes % 60
    return f"{hrs:02d}:{mins:02d}"


def _minutes_to_hm(minutes: int | None) -> str:
    if minutes in (None, ''):
        return ''
    try:
        total_minutes = int(minutes)
    except (TypeError, ValueError):
        return ''
    hrs = total_minutes // 60
    mins = total_minutes % 60
    return f"{hrs:02d}:{mins:02d}"


def _format_time_hm(value: str | None) -> str:
    if not value:
        return ''
    value = value.strip()
    if not value:
        return ''
    parts = value.split(':')
    if len(parts) == 1:
        try:
            hour = int(parts[0])
        except ValueError:
            return ''
        return f"{hour:02d}:00"
    if len(parts) == 2:
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except ValueError:
            return ''
        return f"{hour:02d}:{minute:02d}"
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2])
    except ValueError:
        return ''
    if second >= 30:
        minute += 1
        if minute >= 60:
            minute = 0
            hour += 1
    return f"{hour:02d}:{minute:02d}"


def _parse_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _parse_duration(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(':')
    try:
        if len(parts) == 1:
            return int(parts[0]) * 60
        if len(parts) >= 2:
            hours = int(parts[0])
            minutes = int(parts[1])
            return hours * 60 + minutes
    except ValueError:
        return None
    return None


def _normalize_user_key(user_key: str) -> str:
    return unquote(user_key).strip()


def _normalize_name(name: str) -> str:
    """Normalize name for matching: lowercase, single spaces, sorted words."""
    if not name:
        return ''
    # Remove extra spaces, lowercase
    normalized = ' '.join(name.lower().split())
    # Split into words and sort (so "Maksym Kudko" == "Kudko Maksym")
    words = sorted(normalized.split())
    return ' '.join(words)


def _diff_key_candidates(*values) -> set[str]:
    keys: set[str] = set()
    for value in values:
        if value in (None, ''):
            continue
        text = str(value).strip().lower()
        if text:
            keys.add(text)
            # Add normalized name variant
            if '@' not in text:  # It's a name, not email
                normalized = _normalize_name(text)
                if normalized:
                    keys.add(normalized)
    return keys


def _humanize_entry(name: str, email: str, user_id: str) -> str:
    if name and email:
        return f"{name} ({email})"
    if name:
        return name
    if email:
        return email
    return user_id or '—'


def _load_schedule_entries() -> list[dict]:
    data = schedule_user_manager.load_users()
    users = data.get('users', {}) if isinstance(data, dict) else {}
    entries: list[dict] = []
    for name, raw in users.items():
        if not isinstance(raw, dict):
            continue
        email = str(raw.get('email') or '').strip()
        user_id = str(raw.get('user_id') or '').strip()
        peopleforce_id = str(raw.get('peopleforce_id') or '').strip()
        if _is_ignored_person(name, email):
            continue
        keys = _diff_key_candidates(name, email, user_id, peopleforce_id)
        entries.append({
            'name': name,
            'email': email,
            'user_id': user_id,
            'peopleforce_id': peopleforce_id,
            'keys': keys,
            'in_yaware': False,
            'in_peopleforce': False,
        })
    return entries


def _extract_yaware_entries() -> tuple[list[dict], str | None]:
    try:
        client = YaWareV2Client()
        raw_items = client.get_users(active_only=True) or []
    except Exception as exc:  # pragma: no cover - network failure
        return [], str(exc)

    entries: list[dict] = []
    for item in raw_items:
        firstname = str(item.get('firstname') or '').strip()
        lastname = str(item.get('lastname') or '').strip()
        full_name = ' '.join(part for part in (firstname, lastname) if part).strip() or str(item.get('name') or '').strip()
        if not full_name:
            full_name = str(item.get('user') or '').split(',')[0].strip()
        email = str(item.get('email') or item.get('user_email') or '').strip().lower()
        user_id = str(item.get('id') or item.get('user_id') or '').strip()
        if _is_ignored_person(full_name, email):
            continue
        keys = _diff_key_candidates(full_name, email, user_id)
        entries.append({
            'name': full_name,
            'email': email,
            'user_id': user_id,
            'keys': keys,
        })
    return entries, None


def _extract_peopleforce_entries(force_refresh: bool = False) -> tuple[list[dict], str | None]:
    try:
        client = PeopleForceClient()
        raw_items = client.get_employees(force_refresh=force_refresh) or []
    except Exception as exc:  # pragma: no cover - network failure
        return [], str(exc)

    # Load schedule data to get position, telegram, team_lead
    schedule_data = schedule_user_manager.load_users() if schedule_user_manager else {}
    schedule_by_email = {}
    if isinstance(schedule_data, dict):
        for name, info in schedule_data.get('users', {}).items():
            if isinstance(info, dict):
                email = (info.get('email') or '').strip().lower()
                if email:
                    schedule_by_email[email] = info
    
    # Get YaWare entries to match by email and name
    yaware_entries, _ = _extract_yaware_entries()
    yaware_by_email = {}
    yaware_by_name = {}
    for entry in yaware_entries:
        email = (entry.get('email') or '').strip().lower()
        if email:
            yaware_by_email[email] = entry
        name = entry.get('name', '')
        if name:
            normalized_name = _normalize_name(name)
            if normalized_name:
                yaware_by_name[normalized_name] = entry

    entries: list[dict] = []
    today = date.today()
    for item in raw_items:
        full_name = str(item.get('full_name') or '').strip()
        if not full_name:
            first = str(item.get('first_name') or '').strip()
            last = str(item.get('last_name') or '').strip()
            full_name = ' '.join(part for part in (first, last) if part).strip()
        email = str(item.get('email') or '').strip().lower()
        employee_id = str(item.get('id') or item.get('employee_id') or '').strip()
        if _is_ignored_person(full_name, email):
            continue
        hire_raw = item.get('hired_on') or item.get('hire_date')
        if hire_raw:
            try:
                hire_date = datetime.strptime(str(hire_raw)[:10], '%Y-%m-%d').date()
            except (TypeError, ValueError):
                hire_date = None
            if hire_date and hire_date > today:
                continue
        else:
            hire_date = None
        location_obj = item.get('location') or {}
        location_name = ''
        if isinstance(location_obj, dict):
            location_name = (location_obj.get('name') or '').strip()
        elif isinstance(location_obj, str):
            location_name = location_obj.strip()
        # Don't normalize yet - keep original value for diff modal
        # Normalize only if there's a replacement, otherwise keep original
        normalized = _normalize_location_label(location_name)
        location_name = normalized if normalized is not None else location_name
        department_obj = item.get('department') or {}
        department_name = ''
        if isinstance(department_obj, dict):
            department_name = (department_obj.get('name') or '').strip()
        division_obj = item.get('division') or {}
        division_name = ''
        if isinstance(division_obj, dict):
            division_name = (division_obj.get('name') or '').strip()
        
        # Get position, telegram, team_lead, yaware_id, unit, control_manager from schedule data (cached from sync)
        position_name = ''
        telegram_handle = ''
        team_lead_name = ''
        yaware_user_id = ''
        unit_name = ''
        control_manager_id = None
        schedule_info = schedule_by_email.get(email)
        if schedule_info:
            position_name = (schedule_info.get('position') or '').strip()
            telegram_handle = (schedule_info.get('telegram_username') or '').strip()
            team_lead_name = (schedule_info.get('team_lead') or '').strip()
            yaware_user_id = str(schedule_info.get('user_id') or '').strip()
            unit_name = (schedule_info.get('unit') or schedule_info.get('unit_name') or '').strip()
            control_manager_id = schedule_info.get('control_manager')
        
        # If not in schedule, try to match with YaWare by email first, then by normalized name
        if not yaware_user_id:
            yaware_match = yaware_by_email.get(email)
            if not yaware_match:
                normalized_name = _normalize_name(full_name)
                yaware_match = yaware_by_name.get(normalized_name)
            if yaware_match:
                yaware_user_id = str(yaware_match.get('user_id') or '').strip()
        
        keys = _diff_key_candidates(full_name, email, employee_id)
        entries.append({
            'name': full_name,
            'email': email,
            'user_id': employee_id,
             'peopleforce_id': employee_id,
             'yaware_user_id': yaware_user_id,
             'department': department_name,
             'unit': unit_name,
             'project': division_name,
             'location': location_name,
             'position': position_name,
             'telegram': telegram_handle,
             'team_lead': team_lead_name,
             'control_manager': control_manager_id,
             'hire_date': hire_date.isoformat() if hire_date else None,
            'keys': keys,
        })
    return entries, None


def _generate_user_diff(force_refresh: bool = False) -> dict:
    schedule_entries = _load_schedule_entries()
    schedule_by_key: dict[str, dict] = {}
    for entry in schedule_entries:
        for key in entry['keys']:
            schedule_by_key[key] = entry

    yaware_entries, yaware_error = _extract_yaware_entries()
    peopleforce_entries, peopleforce_error = _extract_peopleforce_entries(force_refresh=force_refresh)

    yaware_only: list[dict] = []
    for entry in yaware_entries:
        matched = False
        for key in entry['keys']:
            schedule_entry = schedule_by_key.get(key)
            if schedule_entry:
                schedule_entry['in_yaware'] = True
                matched = True
        if not matched:
            yaware_only.append(entry)

    peopleforce_only: list[dict] = []
    for entry in peopleforce_entries:
        matched = False
        for key in entry['keys']:
            schedule_entry = schedule_by_key.get(key)
            if schedule_entry:
                schedule_entry['in_peopleforce'] = True
                matched = True
        if not matched:
            peopleforce_only.append(entry)

    local_presence: dict[str, dict] = {}
    missing_yaware: list[str] = []
    missing_peopleforce: list[str] = []
    for entry in schedule_entries:
        payload = {
            'name': entry['name'],
            'email': entry['email'],
            'user_id': entry['user_id'],
            'peopleforce_id': entry.get('peopleforce_id'),
            'in_yaware': entry['in_yaware'],
            'in_peopleforce': entry['in_peopleforce'],
        }
        if yaware_error is None and not entry['in_yaware'] and not _is_ignored_person(entry['name'], entry['email']):
            missing_yaware.append(_humanize_entry(entry['name'], entry['email'], entry['user_id']))
        if peopleforce_error is None and not entry['in_peopleforce'] and not _is_ignored_person(entry['name'], entry['email']):
            missing_peopleforce.append(_humanize_entry(entry['name'], entry['email'], entry['user_id']))
        for key in entry['keys']:
            local_presence[key] = payload

    result = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'local_presence': local_presence,
        'missing_yaware': sorted(set(missing_yaware)),
        'missing_peopleforce': sorted(set(missing_peopleforce)),
        'yaware_only': [] if yaware_error is not None else [
            {
                'display': _humanize_entry(item['name'], item['email'], item['user_id']),
                'email': item['email'],
                'user_id': item['user_id'],
                'name': item['name'],
            }
            for item in yaware_only
        ],
        'peopleforce_only': [] if peopleforce_error is not None else [
            {
                'display': _humanize_entry(item['name'], item['email'], item['user_id']),
                'email': item['email'],
                'user_id': item['user_id'],
                'name': item['name'],
                'peopleforce_id': item.get('peopleforce_id'),
                'yaware_user_id': item.get('yaware_user_id'),
                'project': item.get('project'),
                'department': item.get('department'),
                'unit': item.get('unit'),
                'team': item.get('team'),
                'location': _normalize_location_label(item.get('location')) or (item.get('location') or ''),
                'control_manager': item.get('control_manager'),
                'hire_date': item.get('hire_date'),
            }
            for item in peopleforce_only
        ],
        'counts': {
            'local_total': len(schedule_entries),
            'local_missing_yaware': len(missing_yaware),
            'local_missing_peopleforce': len(missing_peopleforce),
            'yaware_only': len(yaware_only) if yaware_error is None else 0,
            'peopleforce_only': len(peopleforce_only) if peopleforce_error is None else 0,
        },
        'errors': {
            'yaware': yaware_error,
            'peopleforce': peopleforce_error,
        },
    }
    return result


def _serialize_attendance_record(record: AttendanceRecord) -> dict:
    user_schedule = get_user_schedule(record.user_name) or get_user_schedule(record.user_id) or {}

    scheduled_start = record.scheduled_start or ''
    actual_start = record.actual_start or ''
    corrected_minutes = record.corrected_total_minutes
    corrected_display = _minutes_to_str(corrected_minutes) if corrected_minutes is not None else ''
    corrected_hm = _minutes_to_hm(corrected_minutes) if corrected_minutes is not None else ''
    
    return {
        'id': record.id,
        'date': record.record_date.isoformat(),
        'date_display': record.record_date.strftime('%d.%m.%y'),
        'date_iso': record.record_date.strftime('%Y-%m-%d'),
        'user_id': record.user_id,
        'user_name': record.user_name,
        'user_email': record.user_email,
        
        # Нові поля ієрархії
        'division_name': user_schedule.get('division_name'),
        'direction_name': user_schedule.get('direction_name'),
        'unit_name': user_schedule.get('unit_name'),
        'team_name': user_schedule.get('team_name'),

        # Старі поля, залишені для сумісності (можна буде видалити)
        'project': user_schedule.get('division_name'),
        'department': user_schedule.get('direction_name'),
        'team': user_schedule.get('team_name'),

        'location': _normalize_location_label(record.location),
        'scheduled_start': scheduled_start,
        'scheduled_start_hm': _format_time_hm(scheduled_start),
        'actual_start': actual_start,
        'actual_start_hm': _format_time_hm(actual_start),
        'minutes_late': record.minutes_late,
        'minutes_late_display': _minutes_to_str(record.minutes_late),
        'non_productive_minutes': record.non_productive_minutes,
        'non_productive_display': _minutes_to_str(record.non_productive_minutes),
        'non_productive_hm': _minutes_to_hm(record.non_productive_minutes),
        'not_categorized_minutes': record.not_categorized_minutes,
        'not_categorized_display': _minutes_to_str(record.not_categorized_minutes),
        'not_categorized_hm': _minutes_to_hm(record.not_categorized_minutes),
        'productive_minutes': record.productive_minutes,
        'productive_display': _minutes_to_str(record.productive_minutes),
        'productive_hm': _minutes_to_hm(record.productive_minutes),
        'total_minutes': (record.not_categorized_minutes or 0) + (record.productive_minutes or 0),
        'total_display': _minutes_to_str((record.not_categorized_minutes or 0) + (record.productive_minutes or 0)),
        'total_hm': _minutes_to_hm((record.not_categorized_minutes or 0) + (record.productive_minutes or 0)),
        'corrected_total_minutes': corrected_minutes,
        'corrected_total_display': corrected_display,
        'corrected_total_hm': corrected_hm,
        'status': record.status,
        'control_manager': record.control_manager,
        'leave_reason': record.leave_reason,
        'half_day_amount': record.half_day_amount,
        'notes': record.notes,
        'manual_flags': {
            flag_key: getattr(record, flag_name, False)
            for flag_key, flag_name in MANUAL_FLAG_MAP.items()
        }
    }


def _apply_user_key_filter(query, user_key: str):
    normalized = _normalize_user_key(user_key)
    lowered = normalized.lower()
    conditions = []
    if '@' in lowered:
        conditions.append(db.func.lower(AttendanceRecord.user_email) == lowered)
    conditions.append(db.func.lower(AttendanceRecord.user_id) == lowered)
    conditions.append(db.func.lower(AttendanceRecord.user_name) == lowered)
    return query.filter(or_(*conditions)), normalized


def _ensure_admin() -> None:
    if not getattr(current_user, 'is_admin', False):
        abort(403)


@api_bp.get('/admin/scheduler/jobs')
@login_required
def api_scheduler_list_jobs():
    _ensure_admin()
    sched = _get_scheduler()
    if not sched:
        return jsonify({'error': 'scheduler not started'}), 503
    jobs = [_job_to_dict(job) for job in sched.get_jobs()]
    return jsonify({'jobs': jobs})


@api_bp.get('/admin/scheduler/logs')
@login_required
def api_scheduler_logs():
    _ensure_admin()
    logs = list(_get_scheduler_logs())
    return jsonify({'logs': logs})


@api_bp.post('/admin/scheduler/jobs/<job_id>/run')
@login_required
def api_scheduler_run_job(job_id: str):
    _ensure_admin()
    sched = _get_scheduler()
    if not sched:
        return jsonify({'error': 'scheduler not started'}), 503
    job = sched.get_job(job_id)
    if not job:
        return jsonify({'error': f'job {job_id} not found'}), 404

    def _call():
        try:
            job.func(*job.args, **job.kwargs)
            _append_scheduler_log(job_id, "success", "Manual run")
        except Exception as exc:
            _append_scheduler_log(job_id, "error", f"Manual run failed: {exc}")

    threading.Thread(target=_call, daemon=True).start()
    return jsonify({'status': 'triggered'})


@api_bp.post('/admin/scheduler/jobs/<job_id>/pause')
@login_required
def api_scheduler_pause_job(job_id: str):
    _ensure_admin()
    sched = _get_scheduler()
    if not sched:
        return jsonify({'error': 'scheduler not started'}), 503
    if not sched.get_job(job_id):
        return jsonify({'error': f'job {job_id} not found'}), 404
    sched.pause_job(job_id)
    return jsonify({'status': 'paused'})


@api_bp.post('/admin/scheduler/jobs/<job_id>/resume')
@login_required
def api_scheduler_resume_job(job_id: str):
    _ensure_admin()
    sched = _get_scheduler()
    if not sched:
        return jsonify({'error': 'scheduler not started'}), 503
    if not sched.get_job(job_id):
        return jsonify({'error': f'job {job_id} not found'}), 404
    sched.resume_job(job_id)
    return jsonify({'status': 'resumed'})


@api_bp.post('/admin/scheduler/jobs/<job_id>/remove')
@login_required
def api_scheduler_remove_job(job_id: str):
    _ensure_admin()
    sched = _get_scheduler()
    if not sched:
        return jsonify({'error': 'scheduler not started'}), 503
    if not sched.get_job(job_id):
        return jsonify({'error': f'job {job_id} not found'}), 404
    sched.remove_job(job_id)
    return jsonify({'status': 'removed'})


@api_bp.post('/admin/scheduler/jobs/<job_id>/reschedule')
@login_required
def api_scheduler_reschedule_job(job_id: str):
    _ensure_admin()
    sched = _get_scheduler()
    if not sched:
        return jsonify({'error': 'scheduler not started'}), 503
    job = sched.get_job(job_id)
    if not job:
        return jsonify({'error': f'job {job_id} not found'}), 404

    payload = request.get_json(silent=True) or {}
    from apscheduler.triggers.cron import CronTrigger

    trigger = job.trigger
    defaults = {
        'minute': '*',
        'hour': '*',
        'day': '*',
        'month': '*',
        'day_of_week': '*',
    }
    if hasattr(trigger, 'fields'):
        field_names = ['year', 'month', 'day', 'week', 'day_of_week', 'hour', 'minute', 'second']
        for field, name in zip(trigger.fields, field_names):
            if name in defaults and str(field) != '*':
                defaults[name] = str(field)

    data = {k: str(v).strip() for k, v in payload.items() if v not in (None, '')}
    defaults.update({k: v for k, v in data.items() if k in defaults})

    new_trigger = CronTrigger(**defaults)
    job.modify(trigger=new_trigger)
    return jsonify({'status': 'rescheduled', 'trigger': str(new_trigger)})


@api_bp.get('/health')
def health_check():
    """Health check endpoint for monitoring and load balancers."""
    health_status = {
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'version': '1.0.0',
    }
    
    # Check database connection
    try:
        db.session.execute(db.text('SELECT 1'))
        health_status['database'] = 'connected'
    except Exception as exc:
        health_status['database'] = 'error'
        health_status['database_error'] = str(exc)
        health_status['status'] = 'degraded'
    
    # Check scheduler
    sched = _get_scheduler()
    if sched:
        health_status['scheduler'] = 'running'
        health_status['scheduler_jobs'] = len(sched.get_jobs())
    else:
        health_status['scheduler'] = 'stopped'
    
    # Check schedule file
    try:
        schedules = load_user_schedules()
        health_status['user_schedules'] = {
            'loaded': True,
            'count': len(schedules)
        }
    except Exception as exc:
        health_status['user_schedules'] = {
            'loaded': False,
            'error': str(exc)
        }
        health_status['status'] = 'degraded'
    
    status_code = 200 if health_status['status'] == 'ok' else 503
    return jsonify(health_status), status_code


def _log_admin_action(action: str, details: dict) -> None:
    entry = AdminAuditLog(
        user_id=getattr(current_user, 'id', None) if hasattr(current_user, 'id') else None,
        action=action,
        details=details,
    )
    db.session.add(entry)


def _serialize_schedule_user_entry(name: str, info: dict) -> dict:
    email = (info.get('email') or '').strip().lower()
    user_id = str(info.get('user_id') or '').strip()
    peopleforce_id = str(info.get('peopleforce_id') or '').strip()
    division = canonicalize_label(info.get('division_name') or info.get('project'))
    department = canonicalize_label(info.get('direction_name') or info.get('department'))
    unit = canonicalize_label(info.get('unit_name') or info.get('unit'))
    team = canonicalize_label(info.get('team_name') or info.get('team'))
    location_value = canonicalize_label(info.get('location'))
    normalized_location = _normalize_location_label(location_value)
    plan_start = (info.get('start_time') or info.get('plan_start') or '').strip()

    return {
        'user_key': user_id or email or name,
        'user_id': user_id,
        'name': name,
        'email': email,
        'project': division,
        'department': department,
        'unit': unit,
        'team': team,
        'location': normalized_location if normalized_location is not None else location_value,
        'plan_start': plan_start,
        'control_manager': info.get('control_manager'),
        'peopleforce_id': peopleforce_id,
        'position': (info.get('position') or '').strip(),
        'telegram': (info.get('telegram_username') or '').strip(),
        'team_lead': (info.get('team_lead') or '').strip(),
        'ignored': bool(info.get('ignored')),
        'last_date': '',
    }


def _gather_schedule_users(search: str | None, ignored_only: bool = False) -> list[dict]:
    data = schedule_user_manager.load_users()
    users = data.get('users', {}) if isinstance(data, dict) else {}
    if not isinstance(users, dict):
        return []

    search_lower = (search or '').strip().lower()
    entries: list[dict] = []
    for name, info in users.items():
        if not isinstance(info, dict):
            continue
        ignored = bool(info.get('ignored'))
        if ignored_only and not ignored:
            continue
        if not ignored_only and ignored:
            continue

        entry = _serialize_schedule_user_entry(name, info)
        if search_lower:
            haystack = ' '.join(filter(None, [
                entry['name'],
                entry['email'],
                entry.get('project') or '',
                entry.get('department') or '',
                entry.get('unit') or '',
                entry.get('team') or '',
            ])).lower()
            if search_lower not in haystack:
                continue
        entries.append(entry)

    entries.sort(key=lambda item: (item.get('name') or '').lower())
    return entries


def _collect_schedule_filters(entries: list[dict]) -> dict[str, list[str]]:
    projects: set[str] = set()
    departments: set[str] = set()
    units: set[str] = set()
    teams: set[str] = set()

    for entry in entries:
        if entry.get('project'):
            projects.add(canonicalize_label(entry['project']))
        if entry.get('department'):
            departments.add(canonicalize_label(entry['department']))
        if entry.get('unit'):
            units.add(canonicalize_label(entry['unit']))
        if entry.get('team'):
            teams.add(canonicalize_label(entry['team']))

    return {
        'project': sorted(projects),
        'department': sorted(departments),
        'unit': sorted(units),
        'team': sorted(teams),
    }


def _gather_ignored_users(search: str | None) -> list[dict]:
    """Gather ignored users from user_schedules.json"""
    return _gather_schedule_users(search, ignored_only=True)


def _collect_employee_filters(records: list[AttendanceRecord]) -> dict[str, list[str]]:
    divisions: set[str] = set()
    directions: set[str] = set()
    units: set[str] = set()
    teams: set[str] = set()
    for record in records:
        user_schedule = get_user_schedule(record.user_name) or get_user_schedule(record.user_id) or {}
        division_name = canonicalize_label(user_schedule.get('division_name'))
        direction_name = canonicalize_label(user_schedule.get('direction_name'))
        unit_name = canonicalize_label(user_schedule.get('unit_name'))
        team_name = canonicalize_label(user_schedule.get('team_name'))
        
        if division_name:
            divisions.add(division_name)
        if direction_name:
            directions.add(direction_name)
        if unit_name:
            units.add(unit_name)
        if team_name:
            teams.add(team_name)
    return {
        'project': sorted(divisions),
        'department': sorted(directions),
        'unit': sorted(units),
        'team': sorted(teams),
    }


def _filter_employee_records(records: list[AttendanceRecord], attr: str, value: str | None) -> list[AttendanceRecord]:
    if not value:
        return records
    lowered = value.strip().lower()
    if not lowered:
        return records
    filtered: list[AttendanceRecord] = []
    for record in records:
        user_schedule = get_user_schedule(record.user_name) or get_user_schedule(record.user_id) or {}
        resolved_map = {
            'project': user_schedule.get('division_name'),
            'department': user_schedule.get('direction_name'),
            'unit': user_schedule.get('unit_name'),
            'team': user_schedule.get('team_name'),
        }
        attr_value = resolved_map.get(attr, getattr(record, attr, None))
        if attr_value and str(attr_value).strip().lower() == lowered:
            filtered.append(record)
    return filtered


def _serialize_employee_record(record: AttendanceRecord, schedule: dict | None = None) -> dict:
    user_schedule = get_user_schedule(record.user_name) or get_user_schedule(record.user_id) or {}
    
    division_raw = user_schedule.get('division_name') or record.project or ''
    direction_raw = user_schedule.get('direction_name') or record.department or ''
    unit_raw = user_schedule.get('unit_name') or user_schedule.get('unit') or record.team or ''
    team_raw = user_schedule.get('team_name') or user_schedule.get('team') or record.team or ''
    division_name = canonicalize_label(division_raw)
    direction_name = canonicalize_label(direction_raw)
    unit_name = canonicalize_label(unit_raw)
    team_name = canonicalize_label(team_raw)
    
    peopleforce_id = user_schedule.get('peopleforce_id')
    hierarchy_data = {
        'division_name': division_name,
        'direction_name': direction_name,
        'unit_name': unit_name,
        'team_name': team_name,
        'position': '',
        'telegram': '',
        'team_lead': '',
        'manager_name': '',
        'manager_telegram': '',
    }
    
    if schedule and isinstance(schedule, dict):
        candidate = schedule.get('peopleforce_id')
        if candidate not in (None, ''):
            peopleforce_id = str(candidate).strip()
        # Get all data from schedule (newly synced from PeopleForce)
        hierarchy_data = {
            'division_name': canonicalize_label(schedule.get('division_name') or division_raw),
            'direction_name': canonicalize_label(schedule.get('direction_name') or direction_raw),
            'unit_name': canonicalize_label(schedule.get('unit_name') or unit_raw),
            'team_name': canonicalize_label(schedule.get('team_name') or team_raw),
            'position': (schedule.get('position') or '').strip(),
            'telegram': (schedule.get('telegram_username') or '').strip(),
            'team_lead': (schedule.get('team_lead') or '').strip(),
            'manager_name': (schedule.get('manager_name') or '').strip(),
            'manager_telegram': (schedule.get('manager_telegram') or '').strip(),
        }
    
    location_value = _normalize_location_label(record.location)
    
    # Get ignored status from user_schedule or schedule parameter
    ignored_status = False
    if schedule and isinstance(schedule, dict):
        ignored_status = schedule.get('ignored', False)
    else:
        ignored_status = user_schedule.get('ignored', False)
    
    return {
        'user_key': record.user_id or record.user_email or record.user_name,
        'user_id': record.user_id,
        'name': record.user_name,
        'email': record.user_email,
        'project': division_name,
        'department': direction_name,
        'unit': unit_name,
        'team': team_name,
        'location': location_value if location_value is not None else record.location,
        'position': hierarchy_data.get('position', ''),
        'telegram': hierarchy_data.get('telegram', ''),
        'team_lead': hierarchy_data.get('team_lead', ''),
        'plan_start': record.scheduled_start,
        'control_manager': record.control_manager,
        'peopleforce_id': peopleforce_id,
        'last_date': record.record_date.strftime('%Y-%m-%d'),
        'ignored': ignored_status,
    }


def _update_schedule_manager_assignment(keys: set[str], manager_value: int | None) -> list[str]:
    data = schedule_user_manager.load_users()
    users = data.get('users', {}) if isinstance(data, dict) else {}
    updated_names: list[str] = []
    if not users or not keys:
        return updated_names

    for name, info in users.items():
        if not isinstance(info, dict):
            continue
        variants = {
            name.lower(),
            str(info.get('email', '')).lower(),
            str(info.get('user_id', '')).lower(),
        }
        if variants & keys:
            if manager_value is None:
                info.pop('control_manager', None)
            else:
                info['control_manager'] = manager_value
            updated_names.append(name)

    if updated_names:
        schedule_user_manager.save_users(data)
    return updated_names


def _serialize_app_user(user: User) -> dict:
    return {
        'id': user.id,
        'email': user.email,
        'name': user.name,
        'is_admin': user.is_admin,
        'is_control_manager': user.is_control_manager,
        'manager_filter': user.manager_filter or '',
        'created_at': user.created_at.isoformat() if user.created_at else None,
    }


PDF_FONT_CANDIDATES = [
    ('ArialUnicode', '/System/Library/Fonts/Supplemental/Arial Unicode.ttf', '/System/Library/Fonts/Supplemental/Arial Unicode Bold.ttf'),
    ('Arial', '/System/Library/Fonts/Supplemental/Arial.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
    ('ArialMT', '/Library/Fonts/Arial.ttf', '/Library/Fonts/Arial Bold.ttf'),
    ('DejaVuSans', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('LiberationSans', '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf', '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'),
]

_PDF_FONT_REGISTERED = False
_PDF_FONT_PAIR: tuple[str, str] | None = None


def _ensure_pdf_fonts() -> tuple[str, str]:
    global _PDF_FONT_REGISTERED, _PDF_FONT_PAIR
    if SimpleDocTemplate is None or pdfmetrics is None or TTFont is None:
        return 'Helvetica', 'Helvetica-Bold'

    if _PDF_FONT_REGISTERED and _PDF_FONT_PAIR:
        return _PDF_FONT_PAIR

    for base_name, regular_path, bold_path in PDF_FONT_CANDIDATES:
        if not (regular_path and bold_path):
            continue
        if not (os.path.exists(regular_path) and os.path.exists(bold_path)):
            continue
        try:
            regular_name = base_name
            bold_name = f'{base_name}-Bold'
            pdfmetrics.registerFont(TTFont(regular_name, regular_path))
            pdfmetrics.registerFont(TTFont(bold_name, bold_path))
            pdfmetrics.registerFontFamily(
                base_name,
                normal=regular_name,
                bold=bold_name,
                italic=regular_name,
                boldItalic=bold_name,
            )
            _PDF_FONT_REGISTERED = True
            _PDF_FONT_PAIR = (regular_name, bold_name)
            return _PDF_FONT_PAIR
        except Exception:
            continue

    _PDF_FONT_REGISTERED = False
    _PDF_FONT_PAIR = ('Helvetica', 'Helvetica-Bold')
    return _PDF_FONT_PAIR


def _apply_filters(query):
    date_from = _parse_date(request.args.get('date_from'))
    date_to = _parse_date(request.args.get('date_to'))
    single_date = _parse_date(request.args.get('date'))

    if single_date:
        query = query.filter(AttendanceRecord.record_date == single_date)
    else:
        # Якщо дати не задані - показуємо останні 5 робочих днів
        if not date_from and not date_to:
            today = date.today()
            # Шукаємо останні 5 робочих днів (пн-пт)
            workdays = []
            current_day = today
            while len(workdays) < 5:
                if current_day.weekday() < 5:  # 0-4 = пн-пт
                    workdays.append(current_day)
                current_day -= timedelta(days=1)
            if workdays:
                date_from = min(workdays)
                date_to = max(workdays)
        
        if date_from:
            query = query.filter(AttendanceRecord.record_date >= date_from)
        if date_to:
            query = query.filter(AttendanceRecord.record_date <= date_to)

    user_filter = request.args.get('user')
    if user_filter:
        like_pattern = f"%{user_filter.lower()}%"
        query = query.filter(or_(
            db.func.lower(AttendanceRecord.user_name).like(like_pattern),
            db.func.lower(AttendanceRecord.user_email).like(like_pattern)
        ))

    # Фільтрація по project, department, unit, team тепер відбувається 
    # на рівні _filter_employee_records, бо дані зберігаються в user_schedules.json
    # а не в БД. Цей код залишаємо для зворотної сумісності, але він не спрацює
    # для нових даних.
    
    # Support multiple project filters: ?project=A&project=B
    projects = request.args.getlist('project')
    # Support multiple department filters: ?department=A&department=B
    departments = request.args.getlist('department')
    # Support multiple unit filters: ?unit=A&unit=B
    units = request.args.getlist('unit')
    # Support multiple team filters: ?team=A&team=B
    teams = request.args.getlist('team')

    status = request.args.get('status')
    if status:
        query = query.filter(AttendanceRecord.status == status)

    allowed_managers = current_user.allowed_managers
    if allowed_managers:
        query = query.filter(AttendanceRecord.control_manager.in_(allowed_managers))

    return query


def _build_items(records):
    grouped = defaultdict(list)
    for record in records:
        key = record.user_id or record.user_email or record.user_name
        grouped[key].append(record)

    # Load week notes
    week_notes_file = os.path.join(current_app.instance_path, 'week_notes.json')
    week_notes = {}
    if os.path.exists(week_notes_file):
        try:
            with open(week_notes_file, 'r', encoding='utf-8') as f:
                week_notes = json.load(f)
        except Exception as e:
            logger.warning(f'Failed to load week notes: {e}')

    # Load schedule data to get position, telegram, team_lead
    schedule_data = schedule_user_manager.load_users() if schedule_user_manager else {}
    schedule_by_email = {}
    if isinstance(schedule_data, dict):
        for name, info in schedule_data.get('users', {}).items():
            if isinstance(info, dict):
                email = (info.get('email') or '').strip().lower()
                if email:
                    schedule_by_email[email] = info

    items = []
    for key, recs in grouped.items():
        recs.sort(key=lambda r: r.record_date)
        first = recs[0]
        user_schedule_first = get_user_schedule(first.user_name) or get_user_schedule(first.user_id) or {}
        first_division = canonicalize_label(user_schedule_first.get('division_name') or first.project)
        first_direction = canonicalize_label(user_schedule_first.get('direction_name') or first.department)
        first_team = canonicalize_label(user_schedule_first.get('team_name') or first.team)
        
        # Get hierarchy data from schedule (cached from PeopleForce sync)
        hierarchy_data = {
            'division_name': '',
            'direction_name': '',
            'unit_name': '',
            'team_name': '',
            'position': '',
            'telegram': '',
            'team_lead': '',
            'manager_name': '',
            'manager_telegram': '',
        }
        email = (first.user_email or '').strip().lower()
        schedule_info = schedule_by_email.get(email)
        if schedule_info:
            hierarchy_data = {
                'division_name': canonicalize_label(schedule_info.get('division_name')),
                'direction_name': canonicalize_label(schedule_info.get('direction_name')),
                'unit_name': canonicalize_label(schedule_info.get('unit_name')),
                'team_name': canonicalize_label(schedule_info.get('team_name')),
                'position': (schedule_info.get('position') or '').strip(),
                'telegram': (schedule_info.get('telegram_username') or '').strip(),
                'team_lead': (schedule_info.get('team_lead') or '').strip(),
                'manager_name': (schedule_info.get('manager_name') or '').strip(),
                'manager_telegram': (schedule_info.get('manager_telegram') or '').strip(),
            }
        include_weekends = False
        peopleforce_id = None
        if schedule_info and schedule_info.get('peopleforce_id'):
            peopleforce_id = schedule_info.get('peopleforce_id')
        if not peopleforce_id:
            peopleforce_id = user_schedule_first.get('peopleforce_id') or _get_peopleforce_id_for_user(first.user_email or first.user_id or first.user_name)
        try:
            include_weekends = int(peopleforce_id) in SEVEN_DAY_WORK_WEEK_IDS if peopleforce_id else False
        except (TypeError, ValueError):
            include_weekends = False
        
        rows = []
        total_non = 0
        total_not = 0
        total_prod = 0
        total_total = 0
        total_corrected = 0
        has_corrected = False
        notes_aggregated = []

        for rec in recs:
            if rec.record_date.weekday() >= 5 and not include_weekends:
                continue
            rec_schedule = get_user_schedule(rec.user_name) or get_user_schedule(rec.user_id) or {}
            division_name = canonicalize_label(rec_schedule.get('division_name') or rec.project)
            direction_name = canonicalize_label(rec_schedule.get('direction_name') or rec.department)
            team_name = canonicalize_label(rec_schedule.get('team_name') or rec.team)
            
            scheduled_start = rec.scheduled_start or ''
            actual_start = rec.actual_start or ''
            corrected_minutes = rec.corrected_total_minutes
            corrected_display = _minutes_to_str(corrected_minutes) if corrected_minutes is not None else ''
            corrected_hm = _minutes_to_hm(corrected_minutes) if corrected_minutes is not None else ''
            manual_flags = {field: bool(getattr(rec, attr)) for field, attr in MANUAL_FLAG_MAP.items()}
            rows.append({
                'record_id': rec.id,
                'user_name': (rec.user_name or '').strip(),
                'division_name': division_name,  # Додаємо для підсвічування в Total
                'project': division_name,
                'department': direction_name,
                'team': team_name,
                'date': rec.record_date.isoformat(),
                'date_display': rec.record_date.strftime('%d.%m.%y'),
                'date_iso': rec.record_date.strftime('%Y-%m-%d'),
                'scheduled_start': scheduled_start,
                'scheduled_start_hm': _format_time_hm(scheduled_start),
                'actual_start': actual_start,
                'actual_start_hm': _format_time_hm(actual_start),
                'non_productive_minutes': rec.non_productive_minutes,
                'non_productive_display': _minutes_to_str(rec.non_productive_minutes),
                'non_productive_hm': _minutes_to_hm(rec.non_productive_minutes),
                'not_categorized_minutes': rec.not_categorized_minutes,
                'not_categorized_display': _minutes_to_str(rec.not_categorized_minutes),
                'not_categorized_hm': _minutes_to_hm(rec.not_categorized_minutes),
                'productive_minutes': rec.productive_minutes,
                'productive_display': _minutes_to_str(rec.productive_minutes),
                'productive_hm': _minutes_to_hm(rec.productive_minutes),
                'total_minutes': (rec.not_categorized_minutes or 0) + (rec.productive_minutes or 0),
                'total_display': _minutes_to_str((rec.not_categorized_minutes or 0) + (rec.productive_minutes or 0)),
                'total_hm': _minutes_to_hm((rec.not_categorized_minutes or 0) + (rec.productive_minutes or 0)),
                'corrected_total_minutes': corrected_minutes,
                'corrected_total_display': corrected_display,
                'corrected_total_hm': corrected_hm,
                'minutes_late': rec.minutes_late,
                'minutes_late_display': _minutes_to_str(rec.minutes_late),
                'status': rec.status,
                'notes': (rec.notes or '').strip(),
                'notes_display': (rec.notes or rec.leave_reason or '').strip(),
                'leave_reason': (rec.leave_reason or '').strip(),
                'manual_flags': manual_flags,
            })
            total_non += rec.non_productive_minutes or 0
            total_not += rec.not_categorized_minutes or 0
            total_prod += rec.productive_minutes or 0
            # Calculate actual total excluding non_productive
            actual_total = (rec.not_categorized_minutes or 0) + (rec.productive_minutes or 0)
            total_total += actual_total
            if corrected_minutes is not None:
                total_corrected += corrected_minutes
                has_corrected = True
            note_value = (rec.notes or rec.leave_reason or '').strip()
            if note_value:
                notes_aggregated.append(note_value)

        # Get week start date (Monday of the week containing the first record)
        week_start = recs[0].record_date
        days_since_monday = week_start.weekday()  # 0 = Monday, 6 = Sunday
        week_start = week_start - timedelta(days=days_since_monday)
        week_start_str = week_start.isoformat()
        
        # Get week notes for this user and week
        user_key = first.user_email or first.user_id or first.user_name
        note_key = f"{user_key}_{week_start_str}"
        week_note = week_notes.get(note_key, '')
        
        location_display = _normalize_location_label(first.location)
        if not rows:
            continue

        items.append({
            'user_name': first.user_name,
            'user_id': first.user_id,
            'project': first_division,
            'department': first_direction,
            'team': first_team,
            'location': location_display if location_display is not None else first.location,
            'position': hierarchy_data.get('position', ''),
            'telegram': hierarchy_data.get('telegram', ''),
            'team_lead': hierarchy_data.get('team_lead', ''),
            'plan_start': first.scheduled_start,
            'rows': rows,
            'week_total': {
                'non_productive_minutes': total_non,
                'non_productive_display': _minutes_to_str(total_non),
                'non_productive_hm': _minutes_to_hm(total_non),
                'not_categorized_minutes': total_not,
                'not_categorized_display': _minutes_to_str(total_not),
                'not_categorized_hm': _minutes_to_hm(total_not),
                'productive_minutes': total_prod,
                'productive_display': _minutes_to_str(total_prod),
                'productive_hm': _minutes_to_hm(total_prod),
                'total_minutes': total_total,
                'total_display': _minutes_to_str(total_total),
                'total_hm': _minutes_to_hm(total_total),
                'corrected_total_minutes': total_corrected if has_corrected else None,
                'corrected_total_display': _minutes_to_str(total_corrected) if has_corrected else '',
                'corrected_total_hm': _minutes_to_hm(total_corrected) if has_corrected else '',
                'notes': week_note
            }
        })

    items.sort(key=lambda item: item['user_name'])
    return items


def _apply_schedule_overrides(items: list[dict]) -> list[dict]:
    """Update aggregated items with data from user_schedules.json."""
    for item in items:
        schedule = get_user_schedule(item['user_name']) or {}
        if schedule:
            if not item.get('plan_start'):
                plan_start_value = schedule.get('start_time')
                if plan_start_value:
                    item['plan_start'] = plan_start_value
            schedule_location = schedule.get('location')
            normalized_schedule_location = _normalize_location_label(schedule_location)
            if schedule_location not in (None, ''):
                item['location'] = normalized_schedule_location if normalized_schedule_location is not None else schedule_location
            # Додаємо нові поля ієрархії
            if schedule.get('division_name'):
                item['division_name'] = canonicalize_label(schedule['division_name'])
            if schedule.get('direction_name'):
                item['direction_name'] = canonicalize_label(schedule['direction_name'])
            if schedule.get('unit_name'):
                item['unit_name'] = canonicalize_label(schedule['unit_name'])
            if schedule.get('team_name'):
                item['team_name'] = canonicalize_label(schedule['team_name'])
            # Для зворотної сумісності
            item['project'] = item.get('division_name', item.get('project', ''))
            item['department'] = item.get('direction_name', item.get('department', ''))
            item['team'] = item.get('team_name', item.get('team', ''))
        if schedule and schedule.get('location') in (None, ''):
            normalized_item_location = _normalize_location_label(item.get('location'))
            if normalized_item_location is not None:
                item['location'] = normalized_item_location
        item['schedule'] = schedule
    return items


def _get_schedule_filters(selected: dict[str, str] | None = None) -> dict[str, dict[str, list[str]] | dict[str, str]]:
    """Return available filter options and resolved selections based on schedules."""

    schedules = load_user_schedules()
    fields = ('project', 'department', 'unit', 'team')

    def normalize(value: str | None) -> str:
        return (value or '').strip()

    selected = selected or {}
    normalized_selected = {field: normalize(selected.get(field)) for field in fields}
    lower_selected = {field: normalized_selected[field].lower() for field in fields}

    entries: list[dict[str, str]] = []
    for info in schedules.values():
        if not isinstance(info, dict):
            continue
        # Використовуємо нові поля ієрархії
        entry = {
            'project': canonicalize_label(info.get('division_name')),
            'department': canonicalize_label(info.get('direction_name')),
            'unit': canonicalize_label(info.get('unit_name')),
            'team': canonicalize_label(info.get('team_name')),
        }
        if any(entry.values()):
            entries.append(entry)

    def matches(entry: dict[str, str], criteria: dict[str, str]) -> bool:
        for field, value in criteria.items():
            if value and entry[field].lower() != value:
                return False
        return True

    options: dict[str, list[str]] = {}
    for field in fields:
        criteria = {
            other: lower_selected[other]
            for other in fields
            if other != field and lower_selected[other]
        }
        values = sorted({entry[field] for entry in entries if entry[field] and matches(entry, criteria)})
        key = f"{field}s"
        options[key] = values

    selected_entries = [entry for entry in entries if matches(entry, lower_selected)]
    resolved: dict[str, str] = {}
    for field in fields:
        if normalized_selected[field]:
            resolved[field] = normalized_selected[field]
            continue
        values = sorted({entry[field] for entry in selected_entries if entry[field]})
        resolved[field] = values[0] if len(values) == 1 else ''

    return {
        'options': options,
        'selected': resolved
    }


def _get_filtered_items():
    query = _apply_filters(AttendanceRecord.query)
    records = query.order_by(AttendanceRecord.user_name.asc(), AttendanceRecord.record_date.asc()).all()
    
    # Фільтрація по user_key (для множинного вибору співробітників)
    user_keys = request.args.getlist('user_key')
    if user_keys:
        filtered_records = []
        for user_key in user_keys:
            if user_key:
                normalized = _normalize_user_key(user_key).lower()
                for record in records:
                    user_id_match = record.user_id and record.user_id.lower() == normalized
                    email_match = record.user_email and record.user_email.lower() == normalized
                    name_match = record.user_name and record.user_name.lower() == normalized
                    if user_id_match or email_match or name_match:
                        filtered_records.append(record)
        # Видаляємо дублікати
        records = list({record.id: record for record in filtered_records}.values())
    
    # Застосовуємо фільтри по ієрархії (з user_schedules.json)
    # Логіка: OR всередині одного рівня (projects, departments, units, teams)
    #         AND між різними рівнями
    projects = request.args.getlist('project')
    departments = request.args.getlist('department')
    units = request.args.getlist('unit')
    teams = request.args.getlist('team')
    
    # Фільтруємо по проектах (OR)
    if projects:
        projects_filtered = []
        for project in projects:
            if project:
                projects_filtered.extend(_filter_employee_records(records, 'project', project))
        # Видаляємо дублікати
        records = list({record.id: record for record in projects_filtered}.values())
    
    # Фільтруємо по департаментах (OR)
    if departments:
        departments_filtered = []
        for department in departments:
            if department:
                departments_filtered.extend(_filter_employee_records(records, 'department', department))
        records = list({record.id: record for record in departments_filtered}.values())
    
    # Фільтруємо по units (OR)
    if units:
        units_filtered = []
        for unit in units:
            if unit:
                units_filtered.extend(_filter_employee_records(records, 'unit', unit))
        records = list({record.id: record for record in units_filtered}.values())
    
    # Фільтруємо по командах (OR)
    if teams:
        teams_filtered = []
        for team in teams:
            if team:
                teams_filtered.extend(_filter_employee_records(records, 'team', team))
        records = list({record.id: record for record in teams_filtered}.values())
    
    items = _apply_schedule_overrides(_build_items(records))
    return items, len(records)


@api_bp.route('/attendance')
@login_required
def attendance_list():
    items, records = _get_filtered_items()
    selected_filters = {
        'project': request.args.get('project', ''),
        'department': request.args.get('department', ''),
        'unit': request.args.get('unit', ''),
        'team': request.args.get('team', '')
    }
    return jsonify({
        'items': items,
        'count': records,
        'filters': _get_schedule_filters(selected_filters)
    })


@api_bp.route('/admin/users/diff')
@login_required
def admin_users_diff():
    _ensure_admin()
    force = (request.args.get('force') or '').strip().lower() in {'1', 'true', 'yes', 'force'}
    diff_payload = _generate_user_diff(force_refresh=force)
    return jsonify(diff_payload)


@api_bp.route('/admin/sync/users', methods=['POST'])
@login_required
def admin_sync_users():
    _ensure_admin()
    
    try:
        payload = request.get_json(silent=True) or {}
        force_refresh = bool(payload.get('force_refresh'))
        sync_summary: dict[str, object] = {}

        try:
            from dashboard_app.tasks import _sync_peopleforce_metadata  # local import to avoid circular dependency
            _sync_peopleforce_metadata(current_app)
            sync_summary['peopleforce_metadata'] = 'updated'
        except Exception as exc:  # pragma: no cover - filesystem/network failure
            logger.error(f"PeopleForce sync error: {exc}", exc_info=True)
            sync_summary['peopleforce_metadata'] = f'failed: {str(exc)}'

        try:
            from dashboard_app.tasks import _sync_yaware_plan_start  # local import to avoid circular dependency
            updated_count = _sync_yaware_plan_start(current_app)
            sync_summary['yaware_schedule'] = {'updated': updated_count}
        except Exception as exc:  # pragma: no cover - filesystem/network failure
            logger.error(f"YaWare sync error: {exc}", exc_info=True)
            sync_summary['yaware_schedule'] = f'failed: {str(exc)}'

        try:
            diff_payload = _generate_user_diff(force_refresh=force_refresh)
        except Exception as exc:
            logger.error(f"User diff generation error: {exc}", exc_info=True)
            return jsonify({'error': f'Помилка генерації diff: {str(exc)}'}), 500
        
        try:
            _log_admin_action('manual_sync_users', {
                'force_refresh': force_refresh,
                'sync_summary': sync_summary,
                'diff_counts': diff_payload.get('counts'),
            })
            db.session.commit()
        except Exception as exc:
            logger.error(f"Failed to log admin action or commit: {exc}", exc_info=True)
            # Продовжуємо навіть якщо логування не вдалося
        
        return jsonify({'status': 'ok', 'sync': sync_summary, 'diff': diff_payload})
    
    except Exception as exc:
        logger.error(f"Unexpected error in admin_sync_users: {exc}", exc_info=True)
        return jsonify({'error': f'Неочікувана помилка: {str(exc)}'}), 500



@api_bp.route('/admin/sync/attendance', methods=['POST'])
@login_required
def admin_sync_attendance():
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    target_str = (payload.get('date') or '').strip()
    target_date = _parse_date(target_str)
    if not target_date:
        return jsonify({'error': 'Некоректна дата. Використовуйте формат YYYY-MM-DD'}), 400

    skip_weekends = payload.get('skip_weekends', False)
    include_absent = payload.get('include_absent', True)

    if isinstance(skip_weekends, str):
        skip_weekends = skip_weekends.lower() in {'1', 'true', 'yes'}
    skip_weekends = bool(skip_weekends)
    if isinstance(include_absent, str):
        include_absent = include_absent.lower() in {'1', 'true', 'yes'}
    include_absent = bool(include_absent)

    if skip_weekends and target_date.weekday() >= 5:
        return jsonify({
            'skipped': True,
            'reason': 'weekend',
            'date': target_date.isoformat(),
        })

    monitor = AttendanceMonitor()
    update_for_date(monitor, target_date, include_absent=include_absent)

    _log_admin_action('manual_sync_attendance_date', {
        'date': target_date.isoformat(),
        'include_absent': include_absent,
        'skip_weekends': skip_weekends,
    })
    db.session.commit()
    return jsonify({
        'status': 'ok',
        'date': target_date.isoformat(),
        'include_absent': include_absent,
    })


@api_bp.route('/admin/employees', methods=['POST'])
@login_required
def admin_create_employee():
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    email_raw = (payload.get('email') or '').strip()
    email = email_raw.lower()
    
    logger.info(f"Creating employee: name='{name}', email='{email}', ignored={payload.get('ignored')}")
    
    if not name:
        logger.warning(f"Missing name: name='{name}'")
        return jsonify({'error': 'name is required'}), 400

    schedules = schedule_user_manager.load_users()
    users = schedules.get('users')
    if not isinstance(users, dict):
        users = {}
        schedules['users'] = users

    if name in users:
        logger.warning(f"User already exists: name='{name}'")
        # If trying to add as ignored and user already exists, just set ignored flag
        if payload.get('ignored'):
            users[name]['ignored'] = True
            schedule_user_manager.save_users(schedules)
            clear_user_schedule_cache()
            logger.info(f"Updated existing user '{name}' to ignored=True")
            return jsonify({'status': 'ok', 'name': name, 'entry': users[name], 'updated': True})
        return jsonify({'error': 'Користувач з таким ім\'ям вже існує'}), 409

    # Check for email conflicts only if email is provided
    if email:
        normalized_email = email.strip().lower()
        for existing_name, info in users.items():
            existing_email = str(info.get('email') or '').strip().lower()
            if existing_email and existing_email == normalized_email:
                logger.warning(f"Email conflict: '{email}' already used by '{existing_name}'")
                # If trying to add as ignored and email exists, update that user
                if payload.get('ignored'):
                    users[existing_name]['ignored'] = True
                    schedule_user_manager.save_users(schedules)
                    clear_user_schedule_cache()
                    logger.info(f"Updated existing user '{existing_name}' to ignored=True (by email match)")
                    return jsonify({'status': 'ok', 'name': existing_name, 'entry': users[existing_name], 'updated': True})
                return jsonify({'error': f"Email вже використовується користувачем '{existing_name}'"}), 409

    def _clean(value: object) -> str | None:
        if isinstance(value, str):
            value = value.strip()
        return value or None

    start_time = _clean(payload.get('plan_start') or payload.get('start_time'))
    control_manager = payload.get('control_manager')
    if control_manager in (None, '', 'null'):
        control_manager_value = None
    else:
        try:
            control_manager_value = int(control_manager)
        except (TypeError, ValueError):
            return jsonify({'error': 'control_manager must be integer or empty'}), 400

    entry: dict[str, object] = {}
    if email:
        entry['email'] = email.strip().lower()
    yaware_id = _clean(payload.get('user_id'))
    if yaware_id:
        entry['user_id'] = yaware_id
    peopleforce_id = _clean(payload.get('peopleforce_id'))
    if peopleforce_id:
        entry['peopleforce_id'] = peopleforce_id
    location_raw = _clean(payload.get('location'))
    location = _normalize_location_label(location_raw) or location_raw
    if location:
        entry['location'] = location
        set_manual_override(entry, 'location')
    project = _clean(payload.get('project'))
    if project:
        entry['project'] = project
        set_manual_override(entry, 'project')
    department = _clean(payload.get('department'))
    if department:
        entry['department'] = department
        set_manual_override(entry, 'department')
    team = _clean(payload.get('team'))
    if team:
        entry['team'] = team
        set_manual_override(entry, 'team')
    if start_time:
        entry['start_time'] = start_time
        set_manual_override(entry, 'start_time')
    
    # Handle ignored flag
    ignored = payload.get('ignored', False)
    if ignored:
        entry['ignored'] = True
    
    # Автопризначення control_manager якщо не вказано вручну
    if control_manager_value is not None:
        entry['control_manager'] = control_manager_value
        set_manual_override(entry, 'control_manager')
    else:
        # Автоматично визначаємо на основі division_name
        division_name = _clean(payload.get('division_name'))
        if division_name:
            entry['division_name'] = division_name
        auto_manager = auto_assign_control_manager(entry.get('division_name', ''))
        entry['control_manager'] = auto_manager

    users[name] = entry
    if not schedule_user_manager.save_users(schedules):
        return jsonify({'error': 'Не вдалося зберегти користувача'}), 500

    clear_user_schedule_cache()
    _schedule_identity_sets.cache_clear()

    _log_admin_action('create_schedule_user', {
        'name': name,
        'entry': entry,
    })
    return jsonify({'status': 'ok', 'name': name, 'entry': entry})


@api_bp.route('/admin/employees')
@login_required
def admin_employees():
    _ensure_admin()
    search = request.args.get('search', '').strip()
    ignored_only = request.args.get('ignored', '').lower() == 'true'
    project_filters = request.args.getlist('project')
    department_filters = request.args.getlist('department')
    unit_filters = request.args.getlist('unit')
    team_filters = request.args.getlist('team')
    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = max(min(int(request.args.get('per_page', 25) or 25), 100), 1)

    if ignored_only:
        records = _gather_schedule_users(search, ignored_only=True)
        filter_options = {}
    else:
        records = _gather_schedule_users(search, ignored_only=False)
        filter_options = _collect_schedule_filters(records)
    
    # Support multiple filters for each category
    if project_filters:
        project_filters_lower = {p.lower() for p in project_filters if p}
        records = [r for r in records if (r.get('project') or '').lower() in project_filters_lower]
    
    if department_filters:
        department_filters_lower = {d.lower() for d in department_filters if d}
        records = [r for r in records if (r.get('department') or '').lower() in department_filters_lower]
    
    if unit_filters:
        unit_filters_lower = {u.lower() for u in unit_filters if u}
        records = [r for r in records if (r.get('unit') or '').lower() in unit_filters_lower]
    
    if team_filters:
        team_filters_lower = {t.lower() for t in team_filters if t}
        records = [r for r in records if (r.get('team') or '').lower() in team_filters_lower]
    
    total = len(records)
    start = (page - 1) * per_page
    page_records = records[start:start + per_page]

    items: list[dict] = []
    for record in page_records:
        items.append(record)

    return jsonify({
        'items': items,
        'total': total,
        'page': page,
        'per_page': per_page,
        'manager_options': _available_control_managers(),
        'filters': filter_options,
    })


@api_bp.route('/admin/employees/manager', methods=['PATCH'])
@login_required
def admin_update_employee_manager():
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    user_keys = payload.get('user_keys') or []
    if not isinstance(user_keys, list) or not user_keys:
        return jsonify({'error': 'user_keys must be a non-empty list'}), 400

    manager_value = payload.get('control_manager')
    if manager_value in (None, ''):
        manager_value = None
    else:
        try:
            manager_value = int(manager_value)
        except (TypeError, ValueError):
            return jsonify({'error': 'control_manager must be integer or null'}), 400

    normalized_keys = {_normalize_user_key(key).lower() for key in user_keys if key}
    if not normalized_keys:
        return jsonify({'error': 'user_keys must contain valid identifiers'}), 400

    total_updated = 0
    for key in normalized_keys:
        filters = [
            db.func.lower(AttendanceRecord.user_id) == key,
            db.func.lower(AttendanceRecord.user_email) == key,
            db.func.lower(AttendanceRecord.user_name) == key,
        ]
        updated = AttendanceRecord.query.filter(or_(*filters)).update({'control_manager': manager_value}, synchronize_session=False)
        total_updated += updated or 0

    schedule_updated = _update_schedule_manager_assignment(normalized_keys, manager_value)

    _log_admin_action('bulk_update_control_manager', {
        'user_keys': list(normalized_keys),
        'control_manager': manager_value,
        'records_updated': total_updated,
        'schedules_updated': schedule_updated,
    })

    db.session.commit()

    return jsonify({
        'updated_records': total_updated,
        'updated_schedules': schedule_updated,
    })


def _update_schedule_entry(keys: set[str], updates: dict[str, object]) -> dict[str, object]:
    if not keys or not updates:
        return {}
    data = schedule_user_manager.load_users()
    users = data.get('users', {}) if isinstance(data, dict) else {}
    if not users:
        return {}

    target_name = None
    target_info = None
    for name, info in users.items():
        if not isinstance(info, dict):
            continue
        variants = {
            name.strip().lower(),
            str(info.get('email', '')).strip().lower(),
            str(info.get('user_id', '')).strip().lower(),
        }
        if variants & keys:
            target_name = name
            target_info = info
            break

    mapping = {
        'email': 'email',
        'user_id': 'user_id',
        'project': 'project',
        'department': 'department',
        'unit': 'unit',
        'team': 'team',
        'location': 'location',
        'plan_start': 'start_time',
        'peopleforce_id': 'peopleforce_id',
        'control_manager': 'control_manager',
    }

    if not target_name or target_info is None:
        desired_name = (updates.get('name') or '').strip()
        if not desired_name:
            return {}
        info_payload: dict[str, object] = {}
        for source, dest in mapping.items():
            value = updates.get(source)
            if source == 'name':
                continue
            if source == 'location' and value not in (None, ''):
                normalized_location = _normalize_location_label(value)
                value = normalized_location if normalized_location is not None else value
            if value in (None, ''):
                continue
            info_payload[dest] = value
            if dest in _MANUAL_PROTECTED_FIELDS:
                set_manual_override(info_payload, dest)
        if 'email' not in info_payload and updates.get('email') is not None:
            info_payload['email'] = updates.get('email')
        if desired_name not in users:
            users[desired_name] = info_payload
            schedule_user_manager.save_users(data)
            clear_user_schedule_cache()
            _schedule_identity_sets.cache_clear()
            return {
                'matched_entry': None,
                'renamed_to': desired_name,
                'changed': True,
                'created': True,
            }
        target_name = desired_name
        target_info = users[target_name]

    changed = False
    
    # Перевіряємо чи змінилася division_name для автопризначення control_manager
    division_changed = False
    new_division = None
    if 'division_name' in updates or 'project' in updates:
        new_division = updates.get('division_name') or updates.get('project')
        if new_division and target_info.get('division_name') != new_division:
            division_changed = True

    for source, dest in mapping.items():
        if source not in updates:
            continue
        value = updates[source]
        if dest == 'control_manager':
            if value in (None, '', 'null'):
                if target_info.pop(dest, None) is not None:
                    changed = True
                continue
            if target_info.get(dest) != value:
                target_info[dest] = value
                changed = True
                continue

        if dest == 'location' and value not in (None, ''):
            normalized_location = _normalize_location_label(value)
            value = normalized_location if normalized_location is not None else value

        if value in (None, ''):
            if dest in target_info:
                previous = target_info.pop(dest, None)
                if previous is not None:
                    changed = True
            if dest in _MANUAL_PROTECTED_FIELDS:
                clear_manual_override(target_info, dest)
            continue

        if target_info.get(dest) != value:
            target_info[dest] = value
            changed = True
            if dest in _MANUAL_PROTECTED_FIELDS:
                set_manual_override(target_info, dest)

    # Also update canonical hierarchy fields
    hierarchy_mapping = {
        'project': 'division_name',
        'department': 'direction_name',
        'unit': 'unit_name',
        'team': 'team_name',
    }
    for source_field, canonical_field in hierarchy_mapping.items():
        if source_field in updates:
            value = updates[source_field]
            if value in (None, ''):
                if canonical_field in target_info:
                    previous = target_info.pop(canonical_field, None)
                    if previous is not None:
                        changed = True
            elif target_info.get(canonical_field) != value:
                target_info[canonical_field] = value
                changed = True

    new_name = target_name
    if 'name' in updates:
        desired = (updates['name'] or '').strip()
        if desired and desired != target_name:
            users[desired] = target_info
            users.pop(target_name, None)
            new_name = desired
            changed = True
    
    # Автопризначення control_manager якщо змінилася division і немає явного override
    set_override = updates.get('_set_control_manager_override', False)
    
    if division_changed and not set_override and not has_manual_override(target_info, 'control_manager'):
        auto_manager = auto_assign_control_manager(new_division or '')
        if target_info.get('control_manager') != auto_manager:
            target_info['control_manager'] = auto_manager
            changed = True
            logger.debug(f"Автопризначено control_manager={auto_manager} при оновленні division для {new_name}")

    if changed:
        schedule_user_manager.save_users(data)
        clear_user_schedule_cache()
        _schedule_identity_sets.cache_clear()

    return {
        'matched_entry': target_name,
        'renamed_to': new_name if new_name != target_name else None,
        'changed': changed,
    }


@api_bp.route('/admin/employees/<path:user_key>', methods=['PATCH'])
@login_required
def admin_update_employee(user_key: str):
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    normalized_key = _normalize_user_key(user_key).strip()
    if not normalized_key:
        return jsonify({'error': 'Invalid user identifier'}), 400

    filters = [
        db.func.lower(AttendanceRecord.user_id) == normalized_key.lower(),
        db.func.lower(AttendanceRecord.user_email) == normalized_key.lower(),
        db.func.lower(AttendanceRecord.user_name) == normalized_key.lower(),
    ]
    records = AttendanceRecord.query.filter(or_(*filters)).all()
    if not records:
        return jsonify({'error': 'User not found'}), 404

    updates: dict[str, object] = {}
    schedule_updates: dict[str, object] = {}

    if 'name' in payload:
        name = (payload.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'Name cannot be empty'}), 400
        updates['user_name'] = name
        schedule_updates['name'] = name

    if 'email' in payload:
        email_raw = (payload.get('email') or '').strip()
        email = email_raw.lower() if email_raw else None
        updates['user_email'] = email
        schedule_updates['email'] = email

    if 'user_id' in payload:
        user_id = (payload.get('user_id') or '').strip() or None
        updates['user_id'] = user_id
        schedule_updates['user_id'] = user_id

    if 'peopleforce_id' in payload:
        pf_raw = (payload.get('peopleforce_id') or '').strip()
        schedule_updates['peopleforce_id'] = pf_raw or None

    for field in ('project', 'department', 'unit', 'team', 'location', 'plan_start'):
        if field in payload:
            value = (payload.get(field) or '').strip() or None
            if field == 'location' and value is not None:
                normalized_location = _normalize_location_label(value)
                value = normalized_location if normalized_location is not None else value
            target_field = 'scheduled_start' if field == 'plan_start' else field
            updates[target_field] = value
            schedule_updates[field] = value

    if 'control_manager' in payload:
        manager_value = payload.get('control_manager')
        if manager_value in (None, '', 'null'):
            control_manager = None
        else:
            try:
                control_manager = int(manager_value)
            except (TypeError, ValueError):
                return jsonify({'error': 'control_manager must be integer or empty'}), 400
        updates['control_manager'] = control_manager
        schedule_updates['control_manager'] = control_manager
        # Встановлюємо manual override, бо це явне призначення адміном
        schedule_updates['_set_control_manager_override'] = True

    if not updates:
        return jsonify({'error': 'No valid fields to update'}), 400

    key_variants = {normalized_key.lower()}
    for record in records:
        if record.user_id:
            key_variants.add(record.user_id.lower())
        if record.user_email:
            key_variants.add(record.user_email.lower())
        if record.user_name:
            key_variants.add(record.user_name.lower())

    for record in records:
        for attr, value in updates.items():
            setattr(record, attr, value)

    # Отримуємо canonical hierarchy з user_schedules
    sample_record = records[0]
    sample_schedule = get_user_schedule(sample_record.user_name) or get_user_schedule(sample_record.user_id) or {}
    canonical_division = sample_schedule.get('division_name')
    canonical_direction = sample_schedule.get('direction_name')
    canonical_team = sample_schedule.get('team_name')
    
    # Оновлюємо старі поля для зворотної сумісності (можна видалити пізніше)
    for record in records:
        if canonical_division:
            record.project = canonical_division
        if canonical_direction:
            record.department = canonical_direction
        if canonical_team:
            record.team = canonical_team

    # Ensure updates and schedule payload include resolved hierarchy.
    if canonical_division and not updates.get('project'):
        updates['project'] = canonical_division
    if canonical_direction and not updates.get('department'):
        updates['department'] = canonical_direction
    if canonical_team and not updates.get('team'):
        updates['team'] = canonical_team
    for field, value in (('project', canonical_division), ('department', canonical_direction), ('team', canonical_team)):
        if value and field not in schedule_updates:
            schedule_updates[field] = value

    primary_record = records[0]
    if primary_record:
        if 'name' not in schedule_updates and primary_record.user_name:
            schedule_updates['name'] = primary_record.user_name
        if 'email' not in schedule_updates and primary_record.user_email:
            schedule_updates['email'] = primary_record.user_email
        if 'user_id' not in schedule_updates and primary_record.user_id:
            schedule_updates['user_id'] = primary_record.user_id

    schedule_info = _update_schedule_entry(key_variants, schedule_updates)

    _log_admin_action('update_employee', {
        'user_key': normalized_key,
        'updates': updates,
        'schedule_updates': schedule_info,
    })

    db.session.commit()

    primary = records[0]
    refreshed_schedule = _load_user_schedule_variants(normalized_key, records)
    return jsonify({'item': _serialize_employee_record(primary, refreshed_schedule), 'schedule_updates': schedule_info})


@api_bp.route('/admin/employees/<path:user_key>', methods=['DELETE'])
@login_required
def admin_delete_employee(user_key: str):
    _ensure_admin()
    normalized = _normalize_user_key(user_key).strip()
    if not normalized:
        return jsonify({'error': 'Некоректний ідентифікатор користувача'}), 400
    lowered = normalized.lower()

    filters = [
        db.func.lower(AttendanceRecord.user_id) == lowered,
        db.func.lower(AttendanceRecord.user_email) == lowered,
        db.func.lower(AttendanceRecord.user_name) == lowered,
    ]
    deleted_records = AttendanceRecord.query.filter(or_(*filters)).delete(synchronize_session=False)

    schedule_removed = False
    schedule_name = None
    schedule_message = None

    data = schedule_user_manager.load_users()
    users = data.get('users', {}) if isinstance(data, dict) else {}
    for name, info in users.items():
        if not isinstance(info, dict):
            continue
        variants = {
            name.strip().lower(),
            str(info.get('email', '')).strip().lower(),
            str(info.get('user_id', '')).strip().lower(),
        }
        if lowered in variants:
            schedule_name = name
            success, message = schedule_user_manager.delete_user(name)
            schedule_removed = success
            schedule_message = message
            break

    _log_admin_action('delete_employee', {
        'user_key': normalized,
        'deleted_records': deleted_records,
        'schedule_removed': schedule_removed,
        'schedule_name': schedule_name,
    })
    db.session.commit()

    return jsonify({
        'status': 'ok',
        'deleted_records': deleted_records,
        'removed_schedule': schedule_removed,
        'schedule_name': schedule_name,
        'message': schedule_message,
    })


def _get_hierarchy_from_level_grade(user_name: str) -> dict | None:
    """Отримати ієрархію з Level_Grade.json по імені менеджера.
    
    Args:
        user_name: Ім'я користувача у форматі "Прізвище Ім'я"
        
    Returns:
        Словник з полями division_name, direction_name, unit_name, team_name або None
    """
    from pathlib import Path
    
    level_grade_path = Path(__file__).parent.parent / 'config' / 'Level_Grade.json'
    
    if not level_grade_path.exists():
        logger.warning(f"Level_Grade.json not found at {level_grade_path}")
        return None
    
    try:
        with open(level_grade_path, 'r', encoding='utf-8') as f:
            level_grade_data = json.load(f)
        
        # Шукаємо по Manager
        for entry in level_grade_data:
            manager = (entry.get('Manager') or '').strip()
            if manager.lower() == user_name.lower():
                return {
                    'division_name': entry.get('Division', '').strip() if entry.get('Division') != '-' else '',
                    'direction_name': entry.get('Direction', '').strip() if entry.get('Direction') != '-' else '',
                    'unit_name': entry.get('Unit', '').strip() if entry.get('Unit') != '-' else '',
                    'team_name': entry.get('Team', '').strip() if entry.get('Team') != '-' else '',
                }
        
        logger.debug(f"No match found in Level_Grade.json for manager: {user_name}")
        return None
        
    except Exception as exc:
        logger.error(f"Error reading Level_Grade.json: {exc}", exc_info=True)
        return None


@api_bp.route('/admin/employees/<path:user_key>/sync', methods=['POST'])
@login_required
def admin_sync_employee(user_key: str):
    """Синхронізація одного користувача з PeopleForce"""
    _ensure_admin()
    normalized = _normalize_user_key(user_key).strip()
    if not normalized:
        return jsonify({'error': 'Некоректний ідентифікатор користувача'}), 400
    
    try:
        # Завантажуємо дані користувача з schedule
        schedules = schedule_user_manager.load_users()
        users = schedules.get('users', {}) if isinstance(schedules, dict) else {}
        
        user_info = None
        user_name = None
        email = None
        
        # Шукаємо користувача в schedule
        normalized_lower = normalized.lower()
        for name, info in users.items():
            if not isinstance(info, dict):
                continue
            variants = {
                name.strip().lower(),
                str(info.get('email', '')).strip().lower(),
                str(info.get('user_id', '')).strip().lower(),
                str(info.get('peopleforce_id', '')).strip().lower(),
            }
            if normalized_lower in variants:
                user_info = info
                user_name = name
                email = (info.get('email') or '').strip().lower()
                break
        
        if not user_info or not email:
            return jsonify({'error': 'Користувача не знайдено в системі'}), 404
        
        # Синхронізуємо з PeopleForce
        client = PeopleForceClient()
        employees = client.get_employees(force_refresh=True)
        
        employee = None
        for emp in employees:
            emp_email = (emp.get('email') or '').strip().lower()
            if emp_email == email:
                employee = emp
                break
        
        if not employee:
            return jsonify({'error': 'Користувача не знайдено в PeopleForce'}), 404
        
        updated_fields = []
        
        # СПОЧАТКУ: Маппінг через Level_Grade.json для коректної 4-рівневої ієрархії
        level_grade_hierarchy = _get_hierarchy_from_level_grade(user_name)
        if level_grade_hierarchy:
            logger.info(f"Found hierarchy in Level_Grade.json for {user_name}: {level_grade_hierarchy}")
            
            # Оновлюємо всі 4 рівні ієрархії з Level_Grade
            for field in ['division_name', 'direction_name', 'unit_name', 'team_name']:
                new_value = level_grade_hierarchy.get(field, '')
                if new_value and user_info.get(field) != new_value:
                    user_info[field] = new_value
                    updated_fields.append(field)
            
            # Також оновлюємо legacy поля для сумісності
            if level_grade_hierarchy.get('division_name'):
                user_info['project'] = level_grade_hierarchy['division_name']
            if level_grade_hierarchy.get('direction_name'):
                user_info['department'] = level_grade_hierarchy['direction_name']
            if level_grade_hierarchy.get('unit_name'):
                user_info['unit'] = level_grade_hierarchy['unit_name']
            if level_grade_hierarchy.get('team_name'):
                user_info['team'] = level_grade_hierarchy['team_name']
        else:
            # Якщо Level_Grade не знайдено - підтягуємо з PeopleForce (але це запасний варіант)
            logger.warning(f"No Level_Grade entry found for {user_name}, using PeopleForce data")
            
            # Оновлюємо project (DIVISION)
            project_obj = employee.get('division') or {}
            project_name = ''
            if isinstance(project_obj, dict):
                project_name = (project_obj.get('name') or '').strip()
            if project_name and user_info.get('project') != project_name:
                user_info['project'] = project_name
                updated_fields.append('project')
            
            # Оновлюємо department (DIRECTION/UNIT)
            department_obj = employee.get('department') or {}
            department_name = ''
            if isinstance(department_obj, dict):
                department_name = (department_obj.get('name') or '').strip()
            if department_name and user_info.get('department') != department_name:
                user_info['department'] = department_name
                updated_fields.append('department')
        
        # Отримуємо детальні дані з PeopleForce
        peopleforce_id = user_info.get('peopleforce_id')
        if peopleforce_id:
            try:
                detailed_data = client.get_employee_detail(peopleforce_id)
                if detailed_data:
                    # Оновлюємо позицію
                    position_obj = detailed_data.get('position') or {}
                    position_name = ''
                    if isinstance(position_obj, dict):
                        position_name = (position_obj.get('name') or '').strip()
                    if position_name and user_info.get('position') != position_name:
                        user_info['position'] = position_name
                        updated_fields.append('position')
                    
                    # Оновлюємо команду
                    team_obj = detailed_data.get('team') or {}
                    team_name = ''
                    if isinstance(team_obj, dict):
                        team_name = (team_obj.get('name') or '').strip()
                    if team_name and user_info.get('team') != team_name:
                        user_info['team'] = team_name
                        updated_fields.append('team')
                    
                    # Оновлюємо локацію
                    location_obj = detailed_data.get('location') or {}
                    location_name = ''
                    if isinstance(location_obj, dict):
                        location_name = (location_obj.get('name') or '').strip()
                    if location_name and user_info.get('location') != location_name:
                        user_info['location'] = location_name
                        updated_fields.append('location')
            except Exception as exc:
                logger.warning(f"Failed to fetch detailed data for {peopleforce_id}: {exc}")
        
        # Маппінг через Level_Grade.json для коректної 4-рівневої ієрархії
        # Ця частина НЕ перезаписує всі поля, а тільки додає канонічні поля якщо їх немає
        level_grade_hierarchy = _get_hierarchy_from_level_grade(user_name)
        if level_grade_hierarchy:
            logger.info(f"Found hierarchy in Level_Grade.json for {user_name}: {level_grade_hierarchy}")
            
            # Оновлюємо всі 4 рівні ієрархії
            for field in ['division_name', 'direction_name', 'unit_name', 'team_name']:
                new_value = level_grade_hierarchy.get(field, '')
                if new_value and user_info.get(field) != new_value:
                    user_info[field] = new_value
                    updated_fields.append(field)
        
        # Автопризначення control_manager - ПЕРЕВІРЯЄМО чи НЕ перезаписаний вручну
        if not has_manual_override(user_info, 'control_manager'):
            division_name = user_info.get('division_name', '')
            auto_manager = auto_assign_control_manager(division_name)
            if user_info.get('control_manager') != auto_manager:
                user_info['control_manager'] = auto_manager
                updated_fields.append('control_manager (auto)')
        else:
            logger.info(f"Control manager for {user_name} has manual override, skipping auto-assignment")
        
        # Зберігаємо зміни
        if updated_fields:
            users[user_name] = user_info
            schedules['users'] = users
            schedule_user_manager.save_users(schedules)
            clear_user_schedule_cache()
        
        _log_admin_action('sync_single_employee', {
            'user_key': normalized,
            'user_name': user_name,
            'email': email,
            'updated_fields': updated_fields,
        })
        
        db.session.commit()
        
        return jsonify({
            'status': 'ok',
            'user_name': user_name,
            'updated_fields': updated_fields,
            'user_info': user_info,
        })
        
    except Exception as exc:
        logger.error(f"Error syncing employee {normalized}: {exc}", exc_info=True)
        return jsonify({'error': f'Помилка синхронізації: {str(exc)}'}), 500


@api_bp.route('/admin/employees/<key>/adapt', methods=['POST'])
@login_required
def admin_adapt_employee(key: str):
    """Адаптує дані користувача відповідно до Level_Grade.json."""
    _ensure_admin()
    
    try:
        normalized = (key or '').strip().lower()
        if not normalized:
            return jsonify({'error': 'Не вказано ключ користувача'}), 400
        
        # Завантажуємо user_schedules
        schedules = schedule_user_manager.load_users()
        users = schedules.get('users', {})
        
        # Знаходимо користувача
        user_info = None
        user_name = None
        email = None
        
        for name, info in users.items():
            name_norm = name.strip().lower()
            email_norm = (info.get('email') or '').strip().lower()
            user_id_norm = str(info.get('user_id') or '').strip().lower()
            
            if normalized in (name_norm, email_norm, user_id_norm):
                user_info = info
                user_name = name
                email = info.get('email', '')
                break
        
        if not user_info:
            return jsonify({'error': 'Користувача не знайдено'}), 404
        
        base_dir = current_app.config.get('BASE_DIR', os.path.dirname(os.path.dirname(__file__)))
        level_grade_data = load_level_grade_data(base_dir)
        if not level_grade_data:
            return jsonify({'error': 'Level_Grade.json не знайдено'}), 404

        adapted = get_adapted_hierarchy_for_user(user_name, user_info, level_grade_data)
        if not adapted:
            return jsonify({'error': 'Не знайдено співпадіння в Level_Grade.json'}), 404

        updated_fields = apply_adapted_hierarchy(user_info, adapted)
        users[user_name] = user_info
        if updated_fields:
            if not schedule_user_manager.save_users(schedules):
                return jsonify({'error': 'Не вдалося зберегти оновлені дані'}), 500
            clear_user_schedule_cache()
        
        _log_admin_action('adapt_employee', {
            'user_key': normalized,
            'user_name': user_name,
            'email': email,
            'updated_fields': updated_fields,
        })
        
        db.session.commit()
        
        return jsonify({
            'status': 'ok',
            'user_name': user_name,
            'updated_fields': updated_fields,
            'user_info': user_info,
        })
        
    except Exception as exc:
        logger.error(f"Error adapting employee {key}: {exc}", exc_info=True)
        return jsonify({'error': f'Помилка адаптації: {str(exc)}'}), 500


@api_bp.route('/admin/adapt-hierarchy', methods=['POST'])
@login_required
def admin_adapt_hierarchy():
    """Адаптує ієрархію без збереження користувача (для diff add modal)."""
    _ensure_admin()
    
    try:
        payload = request.get_json() or {}
        
        project = (payload.get('project') or '').strip()
        department = (payload.get('department') or '').strip()
        unit = (payload.get('unit') or '').strip()
        team = (payload.get('team') or '').strip()
        
        if not any([project, department, unit, team]):
            return jsonify({'error': 'Не вказано жодного поля ієрархії'}), 400
        
        base_dir = current_app.config.get('BASE_DIR', os.path.dirname(os.path.dirname(__file__)))
        level_grade_data = load_level_grade_data(base_dir)
        if not level_grade_data:
            return jsonify({'error': 'Level_Grade.json не знайдено'}), 404
        
        logger.info(f"Adapting hierarchy: project={project}, department={department}, unit={unit}, team={team}")
        
        match = find_level_grade_match(None, project, department, unit, team, level_grade_data)
        if not match:
            return jsonify({'error': 'Не знайдено співпадіння в Level_Grade.json'}), 404
        
        adapted = build_adapted_hierarchy(match, fallback_location=payload.get('location', ''))
        updated_fields = []
        if project and adapted.get('project') != project:
            updated_fields.append('project')
        if department and adapted.get('department') != department:
            updated_fields.append('department')
        if unit and adapted.get('unit') != unit:
            updated_fields.append('unit')
        if team and adapted.get('team') != team:
            updated_fields.append('team')
        if adapted.get('location') and adapted.get('location') != payload.get('location'):
            updated_fields.append('location')
        if adapted.get('control_manager') is not None:
            updated_fields.append('control_manager')
        
        return jsonify({
            'status': 'ok',
            'adapted': adapted,
            'updated_fields': updated_fields,
        })
        
    except Exception as exc:
        logger.error(f"Error adapting hierarchy: {exc}", exc_info=True)
        return jsonify({'error': f'Помилка адаптації: {str(exc)}'}), 500


@api_bp.route('/admin/adapt-hierarchy/bulk', methods=['POST'])
@login_required
def admin_adapt_hierarchy_bulk():
    """Перезаписати ієрархію всіх користувачів за Level_Grade.json."""
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    force_reset = bool(payload.get('force_reset_overrides'))
    try:
        from dashboard_app.tasks import run_level_grade_adaptation
        stats = run_level_grade_adaptation(current_app, force=True or force_reset)
    except FileNotFoundError:
        return jsonify({'error': 'Level_Grade.json не знайдено'}), 404
    except Exception as exc:
        logger.error("Bulk hierarchy adaptation failed: %s", exc, exc_info=True)
        return jsonify({'error': f'Не вдалося адаптувати ієрархію: {str(exc)}'}), 500

    _log_admin_action('bulk_adapt_hierarchy', {
        'force_reset': force_reset,
        'updated': stats.get('updated'),
        'total': stats.get('total'),
    })
    db.session.commit()

    return jsonify({
        'status': 'ok',
        'updated': stats.get('updated'),
        'total': stats.get('total'),
        'force_reset_overrides': force_reset,
    })


@api_bp.route('/admin/employees/<path:user_key>/ignore', methods=['POST'])
@login_required
def admin_ignore_employee(user_key: str):
    """Add employee to ignore list (exclude from reports and diff)."""
    _ensure_admin()
    normalized = _normalize_user_key(user_key)
    
    try:
        data = schedule_user_manager.load_users()
        users = data.get('users', {}) if isinstance(data, dict) else {}
        
        # Find user
        user_name = None
        user_info = None
        normalized_lower = normalized.lower()
        
        for name, info in users.items():
            if not isinstance(info, dict):
                continue
            variants = {
                name.strip().lower(),
                str(info.get('email', '')).strip().lower(),
                str(info.get('user_id', '')).strip().lower(),
            }
            if normalized_lower in variants:
                user_name = name
                user_info = info
                break
        
        if not user_info:
            return jsonify({'error': 'User not found'}), 404
        
        # Set ignored flag
        user_info['ignored'] = True
        schedule_user_manager.save_users(data)
        clear_user_schedule_cache()
        
        _log_admin_action('ignore_employee', {
            'user_name': user_name,
            'user_key': user_key,
        })
        db.session.commit()
        
        return jsonify({
            'status': 'ok',
            'user_name': user_name,
            'ignored': True
        })
        
    except Exception as exc:
        logger.error(f"Error ignoring employee {user_key}: {exc}", exc_info=True)
        return jsonify({'error': str(exc)}), 500


@api_bp.route('/admin/employees/<path:user_key>/unignore', methods=['POST'])
@login_required
def admin_unignore_employee(user_key: str):
    """Remove employee from ignore list (include in reports and diff)."""
    _ensure_admin()
    normalized = _normalize_user_key(user_key)
    
    try:
        data = schedule_user_manager.load_users()
        users = data.get('users', {}) if isinstance(data, dict) else {}
        
        # Find user
        user_name = None
        user_info = None
        normalized_lower = normalized.lower()
        
        for name, info in users.items():
            if not isinstance(info, dict):
                continue
            variants = {
                name.strip().lower(),
                str(info.get('email', '')).strip().lower(),
                str(info.get('user_id', '')).strip().lower(),
            }
            if normalized_lower in variants:
                user_name = name
                user_info = info
                break
        
        if not user_info:
            return jsonify({'error': 'User not found'}), 404
        
        # Remove ignored flag
        user_info.pop('ignored', None)
        schedule_user_manager.save_users(data)
        clear_user_schedule_cache()
        
        _log_admin_action('unignore_employee', {
            'user_name': user_name,
            'user_key': user_key,
        })
        db.session.commit()
        
        return jsonify({
            'status': 'ok',
            'user_name': user_name,
            'ignored': False
        })
        
    except Exception as exc:
        logger.error(f"Error unignoring employee {user_key}: {exc}", exc_info=True)
        return jsonify({'error': str(exc)}), 500


def _is_synced_employee(user: User) -> bool:
    """Перевіряє чи користувач є синхронізованим співробітником з PeopleForce."""
    names, emails, ids = _schedule_identity_sets()
    if user.email and user.email.strip().lower() in emails:
        return True
    if user.name and user.name.strip().lower() in names:
        return True
    return False


@api_bp.route('/admin/app-users')
@login_required
def admin_app_users():
    _ensure_admin()
    users = User.query.order_by(User.created_at.asc()).all()
    # Показуємо тільки адмінів та control_manager
    visible = [user for user in users if user.is_admin or user.is_control_manager]
    return jsonify({'items': [_serialize_app_user(user) for user in visible]})


@api_bp.route('/admin/app-users', methods=['POST'])
@login_required
def admin_create_app_user():
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip().lower()
    name = (payload.get('name') or '').strip()
    password = payload.get('password')
    manager_filter = (payload.get('manager_filter') or '').strip()
    is_admin = bool(payload.get('is_admin'))
    is_control_manager = bool(payload.get('is_control_manager'))

    if not email or not name:
        return jsonify({'error': 'email and name are required'}), 400

    existing_user = User.query.filter(db.func.lower(User.email) == email).first()
    if existing_user:
        existing_user.name = name
        existing_user.manager_filter = manager_filter
        existing_user.is_admin = is_admin
        existing_user.is_control_manager = is_control_manager
        if password:
            existing_user.set_password(password)
            _password_matches_default.cache_clear()
        _log_admin_action('update_app_user_existing', {
            'user_id': existing_user.id,
            'email': email,
            'is_admin': is_admin,
            'is_control_manager': is_control_manager,
            'manager_filter': manager_filter,
            'created_via': 'create_endpoint',
            'password_updated': bool(password),
        })
        db.session.commit()
        return jsonify({'user': _serialize_app_user(existing_user)})

    if not password:
        return jsonify({'error': 'password is required for new users'}), 400

    user = User(email=email, name=name, manager_filter=manager_filter, is_admin=is_admin, is_control_manager=is_control_manager)
    user.set_password(password)
    _password_matches_default.cache_clear()
    db.session.add(user)
    _log_admin_action('create_app_user', {
        'email': email,
        'name': name,
        'is_admin': is_admin,
        'is_control_manager': is_control_manager,
        'manager_filter': manager_filter,
    })
    db.session.commit()

    return jsonify({'user': _serialize_app_user(user)})


@api_bp.route('/admin/app-users/<int:user_id>', methods=['PATCH'])
@login_required
def admin_update_app_user(user_id: int):
    _ensure_admin()
    user = User.query.get_or_404(user_id)
    payload = request.get_json(silent=True) or {}

    email = payload.get('email')
    if isinstance(email, str) and email.strip():
        new_email = email.strip().lower()
        # Check if email is being changed and if new email already exists
        if new_email != user.email:
            existing = User.query.filter(db.func.lower(User.email) == new_email).first()
            if existing:
                return jsonify({'error': 'Email вже використовується'}), 400
            user.email = new_email

    name = payload.get('name')
    if isinstance(name, str) and name.strip():
        user.name = name.strip()

    if 'manager_filter' in payload:
        user.manager_filter = (payload.get('manager_filter') or '').strip()

    if 'is_admin' in payload:
        user.is_admin = bool(payload.get('is_admin'))

    if 'is_control_manager' in payload:
        user.is_control_manager = bool(payload.get('is_control_manager'))

    if 'password' in payload:
        password = payload.get('password')
        if isinstance(password, str) and password.strip():
            user.set_password(password.strip())
            _password_matches_default.cache_clear()

    _log_admin_action('update_app_user', {
        'user_id': user.id,
        'email': user.email,
        'is_admin': user.is_admin,
        'is_control_manager': user.is_control_manager,
        'manager_filter': user.manager_filter,
        'name': user.name,
    })
    db.session.commit()

    return jsonify({'user': _serialize_app_user(user)})


@api_bp.route('/admin/app-users/<int:user_id>', methods=['DELETE'])
@login_required
def admin_delete_app_user(user_id: int):
    _ensure_admin()
    user = User.query.get_or_404(user_id)
    if user.id == getattr(current_user, 'id', None):
        return jsonify({'error': 'Неможливо видалити себе'}), 400

    db.session.delete(user)
    _log_admin_action('delete_app_user', {'user_id': user_id, 'email': user.email})
    db.session.commit()
    return jsonify({'status': 'deleted'})


@api_bp.route('/admin/attendance/<date_str>', methods=['DELETE'])
@login_required
def admin_delete_attendance_by_date(date_str: str):
    """Видалення всіх записів відвідуваності за конкретну дату (тільки для адмінів)"""
    _ensure_admin()
    
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({'error': 'Некоректний формат дати. Очікується YYYY-MM-DD'}), 400
    
    # Видаляємо всі записи за цю дату
    deleted_count = AttendanceRecord.query.filter_by(record_date=target_date).delete()
    
    _log_admin_action('delete_attendance_date', {
        'date': date_str,
        'deleted_count': deleted_count
    })
    
    db.session.commit()
    
    return jsonify({
        'status': 'deleted',
        'date': date_str,
        'deleted_count': deleted_count
    })


def _available_control_managers() -> list[int]:
    schedules = load_user_schedules()
    values = {
       
        info.get('control_manager')
        for info in schedules.values()
        if info.get('control_manager') not in (None, '')
    }
    result: set[int] = set()
    for value in values:
        try:
            result.add(int(str(value).strip()))
        except (TypeError, ValueError):
            continue
    return sorted(result)


def _user_accessible(schedule: dict | None) -> bool:
    allowed = current_user.allowed_managers
    if not allowed:
        return True
    if not schedule:
        return False
    manager = schedule.get('control_manager')
    if manager is None or manager == '':
        return False
    try:
        manager_id = int(manager)
    except (TypeError, ValueError):
        return False
    return manager_id in allowed


def _load_user_schedule_variants(identifier: str, records: list[AttendanceRecord]) -> dict | None:
    schedule = get_user_schedule(identifier)
    if schedule:
        return schedule
    for record in records:
        if record.user_email:
            schedule = get_user_schedule(record.user_email)
            if schedule:
                return schedule
    if records:
        return get_user_schedule(records[0].user_name)
    return None


def _collect_recent_records(records: list[AttendanceRecord], start: date | None, end: date | None) -> list[dict]:
    filtered = records
    if start:
        filtered = [rec for rec in filtered if rec.record_date >= start]
    if end:
        filtered = [rec for rec in filtered if rec.record_date <= end]
    filtered.sort(key=lambda rec: rec.record_date, reverse=True)
    if not start and not end:
        filtered = [rec for rec in filtered if rec.record_date.weekday() < 5][:5]
    return [_serialize_attendance_record(rec) for rec in filtered]


def _build_week_lateness(records: list[AttendanceRecord]) -> dict:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    days = [week_start + timedelta(days=i) for i in range(5)]
    late_map = {rec.record_date: rec.minutes_late for rec in records if rec.record_date in days}
    weekday_names = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ']
    labels = [f"{weekday_names[i]}.{day.strftime('%d.%m.%y')}" for i, day in enumerate(days)]
    values = [late_map.get(day, 0) for day in days]
    return {'labels': labels, 'values': values}


def _serialize_profile(schedule: dict | None, record: AttendanceRecord | None) -> dict:
    profile = {
        'name': None,
        'email': None,
        'user_id': None,
        'project': None,
        'department': None,
        'team': None,
        'location': None,
        'plan_start': None,
        'control_manager': None,
        'peopleforce_id': None,
        'telegram_username': None,
        'manager_name': None,
        'manager_telegram': None,
    }

    if schedule:
        profile.update({
            'name': schedule.get('name') or profile['name'],
            'email': schedule.get('email') or profile['email'],
            'user_id': schedule.get('user_id') or profile['user_id'],
            'project': schedule.get('project') or profile['project'],
            'department': schedule.get('department') or profile['department'],
            'team': schedule.get('team') or profile['team'],
            'location': schedule.get('location') or profile['location'],
            'plan_start': schedule.get('start_time') or profile['plan_start'],
            'control_manager': schedule.get('control_manager') if schedule.get('control_manager') not in ('', None) else profile['control_manager'],
            'peopleforce_id': schedule.get('peopleforce_id') or profile['peopleforce_id'],
            'telegram_username': schedule.get('telegram_username') or profile['telegram_username'],
            'manager_name': schedule.get('manager_name') or profile['manager_name'],
            'manager_telegram': schedule.get('manager_telegram') or profile['manager_telegram'],
        })

    if record:
        profile.update({
            'name': record.user_name or profile['name'],
            'email': record.user_email or profile['email'],
            'user_id': record.user_id or profile['user_id'],
            'project': record.project or profile['project'],
            'department': record.department or profile['department'],
            'team': record.team or profile['team'],
            'location': record.location or profile['location'],
            'plan_start': record.scheduled_start or profile['plan_start'],
            'control_manager': record.control_manager if record.control_manager is not None else profile['control_manager'],
        })

    # Автогенерація telegram username якщо не задано
    if not profile['telegram_username'] and profile['name']:
        profile['telegram_username'] = _generate_telegram_username(profile['name'])

    # Нормалізація location
    location_normalized = _normalize_location_label(profile.get('location'))
    if location_normalized is not None:
        profile['location'] = location_normalized

    return profile


@api_bp.route('/users/<path:user_key>')
@login_required
def api_user_detail(user_key: str):
    base_query = _apply_filters(AttendanceRecord.query)
    date_from = _parse_date(request.args.get('date_from'))
    date_to = _parse_date(request.args.get('date_to'))
    query, normalized_key = _apply_user_key_filter(base_query, user_key)
    if date_from:
        query = query.filter(AttendanceRecord.record_date >= date_from)
    if date_to:
        query = query.filter(AttendanceRecord.record_date <= date_to)
    records = query.order_by(AttendanceRecord.record_date.asc()).all()

    schedule = _load_user_schedule_variants(normalized_key, records)

    if not records and not schedule:
        abort(404)

    if records:
        primary_record = records[0]
    else:
        primary_record = None

    if not records and not _user_accessible(schedule):
        abort(404)

    profile = _serialize_profile(schedule, primary_record)
    recent_records = _collect_recent_records(records, date_from, date_to)
    lateness = _build_week_lateness(records)
    
    # Фіксований список статусів
    status_options = ['присутствовал', 'отпуск', 'больничный', 'за свой счет']

    is_admin = bool(getattr(current_user, 'is_admin', False))
    is_control_manager = bool(getattr(current_user, 'is_control_manager', False))
    can_edit = is_admin or is_control_manager

    permissions = {
        'can_edit': can_edit,
        'can_change_manager': is_admin,
    }

    return jsonify({
        'profile': profile,
        'schedule': schedule or {},
        'recent_records': recent_records,
        'lateness': lateness,
        'permissions': permissions,
        'manager_options': _available_control_managers(),
        'status_options': status_options,
        'date_range': {
            'date_from': date_from.isoformat() if date_from else '',
            'date_to': date_to.isoformat() if date_to else '',
        }
    })


def _record_belongs_to_user(record: AttendanceRecord, user_key: str) -> bool:
    lowered = _normalize_user_key(user_key).lower()
    candidates = [
        (record.user_email or '').lower(),
        (record.user_id or '').lower(),
        (record.user_name or '').lower(),
    ]
    return lowered in candidates


@api_bp.route('/users/<path:user_key>/records/<int:record_id>', methods=['PATCH'])
@login_required
def api_update_user_record(user_key: str, record_id: int):
    is_admin = getattr(current_user, 'is_admin', False)
    is_control_manager = getattr(current_user, 'is_control_manager', False)
    
    if not (is_admin or is_control_manager):
        return jsonify({'error': 'Forbidden'}), 403

    record = AttendanceRecord.query.get_or_404(record_id)
    if not _record_belongs_to_user(record, user_key):
        return jsonify({'error': 'Record does not belong to user'}), 400

    allowed = current_user.allowed_managers
    if allowed and (record.control_manager not in allowed):
        return jsonify({'error': 'Forbidden'}), 403

    payload = request.get_json(silent=True) or {}

    if payload.get('reset_manual'):
        for flag_attr in MANUAL_FLAG_MAP.values():
            setattr(record, flag_attr, False)
        db.session.commit()
        return jsonify({'record': _serialize_attendance_record(record)})

    reset_fields = payload.get('reset_manual_fields') or []
    if reset_fields:
        for field in reset_fields:
            flag_attr = MANUAL_FLAG_MAP.get(field)
            if flag_attr:
                setattr(record, flag_attr, False)

    def set_manual_flag(field: str):
        flag_attr = MANUAL_FLAG_MAP.get(field)
        if flag_attr:
            setattr(record, flag_attr, True)

    def update_duration(field: str, attr: str):
        if field not in payload:
            return
        value = payload.get(field)
        if value in (None, ''):
            setattr(record, attr, 0)
            set_manual_flag(attr)
            return
        if isinstance(value, (int, float)):
            setattr(record, attr, int(value))
            set_manual_flag(attr)
            return
        parsed = _parse_duration(str(value))
        if parsed is not None:
            setattr(record, attr, parsed)
            set_manual_flag(attr)

    if 'scheduled_start' in payload:
        scheduled = payload.get('scheduled_start')
        record.scheduled_start = str(scheduled).strip() if scheduled not in (None, '') else None
        set_manual_flag('scheduled_start')

    if 'actual_start' in payload:
        actual = payload.get('actual_start')
        record.actual_start = str(actual).strip() if actual not in (None, '') else None
        set_manual_flag('actual_start')

    update_duration('minutes_late', 'minutes_late')
    update_duration('non_productive_minutes', 'non_productive_minutes')
    update_duration('not_categorized_minutes', 'not_categorized_minutes')
    update_duration('productive_minutes', 'productive_minutes')
    # total_minutes тепер розраховується автоматично (not_categorized + productive), не зберігаємо окремо
    # update_duration('total_minutes', 'manual_total_minutes')
    update_duration('corrected_total_minutes', 'corrected_total_minutes')

    if 'status' in payload:
        status = str(payload.get('status') or '').strip().lower()
        if status:
            record.status = status
            # Якщо статус "отпуск" або "за свой счет" - обнуляємо actual_start і продуктивний час
            if status in ('отпуск', 'за свой счет'):
                record.actual_start = None
                record.productive_minutes = 0
                record.not_categorized_minutes = 0
                record.non_productive_minutes = 0
                # total_minutes залишаємо, бо може бути скоригований вручну
        else:
            record.status = ''
        set_manual_flag('status')

    if 'notes' in payload:
        notes = payload.get('notes')
        record.notes = str(notes).strip() if notes not in (None, '') else None
        set_manual_flag('notes')

    if 'leave_reason' in payload:
        leave_reason = payload.get('leave_reason')
        record.leave_reason = str(leave_reason).strip() if leave_reason not in (None, '') else None
        set_manual_flag('leave_reason')

    db.session.commit()
    return jsonify({'record': _serialize_attendance_record(record)})


@api_bp.route('/users/<path:user_key>/manager', methods=['PATCH'])
@login_required
def api_update_user_manager(user_key: str):
    if not getattr(current_user, 'is_admin', False):
        return jsonify({'error': 'Forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    value = payload.get('control_manager')
    if value in (None, ''):
        manager_value = None
    else:
        try:
            manager_value = int(value)
        except (TypeError, ValueError):
            return jsonify({'error': 'control_manager must be integer or null'}), 400

    base_query = _apply_filters(AttendanceRecord.query)
    query, _ = _apply_user_key_filter(base_query, user_key)
    records = query.all()
    if not records:
        return jsonify({'error': 'User not found or no access'}), 404

    for record in records:
        record.control_manager = manager_value

    db.session.commit()

    return jsonify({'control_manager': manager_value})


@api_bp.route('/users/<path:user_key>/telegram', methods=['PATCH'])
@login_required
def api_update_user_telegram(user_key: str):
    if not getattr(current_user, 'is_admin', False):
        return jsonify({'error': 'Forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    telegram_username = payload.get('telegram_username', '').strip()

    # Знаходимо користувача в schedule
    schedule = _load_user_schedule_variants(user_key, [])
    if not schedule:
        return jsonify({'error': 'User not found'}), 404
    
    user_name = schedule.get('name')
    if not user_name:
        return jsonify({'error': 'User name not found'}), 404
    
    # Оновлюємо telegram_username в user_schedules.json
    try:
        from dashboard_app.user_data import load_user_schedules
        from tracker_alert.services.user_manager import save_users, load_users
        
        # load_user_schedules() повертає тільки словник користувачів
        users = load_user_schedules()
        if user_name not in users:
            return jsonify({'error': f'User "{user_name}" not found in schedules'}), 404
        
        # Оновлюємо telegram_username
        users[user_name]['telegram_username'] = telegram_username if telegram_username else None
        
        # Зберігаємо через save_users який очікує повну структуру
        full_data = load_users()  # Отримуємо повну структуру з metadata
        full_data['users'] = users  # Оновлюємо користувачів
        
        # Зберігаємо
        if save_users(full_data):
            # Очищаємо кеш
            clear_user_schedule_cache()
            return jsonify({'telegram_username': telegram_username})
        else:
            return jsonify({'error': 'Failed to save'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/users/<path:user_key>/plan_start', methods=['PATCH'])
@login_required
def api_update_user_plan_start(user_key: str):
    """Глобально змінити плановий час старту для користувача."""
    if not getattr(current_user, 'is_control_manager', False) and not getattr(current_user, 'is_admin', False):
        return jsonify({'error': 'Forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    plan_start = payload.get('plan_start', '').strip()
    apply_to_month = payload.get('apply_to_month', False)

    if not plan_start:
        return jsonify({'error': 'plan_start is required'}), 400

    # Валідація формату часу (HH:MM)
    import re
    if not re.match(r'^\d{1,2}:\d{2}$', plan_start):
        return jsonify({'error': 'Invalid time format. Expected HH:MM'}), 400

    # Знаходимо користувача в schedule
    schedule = _load_user_schedule_variants(user_key, [])
    if not schedule:
        return jsonify({'error': 'User not found'}), 404
    
    user_name = schedule.get('name')
    if not user_name:
        return jsonify({'error': 'User name not found'}), 404
    
    # Оновлюємо start_time в user_schedules.json
    try:
        from dashboard_app.user_data import load_user_schedules, clear_user_schedule_cache
        from tracker_alert.services.user_manager import save_users, load_users
        from tracker_alert.services.schedule_utils import set_manual_override
        from datetime import datetime
        
        # load_user_schedules() повертає тільки словник користувачів
        users = load_user_schedules()
        if user_name not in users:
            return jsonify({'error': f'User "{user_name}" not found in schedules'}), 404
        
        # Оновлюємо start_time
        users[user_name]['start_time'] = plan_start
        
        # Встановлюємо прапорець manual override
        set_manual_override(users[user_name], 'start_time')
        
        # Зберігаємо через save_users який очікує повну структуру
        full_data = load_users()  # Отримуємо повну структуру з metadata
        full_data['users'] = users  # Оновлюємо користувачів
        
        # Зберігаємо
        if not save_users(full_data):
            return jsonify({'error': 'Failed to save'}), 500
        
        # Очищаємо кеш
        clear_user_schedule_cache()
        
        updated_days = 0
        
        # Якщо потрібно застосувати до поточного місяця
        if apply_to_month:
            today = datetime.now()
            first_day = today.replace(day=1).date()
            
            # Отримуємо всі записи користувача за поточний місяць
            base_query = _apply_filters(AttendanceRecord.query)
            query, _ = _apply_user_key_filter(base_query, user_key)
            
            records = query.filter(
                AttendanceRecord.record_date >= first_day,
                AttendanceRecord.record_date <= today.date()
            ).all()
            
            # Оновлюємо тільки записи БЕЗ ручних змін scheduled_start
            for record in records:
                if not record.manual_scheduled_start:
                    record.scheduled_start = plan_start
                    updated_days += 1
            
            if updated_days > 0:
                db.session.commit()
        
        return jsonify({
            'plan_start': plan_start,
            'updated_days': updated_days if apply_to_month else None
        })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/users/<path:user_key>/monthly_category_stats')
@login_required
def api_user_monthly_category_stats(user_key: str):
    """Отримати статистику по категоріях за місяць для конкретного користувача."""
    # Отримуємо параметри року та місяця
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    
    if not year or not month:
        # Використовуємо поточний місяць якщо не передано
        now = datetime.now()
        year = year or now.year
        month = month or now.month
    
    # Визначаємо перший та останній день місяця
    from calendar import monthrange
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    
    # Базовий запит БЕЗ фільтрів дат (тільки manager фільтр)
    base_query = AttendanceRecord.query
    
    # Застосовуємо фільтр за manager (якщо не адмін)
    allowed_managers = current_user.allowed_managers
    if allowed_managers:
        base_query = base_query.filter(AttendanceRecord.control_manager.in_(allowed_managers))
    
    # Застосовуємо фільтр за користувачем
    query, normalized_key = _apply_user_key_filter(base_query, user_key)
    
    # Фільтруємо за датами місяця
    query = query.filter(
        AttendanceRecord.record_date >= first_day,
        AttendanceRecord.record_date <= last_day
    )
    
    # Отримуємо всі записи за місяць
    records = query.all()
    
    if not records:
        return jsonify({
            'not_categorized': 0,
            'productive': 0,
            'non_productive': 0,
            'total': 0,
            'monthly_lateness': 0,
            'year': year,
            'month': month
        })
    
    # Підраховуємо суми
    not_categorized_total = sum(r.not_categorized_minutes or 0 for r in records)
    productive_total = sum(r.productive_minutes or 0 for r in records)
    non_productive_total = sum(r.non_productive_minutes or 0 for r in records)
    total_minutes = sum(r.total_minutes or 0 for r in records)
    monthly_lateness_total = sum(r.minutes_late or 0 for r in records)
    
    return jsonify({
        'not_categorized': not_categorized_total,
        'productive': productive_total,
        'non_productive': non_productive_total,
        'total': total_minutes,
        'monthly_lateness': monthly_lateness_total,
        'year': year,
        'month': month
    })


@api_bp.route('/attendance/<int:record_id>/notes', methods=['PATCH'])
@login_required
def update_attendance_notes(record_id: int):
    record = AttendanceRecord.query.get_or_404(record_id)

    allowed_managers = current_user.allowed_managers
    if allowed_managers and record.control_manager not in allowed_managers:
        return jsonify({'error': 'Forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    notes = payload.get('notes', '')
    if isinstance(notes, str):
        record.notes = notes.strip()
    else:
        record.notes = ''
    record.manual_notes = True

    db.session.commit()
    return jsonify({
        'record_id': record.id,
        'notes': record.notes or '',
        'display': record.notes or record.leave_reason or ''
    })


@api_bp.route('/export')
@login_required
def export_attendance():
    items, _ = _get_filtered_items()
    structured_rows = _build_excel_rows(items)

    wb = Workbook()
    ws = wb.active
    ws.title = 'Attendance'

    for entry in structured_rows:
        ws.append(entry['values'])
        entry['index'] = ws.max_row
        role = entry['role']
        row_idx = entry['index']
        if role == 'summary_period':
            ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=2)
            ws.merge_cells(start_row=row_idx, start_column=3, end_row=row_idx, end_column=5)
        elif role == 'summary_team':
            ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=2)
            ws.merge_cells(start_row=row_idx, start_column=3, end_row=row_idx, end_column=6)
        elif role == 'week_total':
            ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=2)

    column_widths = [22, 14, 14, 14, 16, 16, 14, 14, 14, 28]
    for idx, width in enumerate(column_widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    thin_side = Side(style='thin', color='000000')
    thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    bottom_border = Border(bottom=thin_side)

    left_align = Alignment(horizontal='left', vertical='center', wrap_text=True)
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    right_align = Alignment(horizontal='right', vertical='center', wrap_text=True)
    summary_align = Alignment(horizontal='left', vertical='top', wrap_text=True)

    non_productive_fill = PatternFill(fill_type='solid', fgColor='FAEBD7')
    not_categorized_fill = PatternFill(fill_type='solid', fgColor='E8E8E8')
    productive_fill = PatternFill(fill_type='solid', fgColor='D7F6B2')
    total_fill = PatternFill(fill_type='solid', fgColor='9DE6FA')
    summary_fill = PatternFill(fill_type='solid', fgColor='EEEEEE')

    fill_map = {
        5: non_productive_fill,
        6: not_categorized_fill,
        7: productive_fill,
        8: total_fill,
    }

    header_font = Font(bold=True)
    week_total_font = Font(bold=True)

    max_col = ws.max_column

    for entry in structured_rows:
        row_idx = entry['index']
        role = entry['role']

        for col_idx in range(1, max_col + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            if isinstance(cell, MergedCell):
                continue

            if role in {'summary_period', 'summary_team'}:
                if col_idx == 1:
                    cell.font = header_font
                cell.alignment = summary_align
                continue

            if role == 'divider':
                cell.border = bottom_border
                continue

            if role == 'user_header':
                cell.border = thin_border
                if col_idx == 1:
                    cell.font = header_font
                    cell.alignment = left_align
                else:
                    cell.font = header_font
                    cell.alignment = center_align
                    if col_idx in fill_map:
                        cell.fill = fill_map[col_idx]
                continue

            if role == 'data':
                cell.border = thin_border
                if col_idx in (1, 9):
                    cell.alignment = left_align
                else:
                    cell.alignment = center_align
                continue

            if role == 'week_total':
                cell.border = thin_border
                if col_idx == 1:
                    cell.font = week_total_font
                    cell.alignment = right_align
                    cell.fill = summary_fill
                elif col_idx in (2, 3, 4, 9):
                    cell.alignment = center_align
                    cell.fill = summary_fill
                else:
                    cell.alignment = center_align
                    if col_idx in fill_map:
                        cell.fill = fill_map[col_idx]
                continue

            cell.alignment = left_align if col_idx == 1 else center_align

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"attendance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


def _resolve_period_display() -> str:
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    formatted_from = _format_period_date(date_from)
    formatted_to = _format_period_date(date_to)
    if formatted_from and formatted_to:
        return f"{formatted_from} - {formatted_to}"
    if formatted_from:
        return f"с {formatted_from}"
    if formatted_to:
        return f"до {formatted_to}"
    return '—'


def _format_period_date(value: str | None) -> str:
    if not value:
        return ''
    parsed = _parse_date(value)
    if not parsed:
        return value
    return parsed.strftime('%d.%m.%y')


def _resolve_team_display() -> str:
    selected = {
        'project': request.args.get('project', ''),
        'department': request.args.get('department', ''),
        'team': request.args.get('team', ''),
    }
    filters = _get_schedule_filters(selected)
    resolved = filters.get('selected', {}) if isinstance(filters, dict) else {}

    def resolved_value(field: str, default_label: str) -> str:
        value = resolved.get(field) if isinstance(resolved, dict) else None
        return value or selected.get(field) or default_label

    project = resolved_value('project', 'Все проекты')
    department = resolved_value('department', 'Все департаменты')
    team = resolved_value('team', 'Все команды')
    return f"{project} / {department} / {team}"


def _build_excel_rows(items: list[dict]) -> list[dict[str, object]]:
    cols = 10
    rows: list[dict[str, object]] = [
        {'values': ['Отчет сформирован за період:', '', _resolve_period_display(), '', '', '', '', '', '', ''], 'role': 'summary_period'},
        {'values': ['по команді:', '', _resolve_team_display(), '', '', '', '', '', '', ''], 'role': 'summary_team'},
        {'values': [''] * cols, 'role': 'divider'}
    ]

    header_suffix = ['Plan Start', 'Date', 'Fact Start', 'Non Productive', 'Not Categorized', 'Prodactive', 'Total', 'Total Corrected', 'Notes']

    for item_index, item in enumerate(items):
        user_name = (item.get('user_name') or '').strip()
        rows.append({'values': [user_name, *header_suffix], 'role': 'user_header'})

        project = (item.get('project') or '-').strip() or '-'
        department = (item.get('department') or '-').strip() or '-'
        team = (item.get('team') or '-').strip() or '-'
        raw_location = item.get('location')
        normalized_location = _normalize_location_label(raw_location)
        location_value = (normalized_location if normalized_location is not None else (raw_location or '-')).strip() or '-'
        project_line = f"{project} / {department} / {team}".strip()

        for idx, row in enumerate(item['rows']):
            if idx == 0:
                first_cell = project_line
            elif idx == 1:
                first_cell = location_value
            else:
                first_cell = ''
            values = [
                first_cell,
                row.get('scheduled_start_hm') or row.get('scheduled_start') or '',
                row.get('date_display') or '',
                row.get('actual_start_hm') or row.get('actual_start') or '',
                row.get('non_productive_hm') or row.get('non_productive_display') or '',
                row.get('not_categorized_hm') or row.get('not_categorized_display') or '',
                row.get('productive_hm') or row.get('productive_display') or '',
                row.get('total_hm') or row.get('total_display') or '',
                row.get('corrected_total_hm') or row.get('corrected_total_display') or '',
                (row.get('notes_display') or row.get('notes') or '').strip()
            ]
            rows.append({'values': values, 'role': 'data'})

        if item.get('week_total'):
            wt = item['week_total']
            rows.append({
                'values': [
                    'Week total', '', '', '',
                    wt.get('non_productive_hm') or wt['non_productive_display'],
                    wt.get('not_categorized_hm') or wt['not_categorized_display'],
                    wt.get('productive_hm') or wt['productive_display'],
                    wt.get('total_hm') or wt['total_display'],
                    wt.get('corrected_total_hm') or wt.get('corrected_total_display') or '',
                    ''
                ],
                'role': 'week_total'
            })

        if item_index < len(items) - 1:
            rows.append({'values': [''] * cols, 'role': 'spacer'})

    return rows





def _build_pdf_document(items: list[dict]) -> BytesIO:
    if SimpleDocTemplate is None:
        raise RuntimeError('PDF generation is unavailable (missing reportlab)')

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=7 * mm,
        rightMargin=5 * mm,
        topMargin=5 * mm,
        bottomMargin=5 * mm,
    )

    font_regular, font_bold = _ensure_pdf_fonts()

    base_widths_mm = [30, 13, 12, 13, 13, 13, 13, 13, 13, 30]
    total_points = sum(width * mm for width in base_widths_mm)
    scale_factor = doc.width / total_points if total_points else 1
    col_widths = [width * mm * scale_factor for width in base_widths_mm]

    if Paragraph is None or ParagraphStyle is None:
        raise RuntimeError('PDF generation is unavailable (missing reportlab styles)')

    summary_label_style = ParagraphStyle(
        'summary_label',
        fontName=font_bold,
        fontSize=10,
        leading=12,
        alignment=0,
    )
    summary_text_style = ParagraphStyle(
        'summary_text',
        fontName=font_regular,
        fontSize=10,
        leading=12,
        alignment=0,
    )
    cell_text_style = ParagraphStyle(
        'cell_text',
        fontName=font_regular,
        fontSize=9,
        leading=11,
        alignment=0,
    )
    cell_text_bold_style = ParagraphStyle(
        'cell_text_bold',
        parent=cell_text_style,
        fontName=font_bold,
    )
    cell_text_right_bold_style = ParagraphStyle(
        'cell_text_right_bold',
        parent=cell_text_style,
        fontName=font_bold,
        alignment=2,
    )

    def make_paragraph(value: str | None, style: ParagraphStyle) -> Paragraph:
        text = escape(value or '').replace('\n', '<br/>')
        if not text:
            text = '&nbsp;'
        return Paragraph(text, style)

    summary_data = [
        [make_paragraph('Отчет сформирован за период:', summary_label_style), '', '', make_paragraph(_resolve_period_display(), summary_text_style), '', '', '', '', '', ''],
        [make_paragraph('по команде:', summary_label_style), '', '', make_paragraph(_resolve_team_display(), summary_text_style), '', '', '', '', '', '']
    ]

    summary_table = Table(summary_data, colWidths=col_widths)
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_regular),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('WORDWRAP', (0, 0), (-1, -1), True),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('SPAN', (0, 0), (2, 0)),
        ('SPAN', (3, 0), (9, 0)),
        ('SPAN', (0, 1), (2, 1)),
        ('SPAN', (3, 1), (9, 1)),
        ('ALIGN', (0, 0), (2, 1), 'LEFT'),
        ('ALIGN', (3, 0), (9, 1), 'LEFT'),
        ('LINEBELOW', (0, 1), (-1, 1), 0.5, colors.black),
    ]))

    story = [summary_table, Spacer(1, 6)]

    header_labels = ['Plan Start', 'Date', 'Fact Start', 'Non Prod.', 'Not Cat.', 'Prod.', 'Total', 'Tot.cor.', 'Notes']

    zone_np = colors.HexColor('#FAEBD7')
    zone_nc = colors.HexColor('#E8E8E8')
    zone_prod = colors.HexColor('#D7F6B2')
    zone_total = colors.HexColor('#9DE6FA')
    zone_total_corrected = colors.HexColor('#FDD9A6')
    zone_summary = colors.HexColor('#EEEEEE')

    for item in items:
        table_data = []
        styles: list[tuple] = []

        user_name = (item.get('user_name') or '').strip()
        header_idx = len(table_data)
        table_data.append([make_paragraph(user_name, cell_text_bold_style), *header_labels])
        styles.extend([
            ('FONTNAME', (1, header_idx), (-1, header_idx), font_regular),
            ('FONTNAME', (0, header_idx), (0, header_idx), font_bold),
            ('ALIGN', (1, header_idx), (-1, header_idx), 'CENTER'),
            ('BACKGROUND', (4, header_idx), (4, header_idx), zone_np),
            ('BACKGROUND', (5, header_idx), (5, header_idx), zone_nc),
            ('BACKGROUND', (6, header_idx), (6, header_idx), zone_prod),
            ('BACKGROUND', (7, header_idx), (7, header_idx), zone_total),
            ('BACKGROUND', (8, header_idx), (8, header_idx), zone_total_corrected),
            ('BACKGROUND', (9, header_idx), (9, header_idx), zone_summary),
        ])

        project = (item.get('project') or '-').strip() or '-'
        department = (item.get('department') or '-').strip() or '-'
        team = (item.get('team') or '-').strip() or '-'
        raw_location = item.get('location')
        normalized_location = _normalize_location_label(raw_location)
        location_value = (normalized_location if normalized_location is not None else (raw_location or '-')).strip() or '-'
        project_line = f"{project} / {department} / {team}".strip()

        for idx, row in enumerate(item['rows']):
            if idx == 0:
                label = project_line
            elif idx == 1:
                label = location_value
            else:
                label = ''
            table_data.append([
                make_paragraph(label, cell_text_style),
                row.get('scheduled_start_hm') or row.get('scheduled_start') or '',
                row.get('date_display') or '',
                row.get('actual_start_hm') or row.get('actual_start') or '',
                row.get('non_productive_hm') or row.get('non_productive_display') or '',
                row.get('not_categorized_hm') or row.get('not_categorized_display') or '',
                row.get('productive_hm') or row.get('productive_display') or '',
                row.get('total_hm') or row.get('total_display') or '',
                row.get('corrected_total_hm') or row.get('corrected_total_display') or '',
                make_paragraph((row.get('notes_display') or row.get('notes') or '').strip(), cell_text_style)
            ])

        if item.get('week_total'):
            wt = item['week_total']
            week_total_idx = len(table_data)
            table_data.append([
                make_paragraph('Week total', cell_text_right_bold_style), '', '', '',
                wt.get('non_productive_hm') or wt['non_productive_display'],
                wt.get('not_categorized_hm') or wt['not_categorized_display'],
                wt.get('productive_hm') or wt['productive_display'],
                wt.get('total_hm') or wt['total_display'],
                wt.get('corrected_total_hm') or wt.get('corrected_total_display') or '',
                make_paragraph('', cell_text_style)
            ])
            styles.extend([
                ('SPAN', (0, week_total_idx), (1, week_total_idx)),
                ('FONTNAME', (0, week_total_idx), (-1, week_total_idx), font_bold),
                ('ALIGN', (0, week_total_idx), (0, week_total_idx), 'RIGHT'),
                ('BACKGROUND', (0, week_total_idx), (0, week_total_idx), zone_summary),
                ('BACKGROUND', (2, week_total_idx), (3, week_total_idx), zone_summary),
                ('BACKGROUND', (9, week_total_idx), (9, week_total_idx), zone_summary),
                ('BACKGROUND', (4, week_total_idx), (4, week_total_idx), zone_np),
                ('BACKGROUND', (5, week_total_idx), (5, week_total_idx), zone_nc),
                ('BACKGROUND', (6, week_total_idx), (6, week_total_idx), zone_prod),
                ('BACKGROUND', (7, week_total_idx), (7, week_total_idx), zone_total),
                ('BACKGROUND', (8, week_total_idx), (8, week_total_idx), zone_total_corrected),
            ])
        else:
            week_total_idx = None

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ('FONTNAME', (0, 0), (-1, -1), font_regular),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('WORDWRAP', (0, 0), (-1, -1), True),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('ALIGN', (9, 1), (9, -1), 'LEFT'),
        ]

        if week_total_idx is None:
            styles.append(('FONTNAME', (0, 0), (-1, 0), font_bold))

        table.setStyle(TableStyle(style_cmds + styles))
        story.append(table)
        story.append(Spacer(1, 6))

    doc.build(story)
    buffer.seek(0)
    return buffer


@api_bp.route('/admin/audit/logs')
@login_required
def admin_audit_logs():
    """Get audit log entries with filtering and pagination."""
    _ensure_admin()
    
    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = max(min(int(request.args.get('per_page', 50) or 50), 200), 10)
    action_filter = request.args.get('action', '').strip()
    user_filter = request.args.get('user', '').strip()
    date_from_str = request.args.get('date_from', '').strip()
    date_to_str = request.args.get('date_to', '').strip()
    
    query = AdminAuditLog.query
    
    # Filter by action
    if action_filter:
        query = query.filter(AdminAuditLog.action == action_filter)
    
    # Filter by user
    if user_filter:
        try:
            user_id = int(user_filter)
            query = query.filter(AdminAuditLog.user_id == user_id)
        except ValueError:
            pass
    
    # Filter by date range
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d')
            query = query.filter(AdminAuditLog.created_at >= date_from)
        except ValueError:
            pass
    
    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d')
            date_to = date_to.replace(hour=23, minute=59, second=59)
            query = query.filter(AdminAuditLog.created_at <= date_to)
        except ValueError:
            pass
    
    # Order by newest first
    query = query.order_by(AdminAuditLog.created_at.desc())
    
    # Paginate
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    # Serialize results
    items = []
    for log in pagination.items:
        user_name = log.user.name if log.user else 'System'
        user_email = log.user.email if log.user else ''
        items.append({
            'id': log.id,
            'user_id': log.user_id,
            'user_name': user_name,
            'user_email': user_email,
            'action': log.action,
            'details': log.details,
            'created_at': log.created_at.isoformat(),
            'created_at_display': log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        })
    
    # Get available actions for filter
    actions_query = db.session.query(AdminAuditLog.action).distinct().all()
    available_actions = sorted([action[0] for action in actions_query])
    
    # Get available users for filter
    users_query = db.session.query(User.id, User.name).all()
    available_users = [{'id': user_id, 'name': name} for user_id, name in users_query]
    
    return jsonify({
        'items': items,
        'total': pagination.total,
        'page': page,
        'per_page': per_page,
        'pages': pagination.pages,
        'has_prev': pagination.has_prev,
        'has_next': pagination.has_next,
        'filters': {
            'actions': available_actions,
            'users': available_users,
        }
    })


@api_bp.route('/report/pdf')
@login_required
def export_pdf():
    if SimpleDocTemplate is None:
        abort(503, description='PDF export недоступен: установите пакет reportlab (pip install reportlab).')

    items, _ = _get_filtered_items()
    pdf_stream = _build_pdf_document(items)
    filename = f"attendance_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return send_file(
        pdf_stream,
        as_attachment=True,
        download_name=filename,
        mimetype='application/pdf'
    )
def _is_ignored_person(name: str | None, email: str | None) -> bool:
    """Check if person should be ignored in reports and diff."""
    normalized_name = (name or '').strip().lower()
    normalized_email = (email or '').strip().lower()
    if not normalized_name and not normalized_email:
        return False
    
    # Check in user_schedules.json for dynamic ignore flag
    schedules = load_user_schedules()
    for user_name, info in schedules.items():
        if not isinstance(info, dict):
            continue
        # Check if this user is marked as ignored
        if not info.get('ignored', False):
            continue
        # Match by name
        if normalized_name and user_name.strip().lower() == normalized_name:
            return True
        # Match by email
        user_email = (info.get('email') or '').strip().lower()
        if normalized_email and user_email == normalized_email:
            return True
    
    return False


# List of PeopleForce IDs for employees with 7-day work week (including weekends)
SEVEN_DAY_WORK_WEEK_IDS = {
    297356,  # Iliin Eugeniy
    297357,  # Chernov Leonid
    297358,  # Demidov Viktor
    297365,  # Shpak Andrew
    551929,  # Zbutevich Illia
    297362,  # Andriy Pankov
    297363,  # Kiliovyi Evhen
    297364,  # Larina Olena
    356654,  # Pankov Oleksandr
    374722,  # Stopochkin Nykyta
    433837,  # Alina Serdiuk
    406860,  # Zdorovets Yuliia
    372364,  # Shubska Oleksandra
}


def _get_peopleforce_id_for_user(user_key: str) -> int | None:
    """Get PeopleForce ID for a user from user_schedules.json"""
    schedules = load_user_schedules()
    for user_name, info in schedules.items():
        if not isinstance(info, dict):
            continue
        if info.get('email', '').lower() == user_key.lower():
            pf_id = info.get('peopleforce_id')
            if pf_id:
                try:
                    return int(pf_id)
                except (ValueError, TypeError):
                    pass
    return None


def _count_work_days_in_month(year: int, month: int, include_weekends: bool = False) -> int:
    """
    Count work days in a month.
    
    Args:
        year: Year
        month: Month (1-12)
        include_weekends: If True, count all days including Sat/Sun
    
    Returns:
        Number of work days
    """
    from calendar import monthrange
    
    _, num_days = monthrange(year, month)
    
    if include_weekends:
        return num_days
    
    work_days = 0
    for day in range(1, num_days + 1):
        day_date = date(year, month, day)
        # 0 = Monday, 6 = Sunday
        if day_date.weekday() < 5:  # Monday to Friday
            work_days += 1
    
    return work_days


@api_bp.route('/monthly-report', methods=['GET'])
@login_required
def get_monthly_report():
    """
    Get monthly report data for all employees.
    
    Query parameters:
        - month: YYYY-MM format (default: current month)
        - manager: Control manager ID filter
        - department: Department filter
        - team: Team filter
        - project: Project filter
        - location: Location filter
        - user: User search term
        - selected_users: Comma-separated user keys
    """
    try:
        # Parse month parameter
        month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
        try:
            year, month = map(int, month_str.split('-'))
            first_day = date(year, month, 1)
            from calendar import monthrange
            _, last_day_num = monthrange(year, month)
            last_day = date(year, month, last_day_num)
        except (ValueError, AttributeError):
            return jsonify({'error': 'Invalid month format'}), 400
        
        # Build base query (don't use _apply_filters - it adds its own date filters)
        query = AttendanceRecord.query.filter(
            AttendanceRecord.record_date >= first_day,
            AttendanceRecord.record_date <= last_day
        )
        
        # Apply filters
        manager_id = request.args.get('manager')
        if manager_id:
            query = query.filter(AttendanceRecord.control_manager == int(manager_id))
        
        projects = [p for p in request.args.getlist('project') if p]
        if projects:
            query = query.filter(AttendanceRecord.project.in_(projects))
        
        departments = [d for d in request.args.getlist('department') if d]
        if departments:
            query = query.filter(AttendanceRecord.department.in_(departments))
        
        units = [u for u in request.args.getlist('unit') if u]
        teams = [t for t in request.args.getlist('team') if t]
        team_filters = list({*units, *teams})
        if team_filters:
            query = query.filter(AttendanceRecord.team.in_(team_filters))
        
        locations = [loc for loc in request.args.getlist('location') if loc]
        if locations:
            query = query.filter(AttendanceRecord.location.in_(locations))
        
        user_search = request.args.get('user', '').strip()
        if user_search:
            query = query.filter(
                or_(
                    AttendanceRecord.user_name.ilike(f'%{user_search}%'),
                    AttendanceRecord.user_email.ilike(f'%{user_search}%')
                )
            )
        
        selected_user_keys = [uk.strip().lower() for uk in request.args.getlist('user_key') if uk.strip()]
        legacy_selected = request.args.get('selected_users', '').strip()
        if legacy_selected:
            selected_user_keys.extend(uk.strip().lower() for uk in legacy_selected.split(',') if uk.strip())
        if selected_user_keys:
            query = query.filter(db.func.lower(AttendanceRecord.user_email).in_(selected_user_keys))
        
        # Get all records for the month
        records = query.all()

        # Limit records to users that exist in user_schedules.json (не показуємо автоматично імпортованих з YaWare)
        schedule_entries = _gather_schedule_users(search=None, ignored_only=False)
        allowed_names = { (entry.get('name') or '').strip().lower() for entry in schedule_entries if entry.get('name') }
        allowed_emails = { (entry.get('email') or '').strip().lower() for entry in schedule_entries if entry.get('email') }
        allowed_ids = { (entry.get('user_id') or '').strip().lower() for entry in schedule_entries if entry.get('user_id') }
        
        # Group by user
        user_data = defaultdict(lambda: {
            'user_key': '',
            'user_name': '',
            'user_email': '',
            'project': '',
            'department': '',
            'unit': '',
            'team': '',
            'records': [],
            'total_minutes': 0,
            'corrected_total_minutes': 0,
            'delay_count': 0,
            'include_weekends': False,
        })
        weekend_cache: dict[str, bool] = {}
        
        for record in records:
            email_key = (record.user_email or '').strip().lower()
            user_id_key = (record.user_id or '').strip().lower()
            name_key = (record.user_name or '').strip().lower()
            if (
                email_key not in allowed_emails
                and user_id_key not in allowed_ids
                and name_key not in allowed_names
            ):
                continue
            
            user_key = record.user_email or record.user_id
            user_data[user_key]['user_key'] = user_key
            user_data[user_key]['user_name'] = record.user_name
            user_data[user_key]['user_email'] = record.user_email
            user_data[user_key]['project'] = canonicalize_label(record.project)
            user_data[user_key]['department'] = canonicalize_label(record.department)
            canonical_team = canonicalize_label(record.team)
            user_data[user_key]['unit'] = canonical_team
            user_data[user_key]['team'] = canonical_team
            include_weekends = user_data[user_key]['include_weekends']
            if not user_data[user_key]['include_weekends']:
                if user_key not in weekend_cache:
                    pf_id = _get_peopleforce_id_for_user(user_key)
                    weekend_cache[user_key] = bool(pf_id and pf_id in SEVEN_DAY_WORK_WEEK_IDS)
                include_weekends = weekend_cache[user_key]
                user_data[user_key]['include_weekends'] = include_weekends
            user_data[user_key]['records'].append(record)
            
            # Skip weekend records for users without 7-day work week
            if not include_weekends and record.record_date.weekday() >= 5:
                continue
            
            # Sum ALL tracked hours (Total from our database)
            user_data[user_key]['total_minutes'] += record.total_minutes or 0
            
            # Sum corrected hours (Total cor.) - ONLY where corrected_total_minutes is NOT None
            # Don't substitute with total_minutes if it's None
            if record.corrected_total_minutes is not None:
                user_data[user_key]['corrected_total_minutes'] += record.corrected_total_minutes
            
            # Count delays > 10 minutes
            if record.minutes_late > 10:
                user_data[user_key]['delay_count'] += 1
        
        # Calculate leave days from our database (not from PeopleForce API)
        leave_data = {}
        for user_key, data in user_data.items():
            vacation_days = 0.0
            day_off_days = 0.0
            sick_days = 0.0
            
            has_seven_day_week = data.get('include_weekends', False)
            
            for record in data['records']:
                if record.status != 'leave':
                    continue
                
                # Skip weekend days for users without 7-day work week
                # 5 = Saturday, 6 = Sunday (weekday() returns 0=Mon, 6=Sun)
                if not has_seven_day_week and record.record_date.weekday() >= 5:
                    continue
                
                # Get leave amount (1.0 for full day, 0.5 for half day)
                leave_amount = record.half_day_amount if record.half_day_amount else 1.0
                
                # Categorize by leave_reason from our database
                leave_reason = (record.leave_reason or '').lower()
                if 'vacation' in leave_reason or 'отпуск' in leave_reason or 'відпустка' in leave_reason:
                    vacation_days += leave_amount
                elif 'sick' in leave_reason or 'больничный' in leave_reason or 'лікарняний' in leave_reason:
                    sick_days += leave_amount
                elif 'day off' in leave_reason or 'выходной' in leave_reason or 'вихідний' in leave_reason or 'за свій рахунок' in leave_reason:
                    day_off_days += leave_amount
                else:
                    # If no specific reason, count as vacation by default
                    vacation_days += leave_amount
            
            leave_data[user_key] = {
                'vacation_days': vacation_days,
                'day_off_days': day_off_days,
                'sick_days': sick_days,
            }
        
        # Build result
        employees = []
        for user_key, data in user_data.items():
            include_weekends = data.get('include_weekends', False)
            plan_days = _count_work_days_in_month(year, month, include_weekends)
            
            leaves = leave_data.get(user_key, {})
            vacation_days = leaves.get('vacation_days', 0)
            day_off_days = leaves.get('day_off_days', 0)
            sick_days = leaves.get('sick_days', 0)
            
            fact_days = plan_days - vacation_days - day_off_days - sick_days
            
            # Calculate minimum hours based on project
            project = data['project'] or ''
            if 'agency' in project.lower() or 'apps' in project.lower():
                min_hours_per_day = 6.5
            elif 'adnetwork' in project.lower() or 'cons' in project.lower():
                min_hours_per_day = 7.0
            else:
                min_hours_per_day = 7.0  # Default
            
            minimum_hours = fact_days * min_hours_per_day

            schedule = (
                get_user_schedule(user_key)
                or get_user_schedule(data['user_name'])
                or {}
            )
            division = canonicalize_label(schedule.get('division_name') or data.get('project', ''))
            department = canonicalize_label(schedule.get('direction_name') or data.get('department', ''))
            unit = canonicalize_label(schedule.get('unit_name') or data.get('unit', ''))
            team = canonicalize_label(schedule.get('team_name') or data.get('team', ''))
            
            # Format hours
            def format_hours(minutes):
                hours = minutes // 60
                mins = minutes % 60
                return f"{hours}:{mins:02d}"
            
            employees.append({
                'user_key': user_key,
                'user_name': data['user_name'],
                'user_email': data['user_email'],
                'division': division,
                'department': department,
                'unit': unit,
                'team': team,
                'plan_days': plan_days,
                'vacation_days': vacation_days,
                'day_off_days': day_off_days,
                'sick_days': sick_days,
                'fact_days': fact_days,
                'minimum_hours': format_hours(int(minimum_hours * 60)),
                'tracked_hours': format_hours(data['total_minutes']),
                'delay_count': data['delay_count'],
                'corrected_hours': format_hours(data['corrected_total_minutes']),
                'notes': '',  # Will be loaded from separate storage
            })
        
        # Sort by user name
        employees.sort(key=lambda x: x['user_name'])
        
        filter_options = {
            'projects': sorted({emp['division'] for emp in employees if emp.get('division')}),
            'departments': sorted({emp['department'] for emp in employees if emp.get('department')}),
            'units': sorted({emp['unit'] for emp in employees if emp.get('unit')}),
            'teams': sorted({emp['team'] for emp in employees if emp.get('team')}),
        }
        
        return jsonify({
            'month': month_str,
            'employees': employees,
            'filters': {
                'options': filter_options
            }
        })
        
    except Exception as e:
        logger.exception('Error generating monthly report')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/week-notes', methods=['GET', 'POST'])
@login_required
def week_notes():
    """
    GET: Load all week notes
    POST: Save week notes for a user.
    
    GET Query params:
        - date_from: YYYY-MM-DD format (optional, for filtering)
        - date_to: YYYY-MM-DD format (optional, for filtering)
    
    POST Request body:
        - user_key: User email/key
        - week_start: YYYY-MM-DD format (Monday of the week)
        - notes: Notes text
    """
    notes_file = os.path.join(current_app.instance_path, 'week_notes.json')
    
    if request.method == 'GET':
        try:
            if not os.path.exists(notes_file):
                return jsonify({'notes': {}})
            
            with open(notes_file, 'r', encoding='utf-8') as f:
                all_notes = json.load(f)
            
            return jsonify({'notes': all_notes})
            
        except Exception as e:
            logger.exception('Error loading week notes')
            return jsonify({'error': str(e)}), 500
    
    # POST - save notes
    if not getattr(current_user, 'is_admin', False) and not getattr(current_user, 'is_control_manager', False):
        return jsonify({'error': 'Forbidden'}), 403
    
    try:
        payload = request.get_json(silent=True) or {}
        user_key = payload.get('user_key', '').strip()
        week_start = payload.get('week_start', '').strip()
        notes = payload.get('notes', '').strip()
        
        if not user_key or not week_start:
            return jsonify({'error': 'user_key and week_start required'}), 400
        
        # Load existing notes
        all_notes = {}
        if os.path.exists(notes_file):
            with open(notes_file, 'r', encoding='utf-8') as f:
                all_notes = json.load(f)
        
        # Create key: user_key_week_start
        note_key = f"{user_key}_{week_start}"
        
        # Update notes
        if notes:
            all_notes[note_key] = notes
        elif note_key in all_notes:
            # Delete if empty
            del all_notes[note_key]
        
        # Save back
        os.makedirs(current_app.instance_path, exist_ok=True)
        with open(notes_file, 'w', encoding='utf-8') as f:
            json.dump(all_notes, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'notes': notes})
        
    except Exception as e:
        logger.exception('Error saving week notes')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/monthly-notes', methods=['GET', 'POST'])
@login_required
def monthly_notes():
    """
    GET: Load all notes for a month
    POST: Save notes for a user in monthly report.
    
    GET Query params:
        - month: YYYY-MM format
    
    POST Request body:
        - user_key: User email/key
        - month: YYYY-MM format
        - notes: Notes text
    """
    notes_file = os.path.join(current_app.instance_path, 'monthly_notes.json')
    
    if request.method == 'GET':
        try:
            month = request.args.get('month', datetime.now().strftime('%Y-%m'))
            
            if not os.path.exists(notes_file):
                return jsonify({'notes': {}})
            
            with open(notes_file, 'r', encoding='utf-8') as f:
                all_notes = json.load(f)
            
            # Filter notes for this month
            month_notes = {}
            for key, value in all_notes.items():
                if key.endswith(f'_{month}'):
                    user_key = key.rsplit('_', 2)[0]  # Remove _YYYY-MM
                    month_notes[user_key] = value
            
            return jsonify({'notes': month_notes})
            
        except Exception as e:
            logger.exception('Error loading monthly notes')
            return jsonify({'error': str(e)}), 500
    
    else:  # POST
        try:
            data = request.get_json()
            user_key = data.get('user_key')
            month = data.get('month')
            notes = data.get('notes', '')
            
            if not user_key or not month:
                return jsonify({'error': 'Missing required fields'}), 400
            
            # Load existing notes
            if os.path.exists(notes_file):
                with open(notes_file, 'r', encoding='utf-8') as f:
                    all_notes = json.load(f)
            else:
                all_notes = {}
            
            # Create key for this user+month
            key = f"{user_key}_{month}"
            all_notes[key] = notes
            
            # Save back
            os.makedirs(os.path.dirname(notes_file), exist_ok=True)
            with open(notes_file, 'w', encoding='utf-8') as f:
                json.dump(all_notes, f, ensure_ascii=False, indent=2)
            
            return jsonify({'success': True})
            
        except Exception as e:
            logger.exception('Error saving monthly notes')
            return jsonify({'error': str(e)}), 500


@api_bp.route('/monthly-report/excel', methods=['GET'])
@login_required
def export_monthly_report_excel():
    """Export monthly report as Excel file matching web design."""
    try:
        # Reuse get_monthly_report logic
        month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
        
        # Call internal function to get data
        with current_app.test_request_context('?' + request.query_string.decode()):
            response = get_monthly_report()
            if response.status_code != 200:
                return response
            data = response.get_json()
        
        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = f"Report {month_str}"
        
        # Define styles
        header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        header_font = Font(bold=True, color='FFFFFF', size=11)
        label_font = Font(bold=True, size=10)
        value_font = Font(size=10)
        small_font = Font(size=9, color='6C757D')
        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Add title
        ws.merge_cells('A1:G1')
        title_cell = ws['A1']
        title_cell.value = f'Monthly Report: {month_str}'
        title_cell.font = Font(bold=True, size=14)
        title_cell.alignment = Alignment(horizontal='center', vertical='center')
        
        # Add data rows (no header row, labels under each user)
        current_row = 3
        
        for emp in data.get('employees', []):
            # User info with badges
            user_name = emp['user_name']
            user_email = emp['user_email']
            badges = []
            if emp.get('division'):
                badges.append(emp['division'])
            if emp.get('department'):
                badges.append(emp['department'])
            if emp.get('unit'):
                badges.append(emp['unit'])
            if emp.get('team'):
                badges.append(emp['team'])
            
            user_info = f"{user_name}\n{user_email}\n{' | '.join(badges)}"
            
            # Add user row
            ws.merge_cells(f'A{current_row}:G{current_row}')
            user_cell = ws[f'A{current_row}']
            user_cell.value = user_info
            user_cell.font = label_font
            user_cell.alignment = Alignment(wrap_text=True, vertical='top')
            user_cell.border = border
            
            current_row += 1
            
            # Add data row
            ws[f'A{current_row}'] = 'Plan Days'
            ws[f'B{current_row}'] = 'Vacation'
            ws[f'C{current_row}'] = 'Day Off'
            ws[f'D{current_row}'] = 'Sick'
            ws[f'E{current_row}'] = 'Fact Days'
            ws[f'F{current_row}'] = 'Notes'
            
            for col in ['A', 'B', 'C', 'D', 'E', 'F']:
                cell = ws[f'{col}{current_row}']
                cell.font = label_font
                cell.border = border
                cell.alignment = Alignment(horizontal='center')
            
            current_row += 1
            
            # Add values
            ws[f'A{current_row}'] = emp['plan_days']
            ws[f'B{current_row}'] = emp['vacation_days']
            ws[f'C{current_row}'] = emp['day_off_days']
            ws[f'D{current_row}'] = emp['sick_days']
            ws[f'E{current_row}'] = emp['fact_days']
            ws[f'F{current_row}'] = emp.get('notes', '')
            
            for col in ['A', 'B', 'C', 'D', 'E', 'F']:
                cell = ws[f'{col}{current_row}']
                cell.font = value_font
                cell.border = border
                cell.alignment = Alignment(horizontal='center', vertical='top')
            
            current_row += 1
            
            # Add sub-labels
            ws[f'A{current_row}'] = f"Minimum per month\n{emp['minimum_hours']}"
            ws[f'B{current_row}'] = f"Tracked Hours\n{emp['tracked_hours']}"
            ws[f'C{current_row}'] = f"Delay >10\n{emp['delay_count']}"
            ws[f'D{current_row}'] = f"Corrected Hours\n{emp['corrected_hours']}"
            
            for col in ['A', 'B', 'C', 'D']:
                cell = ws[f'{col}{current_row}']
                cell.font = small_font
                cell.border = border
                cell.alignment = Alignment(horizontal='center', vertical='top', wrap_text=True)
            
            current_row += 2  # Add spacing
        
        # Adjust column widths
        ws.column_dimensions['A'].width = 25
        ws.column_dimensions['B'].width = 20
        ws.column_dimensions['C'].width = 18
        ws.column_dimensions['D'].width = 18
        ws.column_dimensions['E'].width = 15
        ws.column_dimensions['F'].width = 30
        ws.column_dimensions['G'].width = 15
        
        # Save to BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'monthly_report_{month_str}.xlsx'
        )
        
    except Exception as e:
        logger.exception('Error exporting monthly report to Excel')
        return jsonify({'error': str(e)}), 500


@api_bp.route('/monthly-report/pdf', methods=['GET'])
@login_required
def export_monthly_report_pdf():
    """Export monthly report as PDF file with layout matching web design."""
    try:
        if not SimpleDocTemplate:
            return jsonify({'error': 'PDF export not available'}), 500
        
        # Reuse get_monthly_report logic
        month_str = request.args.get('month', datetime.now().strftime('%Y-%m'))
        
        # Call internal function to get data
        with current_app.test_request_context('?' + request.query_string.decode()):
            response = get_monthly_report()
            if response.status_code != 200:
                return response
            data = response.get_json()
        
        # Create PDF
        output = BytesIO()
        doc = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=30, bottomMargin=20)
        elements = []
        
        # Styles
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        styles = getSampleStyleSheet()
        
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=20,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        user_name_style = ParagraphStyle(
            'UserName',
            parent=styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#1a1a1a'),
            fontName='Helvetica-Bold',
            alignment=TA_LEFT
        )
        
        user_email_style = ParagraphStyle(
            'UserEmail',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#666666'),
            alignment=TA_LEFT
        )
        
        badge_style = ParagraphStyle(
            'Badge',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#0d6efd'),
            alignment=TA_LEFT
        )
        
        label_style = ParagraphStyle(
            'Label',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#666666'),
            alignment=TA_CENTER,
            fontName='Helvetica'
        )
        
        value_style = ParagraphStyle(
            'Value',
            parent=styles['Normal'],
            fontSize=11,
            textColor=colors.HexColor('#1a1a1a'),
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        small_label_style = ParagraphStyle(
            'SmallLabel',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#666666'),
            alignment=TA_CENTER
        )
        
        small_value_style = ParagraphStyle(
            'SmallValue',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#1a1a1a'),
            alignment=TA_CENTER
        )
        
        # Title
        elements.append(Paragraph(f"Monthly Report: {month_str}", title_style))
        elements.append(Spacer(1, 20))
        
        # Process each employee
        for emp in data.get('employees', []):
            # User info section
            user_name = emp['user_name']
            user_email = emp['user_email']
            
            # Build badges
            badges = []
            if emp.get('division'):
                badges.append(emp['division'])
            if emp.get('department'):
                badges.append(emp['department'])
            if emp.get('unit'):
                badges.append(emp['unit'])
            if emp.get('team'):
                badges.append(emp['team'])
            
            # User info table (single row spanning all columns)
            user_info_text = f"<b>{user_name}</b><br/><font size=8 color='#666666'>{user_email}</font>"
            if badges:
                user_info_text += f"<br/><font size=7 color='#0d6efd'>{' | '.join(badges)}</font>"
            
            user_table = Table([[Paragraph(user_info_text, user_name_style)]], colWidths=[750])
            user_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ]))
            elements.append(user_table)
            
            # Data table - labels row
            labels_data = [[
                Paragraph('Plan Days', label_style),
                Paragraph('Vacation', label_style),
                Paragraph('Day Off', label_style),
                Paragraph('Sick', label_style),
                Paragraph('Fact Days', label_style),
                Paragraph('Notes', label_style)
            ]]
            
            # Data table - values row
            notes_text = emp.get('notes', '') or ''
            if len(notes_text) > 40:
                notes_text = notes_text[:37] + '...'
            
            values_data = [[
                Paragraph(str(emp['plan_days']), value_style),
                Paragraph(str(emp['vacation_days']), value_style),
                Paragraph(str(emp['day_off_days']), value_style),
                Paragraph(str(emp['sick_days']), value_style),
                Paragraph(str(emp['fact_days']), value_style),
                Paragraph(notes_text, value_style)
            ]]
            
            # Data table - sub-labels row
            sub_labels_data = [[
                Paragraph(f"Minimum per month<br/>{emp['minimum_hours']}", small_label_style),
                Paragraph(f"Tracked Hours<br/>{emp['tracked_hours']}", small_label_style),
                Paragraph(f"Delay &gt;10<br/>{emp['delay_count']}", small_label_style),
                Paragraph(f"Corrected Hours<br/>{emp['corrected_hours']}", small_label_style),
                Paragraph('', small_label_style),
                Paragraph('', small_label_style)
            ]]
            
            # Combine all data rows
            data_table = Table(labels_data + values_data + sub_labels_data, 
                             colWidths=[125, 125, 125, 125, 125, 125])
            data_table.setStyle(TableStyle([
                # Labels row styling
                ('BACKGROUND', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('VALIGN', (0, 0), (-1, 0), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, 0), 5),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 3),
                
                # Values row styling
                ('BACKGROUND', (0, 1), (-1, 1), colors.white),
                ('ALIGN', (0, 1), (-1, 1), 'CENTER'),
                ('VALIGN', (0, 1), (-1, 1), 'MIDDLE'),
                ('TOPPADDING', (0, 1), (-1, 1), 5),
                ('BOTTOMPADDING', (0, 1), (-1, 1), 5),
                
                # Sub-labels row styling
                ('BACKGROUND', (0, 2), (-1, 2), colors.white),
                ('ALIGN', (0, 2), (-1, 2), 'CENTER'),
                ('VALIGN', (0, 2), (-1, 2), 'TOP'),
                ('TOPPADDING', (0, 2), (-1, 2), 3),
                ('BOTTOMPADDING', (0, 2), (-1, 2), 5),
                
                # All borders
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#dee2e6')),
            ]))
            elements.append(data_table)
            
            # Add spacing between employees
            elements.append(Spacer(1, 15))
        
        # Build PDF
        doc.build(elements)
        
        output.seek(0)
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'monthly_report_{month_str}.pdf'
        )
        
    except Exception as e:
        logger.exception('Error exporting monthly report to PDF')
        return jsonify({'error': str(e)}), 500
