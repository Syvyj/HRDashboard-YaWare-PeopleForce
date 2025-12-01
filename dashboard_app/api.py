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

from flask import Blueprint, request, jsonify, send_file, abort, current_app, g
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash
from sqlalchemy import or_
from openpyxl import Workbook
from openpyxl.styles import Alignment, PatternFill, Font, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.cell.cell import MergedCell
from .extensions import db
from .models import AttendanceRecord, User, AdminAuditLog, EmployeePreset
from .user_data import get_user_schedule, load_user_schedules, clear_user_schedule_cache
from tracker_alert.services import user_manager as schedule_user_manager
from tracker_alert.services.schedule_utils import (
    set_manual_override,
    clear_manual_override,
    has_manual_override,
)
from tracker_alert.services.attendance_monitor import AttendanceMonitor
from tracker_alert.client.peopleforce_api import PeopleForceClient
from tracker_alert.client.yaware_v2_api import YaWareV2Client
from tracker_alert.services.control_manager import auto_assign_control_manager
from tracker_alert.services.dashboard_report import DashboardReportService
from dashboard_app.lateness_service import collect_lateness_for_date, LatenessCollectorError
from dashboard_app.models import LatenessRecord
from dashboard_app.constants import SEVEN_DAY_WORK_WEEK_IDS
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


def _parse_manager_ids(manager_filter: str | None) -> list[int]:
    if not manager_filter:
        return []
    result: list[int] = []
    for value in manager_filter.split(','):
        value = value.strip()
        if not value:
            continue
        try:
            result.append(int(value))
        except ValueError:
            continue
    return result


def _can_manage_presets(user: User) -> bool:
    return bool(getattr(user, 'is_admin', False) or getattr(user, 'is_control_manager', False))


def _can_view_all_presets(user: User) -> bool:
    if getattr(user, 'is_admin', False):
        return True
    if not getattr(user, 'is_control_manager', False):
        return False
    return _parse_manager_ids(getattr(user, 'manager_filter', None)) == [3]


def _include_archived_requested(default: bool = False) -> bool:
    value = (request.args.get('include_archived') or '').strip().lower()
    if not value:
        return default
    return value in {'1', 'true', 'yes', 'on'}


_dashboard_report_service: DashboardReportService | None = None


def _get_dashboard_report_service() -> DashboardReportService:
    global _dashboard_report_service
    if _dashboard_report_service is None:
        db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI')
        _dashboard_report_service = DashboardReportService(db_url)
    return _dashboard_report_service


def _serialize_attendance_status(status) -> dict:
    user = status.user
    return {
        'name': user.name,
        'email': user.email,
        'project': user.project,
        'department': user.department,
        'team': user.team,
        'location': user.location,
        'scheduled_start': status.expected_time,
        'actual_start': status.actual_time,
        'minutes_late': status.minutes_late,
        'status': status.status,
        'control_manager': user.control_manager,
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

def _normalize_plan_start(value: str | None) -> str:
    if not value:
        return ''
    text = str(value).strip()
    if not text:
        return ''
    parts = text.split(':')
    try:
        if len(parts) == 2:
            hour = int(parts[0])
            minute = int(parts[1])
            return f"{hour:02d}:{minute:02d}"
        if len(parts) >= 3:
            hour = int(parts[0])
            minute = int(parts[1])
            return f"{hour:02d}:{minute:02d}"
    except ValueError:
        return ''
    return text

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
        if _is_ignored_person(name, email) or _is_archived_person(name, email):
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
        if _is_ignored_person(full_name, email) or _is_archived_person(full_name, email):
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
        if _is_ignored_person(full_name, email) or _is_archived_person(full_name, email):
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
        if yaware_error is None and not entry['in_yaware'] and not _is_ignored_person(entry['name'], entry['email']) and not _is_archived_person(entry['name'], entry['email']):
            missing_yaware.append(_humanize_entry(entry['name'], entry['email'], entry['user_id']))
        if peopleforce_error is None and not entry['in_peopleforce'] and not _is_ignored_person(entry['name'], entry['email']) and not _is_archived_person(entry['name'], entry['email']):
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
        'archived': bool(info.get('archived')),
        'last_date': '',
    }


def _gather_schedule_users(search: str | None, ignored_only: bool = False, include_archived: bool = False) -> list[dict]:
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
        archived = bool(info.get('archived'))
        if ignored_only and not ignored:
            continue
        if not ignored_only and ignored:
            continue
        if not ignored_only and not include_archived and archived:
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
    
    # Get ignored/archived status from user_schedule or schedule parameter
    ignored_status = False
    archived_status = False
    if schedule and isinstance(schedule, dict):
        ignored_status = schedule.get('ignored', False)
        archived_status = schedule.get('archived', False)
    else:
        ignored_status = user_schedule.get('ignored', False)
        archived_status = user_schedule.get('archived', False)
    
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
        'archived': archived_status,
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
    week_offset = request.args.get('week_offset', type=int, default=0)

    if single_date:
        query = query.filter(AttendanceRecord.record_date == single_date)
        g.week_start = None  # No week context for single date
    else:
        # Якщо дати не задані - показуємо тиждень з урахуванням offset
        if not date_from and not date_to:
            today = date.today()
            # Знаходимо понеділок поточного тижня
            week_start = today - timedelta(days=today.weekday())  # 0 = понеділок
            # Додаємо offset (в тижнях)
            week_start = week_start + timedelta(weeks=week_offset)
            # П'ятниця = понеділок + 4 дні (для 5/2)
            # Для відображення включаємо також week_total записи (можуть бути в неділю для 24/7)
            week_end = week_start + timedelta(days=6)  # Неділя
            date_from = week_start
            date_to = week_end
            # Store week_start in flask.g for use in _build_items
            g.week_start = week_start
        else:
            g.week_start = None  # Custom date range, no week context
        
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


def _sync_plan_start_for_date(target_date: date) -> tuple[int, int]:
    """Update scheduled_start for a given date using YaWare monitoring endpoint."""
    records = AttendanceRecord.query.filter_by(record_date=target_date).all()
    if not records:
        return 0, 0

    user_ids = {str(rec.user_id).strip() for rec in records if rec.user_id}
    user_ids = {uid for uid in user_ids if uid}
    if not user_ids:
        return 0, len(records)

    client = YaWareV2Client()
    try:
        payload = client.get_begin_end_monitoring_by_employees(list(user_ids)) or []
    except Exception as exc:
        logger.error("Failed to sync plan start from YaWare for %s: %s", target_date, exc)
        raise

    day_index = target_date.weekday() + 1  # 1..7
    start_by_id: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        uid = str(item.get('user_id') or '').strip()
        if not uid:
            continue
        for day_info in item.get('data') or []:
            if str(day_info.get('day')) != str(day_index):
                continue
            start_val = _normalize_plan_start(day_info.get('start_monitoring'))
            if start_val:
                start_by_id[uid] = start_val
            break

    updated = 0
    for rec in records:
        if getattr(rec, 'manual_scheduled_start', False):
            continue
        new_start = start_by_id.get(str(rec.user_id).strip())
        if not new_start:
            continue
        current = _normalize_plan_start(rec.scheduled_start)
        if new_start != current:
            rec.scheduled_start = new_start
            updated += 1

    if updated:
        db.session.commit()
    return updated, len(records)


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
        week_total_from_db = None

        for rec in recs:
            # Check if this is a week_total record from database
            if rec.record_type == 'week_total':
                week_total_from_db = rec
                continue
            
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
                'notes': rec.notes,
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
        
        # Use week_total from DB if exists, otherwise use calculated totals
        if week_total_from_db:
            week_total_data = {
                'non_productive_minutes': week_total_from_db.non_productive_minutes or 0,
                'non_productive_display': _minutes_to_str(week_total_from_db.non_productive_minutes or 0),
                'non_productive_hm': _minutes_to_hm(week_total_from_db.non_productive_minutes or 0),
                'not_categorized_minutes': week_total_from_db.not_categorized_minutes or 0,
                'not_categorized_display': _minutes_to_str(week_total_from_db.not_categorized_minutes or 0),
                'not_categorized_hm': _minutes_to_hm(week_total_from_db.not_categorized_minutes or 0),
                'productive_minutes': week_total_from_db.productive_minutes or 0,
                'productive_display': _minutes_to_str(week_total_from_db.productive_minutes or 0),
                'productive_hm': _minutes_to_hm(week_total_from_db.productive_minutes or 0),
                'total_minutes': week_total_from_db.total_minutes or 0,
                'total_display': _minutes_to_str(week_total_from_db.total_minutes or 0),
                'total_hm': _minutes_to_hm(week_total_from_db.total_minutes or 0),
                'corrected_total_minutes': week_total_from_db.corrected_total_minutes,
                'corrected_total_display': _minutes_to_str(week_total_from_db.corrected_total_minutes) if week_total_from_db.corrected_total_minutes is not None else '',
                'corrected_total_hm': _minutes_to_hm(week_total_from_db.corrected_total_minutes) if week_total_from_db.corrected_total_minutes is not None else '',
                'notes': week_total_from_db.notes or week_note,
                'from_db': True
            }
        else:
            week_total_data = {
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
                'notes': week_note,
                'from_db': False
            }

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
            'week_total': week_total_data,
            'week_start': g.get('week_start').isoformat() if g.get('week_start') else None
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
    # Filter only daily records (exclude week_total)
    query = _apply_filters(AttendanceRecord.query)
    query = query.filter(or_(
        AttendanceRecord.record_type == 'daily',
        AttendanceRecord.record_type.is_(None)  # для старих записів без record_type
    ))
    records = query.order_by(AttendanceRecord.user_name.asc(), AttendanceRecord.record_date.asc()).all()
    
    include_archived = _include_archived_requested(False)
    filtered_by_status: list[AttendanceRecord] = []
    for rec in records:
        if _is_ignored_person(rec.user_name, rec.user_email, rec.user_id):
            continue
        if not include_archived and _is_archived_person(rec.user_name, rec.user_email, rec.user_id):
            continue
        filtered_by_status.append(rec)
    records = filtered_by_status
    
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
    
    # Фільтруємо вихідні дні для користувачів без 7-денного робочого тижня
    filtered_records = []
    weekend_cache = {}
    for record in records:
        user_key = record.user_email or record.user_id
        if user_key not in weekend_cache:
            pf_id = _get_peopleforce_id_for_user(user_key)
            weekend_cache[user_key] = bool(pf_id and pf_id in SEVEN_DAY_WORK_WEEK_IDS)
        
        # Якщо користувач не має 7-денного тижня і це вихідний - пропускаємо
        if not weekend_cache[user_key] and record.record_date.weekday() >= 5:
            continue
        
        filtered_records.append(record)
    
    records = filtered_records
    
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


@api_bp.route('/admin/sync/plan-start', methods=['POST'])
@login_required
def admin_sync_plan_start():
    """Manual sync of Plan start (scheduled_start) from YaWare monitoring endpoint."""
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    date_str = (payload.get('date') or request.args.get('date') or '').strip()
    target_date = _parse_date(date_str)
    if not target_date:
        target_date = date.today() - timedelta(days=1)

    try:
        updated, total = _sync_plan_start_for_date(target_date)
    except Exception as exc:
        logger.error("Plan start sync failed for %s: %s", target_date, exc, exc_info=True)
        return jsonify({'error': f'Plan start sync failed: {str(exc)}'}), 500

    try:
        _log_admin_action('sync_plan_start', {
            'date': target_date.isoformat(),
            'updated': updated,
            'total_records': total
        })
        db.session.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to log plan start sync: %s", exc)

    return jsonify({
        'status': 'ok',
        'date': target_date.isoformat(),
        'updated': updated,
        'total_records': total
    })


@api_bp.route('/admin/employees', methods=['POST'])
@login_required
def admin_create_employee():
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    email_raw = (payload.get('email') or '').strip()
    email = email_raw.lower()
    
    logger.info(f"Creating employee: name='{name}', email='{email}', ignored={payload.get('ignored')}, archived={payload.get('archived')}")
    
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
    
    # Handle ignored/archived flags
    ignored = payload.get('ignored', False)
    if ignored:
        entry['ignored'] = True
    if payload.get('archived'):
        entry['archived'] = True
    
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
    include_archived = _include_archived_requested(False)
    project_filters = request.args.getlist('project')
    department_filters = request.args.getlist('department')
    unit_filters = request.args.getlist('unit')
    team_filters = request.args.getlist('team')
    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = max(min(int(request.args.get('per_page', 25) or 25), 100), 1)

    if ignored_only:
        records = _gather_schedule_users(search, ignored_only=True, include_archived=True)
        filter_options = {}
    else:
        records = _gather_schedule_users(search, ignored_only=False, include_archived=include_archived)
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
        'archived': 'archived',
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

    if 'archived' in payload:
        schedule_updates['archived'] = bool(payload.get('archived'))

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


@api_bp.route('/admin/employees/<path:user_key>/adapt', methods=['POST'])
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
    
    exclude_247 = request.args.get('exclude_247', 'false').lower() == 'true'
    
    # Видаляємо записи за цю дату
    query = AttendanceRecord.query.filter_by(record_date=target_date)
    
    if exclude_247:
        # Фільтруємо, щоб виключити користувачів з графіком 24/7
        # Отримуємо internal_id користувачів з графіком 24/7
        schedules = load_user_schedules()
        seven_day_internal_ids = set()
        for user_name, info in schedules.items():
            if isinstance(info, dict):
                pf_id = info.get('peopleforce_id')
                if pf_id and int(pf_id) in SEVEN_DAY_WORK_WEEK_IDS:
                    internal_id = info.get('internal_id')
                    if internal_id:
                        seven_day_internal_ids.add(int(internal_id))
        
        records_to_delete = []
        for record in query.all():
            # Видаляємо якщо internal_user_id НЕ в списку 24/7 або якщо internal_user_id == None
            if record.internal_user_id is None or record.internal_user_id not in seven_day_internal_ids:
                records_to_delete.append(record)
        
        deleted_count = len(records_to_delete)
        for record in records_to_delete:
            db.session.delete(record)
    else:
        # Видаляємо всі записи
        deleted_count = query.delete()
    
    _log_admin_action('delete_attendance_date', {
        'date': date_str,
        'deleted_count': deleted_count,
        'exclude_247': exclude_247
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
        if isinstance(info, dict) and info.get('control_manager') not in (None, '')
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
    
    # Separate daily records from week_total - EXACTLY like _build_items()
    daily_records = []
    week_total_from_db = None
    
    for rec in filtered:
        # Check if this is a week_total record from database
        if rec.record_type == 'week_total':
            week_total_from_db = rec
            continue
        daily_records.append(rec)
    
    # Don't filter weekends or limit records when date range is specified
    if not start and not end:
        daily_records = [rec for rec in daily_records if rec.record_date.weekday() < 5][:5]
    
    # Sort daily records by date ASCENDING (Monday -> Friday)
    daily_records.sort(key=lambda rec: rec.record_date, reverse=False)
    result = [_serialize_attendance_record(rec) for rec in daily_records]
    
    # Add week_total: COPY EXACT LOGIC FROM _build_items()
    if start and end and daily_records:
        # Calculate totals from daily records
        total_non = sum(rec.non_productive_minutes or 0 for rec in daily_records)
        total_not = sum(rec.not_categorized_minutes or 0 for rec in daily_records)
        total_prod = sum(rec.productive_minutes or 0 for rec in daily_records)
        total_total = sum((rec.not_categorized_minutes or 0) + (rec.productive_minutes or 0) for rec in daily_records)
        total_corrected = sum(rec.corrected_total_minutes or 0 for rec in daily_records if rec.corrected_total_minutes is not None)
        has_corrected = any(rec.corrected_total_minutes is not None for rec in daily_records)
        
        # Get week notes - same as _build_items()
        week_notes_file = os.path.join(current_app.instance_path, 'week_notes.json')
        week_notes = {}
        if os.path.exists(week_notes_file):
            try:
                with open(week_notes_file, 'r', encoding='utf-8') as f:
                    week_notes = json.load(f)
            except:
                pass
        
        # Get week start
        week_start = recs[0].record_date
        days_since_monday = week_start.weekday()
        week_start = week_start - timedelta(days=days_since_monday)
        week_start_str = week_start.isoformat()
        
        # Get week note
        first_rec = daily_records[0]
        user_key = first_rec.user_email or first_rec.user_id or first_rec.user_name
        note_key = f"{user_key}_{week_start_str}"
        week_note = week_notes.get(note_key, '')
        
        # Use week_total from DB if exists, otherwise use calculated totals - EXACT SAME LOGIC
        if week_total_from_db:
            week_total_data = {
                'non_productive_minutes': week_total_from_db.non_productive_minutes or 0,
                'non_productive_display': _minutes_to_str(week_total_from_db.non_productive_minutes or 0),
                'non_productive_hm': _minutes_to_hm(week_total_from_db.non_productive_minutes or 0),
                'not_categorized_minutes': week_total_from_db.not_categorized_minutes or 0,
                'not_categorized_display': _minutes_to_str(week_total_from_db.not_categorized_minutes or 0),
                'not_categorized_hm': _minutes_to_hm(week_total_from_db.not_categorized_minutes or 0),
                'productive_minutes': week_total_from_db.productive_minutes or 0,
                'productive_display': _minutes_to_str(week_total_from_db.productive_minutes or 0),
                'productive_hm': _minutes_to_hm(week_total_from_db.productive_minutes or 0),
                'total_minutes': week_total_from_db.total_minutes or 0,
                'total_display': _minutes_to_str(week_total_from_db.total_minutes or 0),
                'total_hm': _minutes_to_hm(week_total_from_db.total_minutes or 0),
                'corrected_total_minutes': week_total_from_db.corrected_total_minutes,
                'corrected_total_display': _minutes_to_str(week_total_from_db.corrected_total_minutes) if week_total_from_db.corrected_total_minutes is not None else '',
                'corrected_total_hm': _minutes_to_hm(week_total_from_db.corrected_total_minutes) if week_total_from_db.corrected_total_minutes is not None else '',
                'notes': week_total_from_db.notes or week_note,
                'from_db': True
            }
        else:
            week_total_data = {
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
                'notes': week_note,
                'from_db': False
            }

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
            'week_total': week_total_data,
            'week_start': g.get('week_start').isoformat() if g.get('week_start') else None
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
    # Filter only daily records (exclude week_total)
    query = _apply_filters(AttendanceRecord.query)
    query = query.filter(or_(
        AttendanceRecord.record_type == 'daily',
        AttendanceRecord.record_type.is_(None)  # для старих записів без record_type
    ))
    records = query.order_by(AttendanceRecord.user_name.asc(), AttendanceRecord.record_date.asc()).all()
    
    include_archived = _include_archived_requested(False)
    filtered_by_status: list[AttendanceRecord] = []
    for rec in records:
        if _is_ignored_person(rec.user_name, rec.user_email, rec.user_id):
            continue
        if not include_archived and _is_archived_person(rec.user_name, rec.user_email, rec.user_id):
            continue
        filtered_by_status.append(rec)
    records = filtered_by_status
    
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
    
    # Фільтруємо вихідні дні для користувачів без 7-денного робочого тижня
    filtered_records = []
    weekend_cache = {}
    for record in records:
        user_key = record.user_email or record.user_id
        if user_key not in weekend_cache:
            pf_id = _get_peopleforce_id_for_user(user_key)
            weekend_cache[user_key] = bool(pf_id and pf_id in SEVEN_DAY_WORK_WEEK_IDS)
        
        # Якщо користувач не має 7-денного тижня і це вихідний - пропускаємо
        if not weekend_cache[user_key] and record.record_date.weekday() >= 5:
            continue
        
        filtered_records.append(record)
    
    records = filtered_records
    
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


@api_bp.route('/admin/sync/plan-start', methods=['POST'])
@login_required
def admin_sync_plan_start():
    """Manual sync of Plan start (scheduled_start) from YaWare monitoring endpoint."""
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    date_str = (payload.get('date') or request.args.get('date') or '').strip()
    target_date = _parse_date(date_str)
    if not target_date:
        target_date = date.today() - timedelta(days=1)

    try:
        updated, total = _sync_plan_start_for_date(target_date)
    except Exception as exc:
        logger.error("Plan start sync failed for %s: %s", target_date, exc, exc_info=True)
        return jsonify({'error': f'Plan start sync failed: {str(exc)}'}), 500

    try:
        _log_admin_action('sync_plan_start', {
            'date': target_date.isoformat(),
            'updated': updated,
            'total_records': total
        })
        db.session.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to log plan start sync: %s", exc)

    return jsonify({
        'status': 'ok',
        'date': target_date.isoformat(),
        'updated': updated,
        'total_records': total
    })


@api_bp.route('/admin/employees', methods=['POST'])
@login_required
def admin_create_employee():
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    email_raw = (payload.get('email') or '').strip()
    email = email_raw.lower()
    
    logger.info(f"Creating employee: name='{name}', email='{email}', ignored={payload.get('ignored')}, archived={payload.get('archived')}")
    
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
    
    # Handle ignored/archived flags
    ignored = payload.get('ignored', False)
    if ignored:
        entry['ignored'] = True
    if payload.get('archived'):
        entry['archived'] = True
    
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
    include_archived = _include_archived_requested(False)
    project_filters = request.args.getlist('project')
    department_filters = request.args.getlist('department')
    unit_filters = request.args.getlist('unit')
    team_filters = request.args.getlist('team')
    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = max(min(int(request.args.get('per_page', 25) or 25), 100), 1)

    if ignored_only:
        records = _gather_schedule_users(search, ignored_only=True, include_archived=True)
        filter_options = {}
    else:
        records = _gather_schedule_users(search, ignored_only=False, include_archived=include_archived)
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
        'archived': 'archived',
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

    if 'archived' in payload:
        schedule_updates['archived'] = bool(payload.get('archived'))

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


@api_bp.route('/admin/employees/<path:user_key>/adapt', methods=['POST'])
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
    
    exclude_247 = request.args.get('exclude_247', 'false').lower() == 'true'
    
    # Видаляємо записи за цю дату
    query = AttendanceRecord.query.filter_by(record_date=target_date)
    
    if exclude_247:
        # Фільтруємо, щоб виключити користувачів з графіком 24/7
        # Отримуємо internal_id користувачів з графіком 24/7
        schedules = load_user_schedules()
        seven_day_internal_ids = set()
        for user_name, info in schedules.items():
            if isinstance(info, dict):
                pf_id = info.get('peopleforce_id')
                if pf_id and int(pf_id) in SEVEN_DAY_WORK_WEEK_IDS:
                    internal_id = info.get('internal_id')
                    if internal_id:
                        seven_day_internal_ids.add(int(internal_id))
        
        records_to_delete = []
        for record in query.all():
            # Видаляємо якщо internal_user_id НЕ в списку 24/7 або якщо internal_user_id == None
            if record.internal_user_id is None or record.internal_user_id not in seven_day_internal_ids:
                records_to_delete.append(record)
        
        deleted_count = len(records_to_delete)
        for record in records_to_delete:
            db.session.delete(record)
    else:
        # Видаляємо всі записи
        deleted_count = query.delete()
    
    _log_admin_action('delete_attendance_date', {
        'date': date_str,
        'deleted_count': deleted_count,
        'exclude_247': exclude_247
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
        if isinstance(info, dict) and info.get('control_manager') not in (None, '')
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
    
    # Separate daily records from week_total - EXACTLY like _build_items()
    daily_records = []
    week_total_from_db = None
    
    for rec in filtered:
        # Check if this is a week_total record from database
        if rec.record_type == 'week_total':
            week_total_from_db = rec
            continue
        daily_records.append(rec)
    
    # Don't filter weekends or limit records when date range is specified
    if not start and not end:
        daily_records = [rec for rec in daily_records if rec.record_date.weekday() < 5][:5]
    
    # Sort daily records by date ASCENDING (Monday -> Friday)
    daily_records.sort(key=lambda rec: rec.record_date, reverse=False)
    result = [_serialize_attendance_record(rec) for rec in daily_records]
    
    # Add week_total: COPY EXACT LOGIC FROM _build_items()
    if start and end and daily_records:
        # Calculate totals from daily records
        total_non = sum(rec.non_productive_minutes or 0 for rec in daily_records)
        total_not = sum(rec.not_categorized_minutes or 0 for rec in daily_records)
        total_prod = sum(rec.productive_minutes or 0 for rec in daily_records)
        total_total = sum((rec.not_categorized_minutes or 0) + (rec.productive_minutes or 0) for rec in daily_records)
        total_corrected = sum(rec.corrected_total_minutes or 0 for rec in daily_records if rec.corrected_total_minutes is not None)
        has_corrected = any(rec.corrected_total_minutes is not None for rec in daily_records)
        
        # Get week notes - same as _build_items()
        week_notes_file = os.path.join(current_app.instance_path, 'week_notes.json')
        week_notes = {}
        if os.path.exists(week_notes_file):
            try:
                with open(week_notes_file, 'r', encoding='utf-8') as f:
                    week_notes = json.load(f)
            except:
                pass
        
        # Get week start
        week_start = recs[0].record_date
        days_since_monday = week_start.weekday()
        week_start = week_start - timedelta(days=days_since_monday)
        week_start_str = week_start.isoformat()
        
        # Get week note
        first_rec = daily_records[0]
        user_key = first_rec.user_email or first_rec.user_id or first_rec.user_name
        note_key = f"{user_key}_{week_start_str}"
        week_note = week_notes.get(note_key, '')
        
        # Use week_total from DB if exists, otherwise use calculated totals - EXACT SAME LOGIC
        if week_total_from_db:
            week_total_data = {
                'non_productive_minutes': week_total_from_db.non_productive_minutes or 0,
                'non_productive_display': _minutes_to_str(week_total_from_db.non_productive_minutes or 0),
                'non_productive_hm': _minutes_to_hm(week_total_from_db.non_productive_minutes or 0),
                'not_categorized_minutes': week_total_from_db.not_categorized_minutes or 0,
                'not_categorized_display': _minutes_to_str(week_total_from_db.not_categorized_minutes or 0),
                'not_categorized_hm': _minutes_to_hm(week_total_from_db.not_categorized_minutes or 0),
                'productive_minutes': week_total_from_db.productive_minutes or 0,
                'productive_display': _minutes_to_str(week_total_from_db.productive_minutes or 0),
                'productive_hm': _minutes_to_hm(week_total_from_db.productive_minutes or 0),
                'total_minutes': week_total_from_db.total_minutes or 0,
                'total_display': _minutes_to_str(week_total_from_db.total_minutes or 0),
                'total_hm': _minutes_to_hm(week_total_from_db.total_minutes or 0),
                'corrected_total_minutes': week_total_from_db.corrected_total_minutes,
                'corrected_total_display': _minutes_to_str(week_total_from_db.corrected_total_minutes) if week_total_from_db.corrected_total_minutes is not None else '',
                'corrected_total_hm': _minutes_to_hm(week_total_from_db.corrected_total_minutes) if week_total_from_db.corrected_total_minutes is not None else '',
                'notes': week_total_from_db.notes or week_note,
                'from_db': True
            }
        else:
            week_total_data = {
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
                'notes': week_note,
                'from_db': False
            }

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
            'week_total': week_total_data,
            'week_start': g.get('week_start').isoformat() if g.get('week_start') else None
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
    # Filter only daily records (exclude week_total)
    query = _apply_filters(AttendanceRecord.query)
    query = query.filter(or_(
        AttendanceRecord.record_type == 'daily',
        AttendanceRecord.record_type.is_(None)  # для старих записів без record_type
    ))
    records = query.order_by(AttendanceRecord.user_name.asc(), AttendanceRecord.record_date.asc()).all()
    
    include_archived = _include_archived_requested(False)
    filtered_by_status: list[AttendanceRecord] = []
    for rec in records:
        if _is_ignored_person(rec.user_name, rec.user_email, rec.user_id):
            continue
        if not include_archived and _is_archived_person(rec.user_name, rec.user_email, rec.user_id):
            continue
        filtered_by_status.append(rec)
    records = filtered_by_status
    
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
    
    # Фільтруємо вихідні дні для користувачів без 7-денного робочого тижня
    filtered_records = []
    weekend_cache = {}
    for record in records:
        user_key = record.user_email or record.user_id
        if user_key not in weekend_cache:
            pf_id = _get_peopleforce_id_for_user(user_key)
            weekend_cache[user_key] = bool(pf_id and pf_id in SEVEN_DAY_WORK_WEEK_IDS)
        
        # Якщо користувач не має 7-денного тижня і це вихідний - пропускаємо
        if not weekend_cache[user_key] and record.record_date.weekday() >= 5:
            continue
        
        filtered_records.append(record)
    
    records = filtered_records
    
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


@api_bp.route('/admin/sync/plan-start', methods=['POST'])
@login_required
def admin_sync_plan_start():
    """Manual sync of Plan start (scheduled_start) from YaWare monitoring endpoint."""
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    date_str = (payload.get('date') or request.args.get('date') or '').strip()
    target_date = _parse_date(date_str)
    if not target_date:
        target_date = date.today() - timedelta(days=1)

    try:
        updated, total = _sync_plan_start_for_date(target_date)
    except Exception as exc:
        logger.error("Plan start sync failed for %s: %s", target_date, exc, exc_info=True)
        return jsonify({'error': f'Plan start sync failed: {str(exc)}'}), 500

    try:
        _log_admin_action('sync_plan_start', {
            'date': target_date.isoformat(),
            'updated': updated,
            'total_records': total
        })
        db.session.commit()
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to log plan start sync: %s", exc)

    return jsonify({
        'status': 'ok',
        'date': target_date.isoformat(),
        'updated': updated,
        'total_records': total
    })


@api_bp.route('/admin/employees', methods=['POST'])
@login_required
def admin_create_employee():
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    email_raw = (payload.get('email') or '').strip()
    email = email_raw.lower()
    
    logger.info(f"Creating employee: name='{name}', email='{email}', ignored={payload.get('ignored')}, archived={payload.get('archived')}")
    
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
    
    # Handle ignored/archived flags
    ignored = payload.get('ignored', False)
    if ignored:
        entry['ignored'] = True
    if payload.get('archived'):
        entry['archived'] = True
    
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
    include_archived = _include_archived_requested(False)
    project_filters = request.args.getlist('project')
    department_filters = request.args.getlist('department')
    unit_filters = request.args.getlist('unit')
    team_filters = request.args.getlist('team')
    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = max(min(int(request.args.get('per_page', 25) or 25), 100), 1)

    if ignored_only:
        records = _gather_schedule_users(search, ignored_only=True, include_archived=True)
        filter_options = {}
    else:
        records = _gather_schedule_users(search, ignored_only=False, include_archived=include_archived)
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
    users = data.get('users', {}) if isinstance(data, dict) :
