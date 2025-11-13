from __future__ import annotations

import os
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
)
from tracker_alert.services.attendance_monitor import AttendanceMonitor
from tracker_alert.client.peopleforce_api import PeopleForceClient

logger = logging.getLogger(__name__)
from tracker_alert.client.yaware_v2_api import YaWareV2Client
from tasks.update_attendance import update_for_date

try:
    from reportlab.lib import colors  # type: ignore[import]
    from reportlab.lib.pagesizes import A4  # type: ignore[import]
    from reportlab.lib.units import mm  # type: ignore[import]
    from reportlab.pdfbase import pdfmetrics  # type: ignore[import]
    from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import]
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle, Paragraph  # type: ignore[import]
    from reportlab.lib.styles import ParagraphStyle  # type: ignore[import]
except ImportError:  # pragma: no cover
    colors = A4 = mm = None
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


_MANUAL_PROTECTED_FIELDS = {'start_time', 'project', 'department', 'team', 'location'}


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
    """Lazy import to avoid circular dependencies."""
    try:
        module = import_module('dashboard_app.tasks')
        return getattr(module, 'SCHEDULER', None)
    except Exception:
        return None


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

PROJECT_NORMALIZATION: dict[str, str] = {
    'ad network': 'Ad Network',
    'consulting': 'Consulting',
}

HIERARCHY_PATHS: tuple[tuple[str, ...], ...] = (
    ('Ad Network',),
    ('Ad Network', 'Analyst'),
    ('Ad Network', 'CPA'),
    ('Ad Network', 'CPA', 'BizDev СPA'),
    ('Ad Network', 'CPA', 'Gambling team'),
    ('Ad Network', 'CPA', 'MB EVA'),
    ('Ad Network', 'Demand department'),
    ('Ad Network', 'Demand department', 'Account Team (DD)'),
    ('Ad Network', 'Demand department', 'Hot team (DD)'),
    ('Ad Network', 'Marketing'),
    ('Ad Network', 'Moderation'),
    ('Ad Network', 'Product team'),
    ('Ad Network', 'R&D'),
    ('Ad Network', 'RTB'),
    ('Ad Network', 'Support'),
    ('Ad Network', 'Support team'),
    ('Ad Network', 'Support', 'Support team'),
    ('Ad Network', 'Traffic'),
    ('Ad Network', 'Traffic', 'Account Team'),
    ('Ad Network', 'Traffic', 'Bizdev team 1'),
    ('Ad Network', 'Traffic', 'BizDev team 2'),
    ('Agency',),
    ('Agency', 'Creative'),
    ('Agency', 'FB MB'),
    ('Agency', 'FB MB', 'FB - MB (Anna)'),
    ('Agency', 'FB MB', 'FB - MB (Mykyta)'),
    ('Agency', 'FB MB', 'Klimchenya Valery'),
    ('Agency', 'Native Anton'),
    ('Agency', 'Native Anton', 'Native (Hlib)'),
    ('Agency', 'Native Anton', 'Tik Tok (Iryna)'),
    ('Agency', 'Tech'),
    ('APPs',),
    ('APPs', 'iOS team'),
    ('APPs', 'iOS team', 'iOS team'),
    ('APPs', 'Mediabuy team'),
    ('APPs', 'Mediabuy team', 'Mediabuy team'),
    ('Consulting',),
    ('Consulting', 'Administration'),
    ('Consulting', 'CBDO'),
    ('Consulting', 'Consulting Alla Kokosha'),
    ('Consulting', 'Consulting Marcikute Ilona'),
    ('Consulting', 'Consulting Maryia Harauskaya'),
    ('Consulting', 'Control'),
    ('Consulting', 'Control', 'Consulting-Control-Serdiuk Alina'),
    ('Consulting', 'Control', 'Control-Kryvytska Olena'),
    ('Consulting', 'Finance'),
    ('Consulting', 'HR Department'),
    ('Consulting', 'HR Department', 'C&B'),
    ('Consulting', 'HR Department', 'C&B', 'C&B Dankova Tetiana'),
    ('Consulting', 'HR Department', 'C&B', 'C&B Ilona Marcinkute'),
    ('Consulting', 'HR Department', 'HR'),
    ('Consulting', 'HR Department', 'HRBP'),
    ('Consulting', 'HR Department', 'L&D'),
    ('Consulting', 'HR Department', 'Recruitment'),
    ('Consulting', 'Legal'),
    ('Consulting', 'Operation Control'),
)

DEPARTMENT_TO_PROJECT: dict[str, tuple[str, str]] = {}
TEAM_TO_INFO: dict[str, tuple[str, str, str]] = {}

for path in HIERARCHY_PATHS:
    if not path:
        continue
    project = path[0].strip()
    if len(path) >= 2:
        department = path[1].strip() if len(path) == 2 else path[-2].strip()
        key = department.lower()
        if key and key not in DEPARTMENT_TO_PROJECT:
            DEPARTMENT_TO_PROJECT[key] = (project, department)
    if len(path) >= 3:
        team = path[-1].strip()
        department_for_team = path[-2].strip()
        team_key = team.lower()
        if team_key and team_key not in TEAM_TO_INFO:
            TEAM_TO_INFO[team_key] = (project, department_for_team, team)


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _is_synced_employee(user: User) -> bool:
    if not user or user.is_admin:
        return False
    names, emails, ids = _schedule_identity_sets()
    email = (user.email or '').strip().lower()
    if email and email in emails:
        return True
    name = (user.name or '').strip().lower()
    if name and name in names:
        return True
    identifier = getattr(user, 'user_id', None)
    if identifier and str(identifier).strip().lower() in ids:
        return True
    return _password_matches_default(getattr(user, 'password_hash', None))


def _apply_hierarchy_defaults(project: str | None, department: str | None, team: str | None) -> tuple[str, str, str]:
    proj = (project or '').strip()
    dept = (department or '').strip()
    team_value = (team or '').strip()

    if team_value:
        info = TEAM_TO_INFO.get(team_value.lower())
        if info:
            proj = proj or info[0]
            if not dept:
                dept = info[1]
            team_value = info[2]
    if dept:
        info = DEPARTMENT_TO_PROJECT.get(dept.lower())
        if info:
            proj = proj or info[0]
            dept = info[1]

    if proj:
        proj = PROJECT_NORMALIZATION.get(proj.lower(), proj)

    return proj, dept, team_value


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


def _diff_key_candidates(*values) -> set[str]:
    keys: set[str] = set()
    for value in values:
        if value in (None, ''):
            continue
        text = str(value).strip().lower()
        if text:
            keys.add(text)
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
        location_name = _normalize_location_label(location_name) or ''
        department_obj = item.get('department') or {}
        department_name = ''
        if isinstance(department_obj, dict):
            department_name = (department_obj.get('name') or '').strip()
        division_obj = item.get('division') or {}
        division_name = ''
        if isinstance(division_obj, dict):
            division_name = (division_obj.get('name') or '').strip()
        keys = _diff_key_candidates(full_name, email, employee_id)
        entries.append({
            'name': full_name,
            'email': email,
            'user_id': employee_id,
             'peopleforce_id': employee_id,
             'department': department_name,
             'project': division_name,
             'location': location_name,
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
                'project': item.get('project'),
                'department': item.get('department'),
                'team': item.get('team'),
                'location': _normalize_location_label(item.get('location')) or (item.get('location') or ''),
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
    project_resolved, department_resolved, team_resolved = _apply_hierarchy_defaults(
        record.project,
        record.department,
        record.team,
    )
    corrected_display = _minutes_to_str(record.corrected_total_minutes) if record.corrected_total_minutes is not None else ''
    corrected_hm = _minutes_to_hm(record.corrected_total_minutes) if record.corrected_total_minutes is not None else ''
    manual_flags = {field: bool(getattr(record, attr)) for field, attr in MANUAL_FLAG_MAP.items()}
    location_value = _normalize_location_label(record.location)
    return {
        'id': record.id,
        'date': record.record_date.isoformat(),
        'date_display': record.record_date.strftime('%d.%m.%y'),
        'weekday': record.record_date.strftime('%a'),
        'scheduled_start': record.scheduled_start or '',
        'scheduled_start_hm': _format_time_hm(record.scheduled_start),
        'actual_start': record.actual_start or '',
        'actual_start_hm': _format_time_hm(record.actual_start),
        'minutes_late': record.minutes_late,
        'minutes_late_display': _minutes_to_str(record.minutes_late),
        'non_productive_minutes': record.non_productive_minutes,
        'non_productive_display': _minutes_to_str(record.non_productive_minutes),
        'not_categorized_minutes': record.not_categorized_minutes,
        'not_categorized_display': _minutes_to_str(record.not_categorized_minutes),
        'productive_minutes': record.productive_minutes,
        'productive_display': _minutes_to_str(record.productive_minutes),
        'total_minutes': record.total_minutes,
        'total_display': _minutes_to_str(record.total_minutes),
        'status': record.status,
        'notes': (record.notes or '').strip(),
        'notes_display': (record.notes or record.leave_reason or '').strip(),
        'leave_reason': (record.leave_reason or '').strip(),
        'project': project_resolved,
        'department': department_resolved,
        'team': team_resolved,
        'location': location_value if location_value is not None else record.location,
        'control_manager': record.control_manager,
        'corrected_total_minutes': record.corrected_total_minutes,
        'corrected_total_display': corrected_display,
        'corrected_total_hm': corrected_hm,
        'manual_flags': manual_flags,
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
        except Exception:
            pass

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
def _log_admin_action(action: str, details: dict) -> None:
    entry = AdminAuditLog(
        user_id=getattr(current_user, 'id', None) if hasattr(current_user, 'id') else None,
        action=action,
        details=details,
    )
    db.session.add(entry)


def _gather_employee_records(search: str | None) -> list[AttendanceRecord]:
    query = AttendanceRecord.query
    if search:
        search_value = f"%{search.lower()}%"
        query = query.filter(or_(
            db.func.lower(AttendanceRecord.user_name).like(search_value),
            db.func.lower(AttendanceRecord.user_email).like(search_value),
            db.func.lower(AttendanceRecord.project).like(search_value),
            db.func.lower(AttendanceRecord.department).like(search_value),
            db.func.lower(AttendanceRecord.team).like(search_value)
        ))
    query = query.order_by(AttendanceRecord.record_date.desc())

    seen = set()
    records: list[AttendanceRecord] = []
    for record in query:
        key = (record.user_id or record.user_email or record.user_name or '').lower()
        if not key or key in seen:
            continue
        seen.add(key)
        records.append(record)
    return records


def _collect_employee_filters(records: list[AttendanceRecord]) -> dict[str, list[str]]:
    projects: set[str] = set()
    departments: set[str] = set()
    teams: set[str] = set()
    for record in records:
        project_resolved, department_resolved, team_resolved = _apply_hierarchy_defaults(
            record.project,
            record.department,
            record.team,
        )
        if project_resolved:
            projects.add(project_resolved)
        if department_resolved:
            departments.add(department_resolved)
        if team_resolved:
            teams.add(team_resolved)
    return {
        'project': sorted(projects),
        'department': sorted(departments),
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
        project_resolved, department_resolved, team_resolved = _apply_hierarchy_defaults(
            record.project,
            record.department,
            record.team,
        )
        resolved_map = {
            'project': project_resolved,
            'department': department_resolved,
            'team': team_resolved,
        }
        attr_value = resolved_map.get(attr, getattr(record, attr, None))
        if attr_value and str(attr_value).strip().lower() == lowered:
            filtered.append(record)
    return filtered


def _serialize_employee_record(record: AttendanceRecord, schedule: dict | None = None) -> dict:
    project_resolved, department_resolved, team_resolved = _apply_hierarchy_defaults(
        record.project,
        record.department,
        record.team,
    )
    peopleforce_id = None
    if schedule and isinstance(schedule, dict):
        candidate = schedule.get('peopleforce_id')
        if candidate not in (None, ''):
            peopleforce_id = str(candidate).strip()
    location_value = _normalize_location_label(record.location)
    return {
        'user_key': record.user_id or record.user_email or record.user_name,
        'user_id': record.user_id,
        'name': record.user_name,
        'email': record.user_email,
        'project': project_resolved,
        'department': department_resolved,
        'team': team_resolved,
        'location': location_value if location_value is not None else record.location,
        'plan_start': record.scheduled_start,
        'control_manager': record.control_manager,
        'peopleforce_id': peopleforce_id,
        'last_date': record.record_date.strftime('%Y-%m-%d'),
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

    # Support multiple project filters: ?project=A&project=B
    projects = request.args.getlist('project')
    if projects:
        projects_lower = [p.lower() for p in projects if p]
        if projects_lower:
            query = query.filter(db.func.lower(AttendanceRecord.project).in_(projects_lower))

    # Support multiple department filters: ?department=A&department=B
    departments = request.args.getlist('department')
    if departments:
        departments_lower = [d.lower() for d in departments if d]
        if departments_lower:
            query = query.filter(db.func.lower(AttendanceRecord.department).in_(departments_lower))

    # Support multiple team filters: ?team=A&team=B
    teams = request.args.getlist('team')
    if teams:
        teams_lower = [t.lower() for t in teams if t]
        if teams_lower:
            query = query.filter(db.func.lower(AttendanceRecord.team).in_(teams_lower))

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

    items = []
    for key, recs in grouped.items():
        recs.sort(key=lambda r: r.record_date)
        first = recs[0]
        first_project, first_department, first_team = _apply_hierarchy_defaults(first.project, first.department, first.team)
        rows = []
        total_non = 0
        total_not = 0
        total_prod = 0
        total_total = 0
        total_corrected = 0
        has_corrected = False
        notes_aggregated = []

        for rec in recs:
            project_resolved, department_resolved, team_resolved = _apply_hierarchy_defaults(rec.project, rec.department, rec.team)
            scheduled_start = rec.scheduled_start or ''
            actual_start = rec.actual_start or ''
            corrected_minutes = rec.corrected_total_minutes
            corrected_display = _minutes_to_str(corrected_minutes) if corrected_minutes is not None else ''
            corrected_hm = _minutes_to_hm(corrected_minutes) if corrected_minutes is not None else ''
            manual_flags = {field: bool(getattr(rec, attr)) for field, attr in MANUAL_FLAG_MAP.items()}
            rows.append({
                'record_id': rec.id,
                'user_name': (rec.user_name or '').strip(),
                'project': project_resolved,
                'department': department_resolved,
                'team': team_resolved,
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

        location_display = _normalize_location_label(first.location)
        items.append({
            'user_name': first.user_name,
            'user_id': first.user_id,
            'project': first_project,
            'department': first_department,
            'team': first_team,
            'location': location_display if location_display is not None else first.location,
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
                'notes': ''
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
            for field in ('project', 'department', 'team'):
                if schedule.get(field):
                    item[field] = schedule[field]
        if schedule.get('location') in (None, ''):
            normalized_item_location = _normalize_location_label(item.get('location'))
            if normalized_item_location is not None:
                item['location'] = normalized_item_location
        project_resolved, department_resolved, team_resolved = _apply_hierarchy_defaults(
            item.get('project'),
            item.get('department'),
            item.get('team'),
        )
        item['project'] = project_resolved
        item['department'] = department_resolved
        item['team'] = team_resolved
        item['schedule'] = schedule
    return items


def _get_schedule_filters(selected: dict[str, str] | None = None) -> dict[str, dict[str, list[str]] | dict[str, str]]:
    """Return available filter options and resolved selections based on schedules."""

    schedules = load_user_schedules()
    fields = ('project', 'department', 'team')

    def normalize(value: str | None) -> str:
        return (value or '').strip()

    selected = selected or {}
    normalized_selected = {field: normalize(selected.get(field)) for field in fields}
    lower_selected = {field: normalized_selected[field].lower() for field in fields}

    entries: list[dict[str, str]] = []
    for info in schedules.values():
        entry = {field: normalize(info.get(field)) for field in fields}
        project_resolved, department_resolved, team_resolved = _apply_hierarchy_defaults(
            entry.get('project'),
            entry.get('department'),
            entry.get('team'),
        )
        entry['project'] = project_resolved
        entry['department'] = department_resolved
        entry['team'] = team_resolved
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
    items = _apply_schedule_overrides(_build_items(records))
    return items, len(records)


@api_bp.route('/attendance')
@login_required
def attendance_list():
    items, records = _get_filtered_items()
    selected_filters = {
        'project': request.args.get('project', ''),
        'department': request.args.get('department', ''),
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
    payload = request.get_json(silent=True) or {}
    force_refresh = bool(payload.get('force_refresh'))
    sync_summary: dict[str, object] = {}

    try:
        from dashboard_app.tasks import _sync_peopleforce_metadata  # local import to avoid circular dependency
        _sync_peopleforce_metadata(current_app)
        sync_summary['peopleforce_metadata'] = 'updated'
    except Exception as exc:  # pragma: no cover - filesystem/network failure
        logger.error(f"PeopleForce sync error: {exc}", exc_info=True)
        sync_summary['peopleforce_metadata'] = f'failed: {exc}'

    try:
        from dashboard_app.tasks import _sync_yaware_plan_start  # local import to avoid circular dependency
        updated_count = _sync_yaware_plan_start(current_app)
        sync_summary['yaware_schedule'] = {'updated': updated_count}
    except Exception as exc:  # pragma: no cover - filesystem/network failure
        logger.error(f"YaWare sync error: {exc}", exc_info=True)
        sync_summary['yaware_schedule'] = f'failed: {exc}'

    try:
        diff_payload = _generate_user_diff(force_refresh=force_refresh)
    except Exception as exc:
        logger.error(f"User diff generation error: {exc}", exc_info=True)
        return jsonify({'error': f'Помилка генерації diff: {str(exc)}'}), 500
    
    _log_admin_action('manual_sync_users', {
        'force_refresh': force_refresh,
        'sync_summary': sync_summary,
        'diff_counts': diff_payload.get('counts'),
    })
    db.session.commit()
    return jsonify({'status': 'ok', 'sync': sync_summary, 'diff': diff_payload})


@api_bp.route('/admin/sync/attendance', methods=['POST'])
@login_required
def admin_sync_attendance():
    _ensure_admin()
    payload = request.get_json(silent=True) or {}
    target_str = (payload.get('date') or '').strip()
    target_date = _parse_date(target_str)
    if not target_date:
        return jsonify({'error': 'Некоректна дата. Використовуйте формат YYYY-MM-DD'}), 400

    skip_weekends = payload.get('skip_weekends', True)
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
    if not name or not email:
        return jsonify({'error': 'name and email are required'}), 400

    schedules = schedule_user_manager.load_users()
    users = schedules.get('users')
    if not isinstance(users, dict):
        users = {}
        schedules['users'] = users

    if name in users:
        return jsonify({'error': 'Користувач з таким ім\'ям вже існує'}), 409

    normalized_email = email.strip().lower()
    for existing_name, info in users.items():
        existing_email = str(info.get('email') or '').strip().lower()
        if existing_email and existing_email == normalized_email:
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

    entry: dict[str, object] = {
        'email': normalized_email,
    }
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
    if control_manager_value is not None:
        entry['control_manager'] = control_manager_value

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
    project_filters = request.args.getlist('project')
    department_filters = request.args.getlist('department')
    team_filters = request.args.getlist('team')
    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = max(min(int(request.args.get('per_page', 25) or 25), 100), 1)

    records = _gather_employee_records(search)
    filter_options = _collect_employee_filters(records)
    
    # Support multiple filters for each category
    if project_filters:
        project_filters_lower = {p.lower() for p in project_filters if p}
        records = [r for r in records if (r.project or '').lower() in project_filters_lower]
    
    if department_filters:
        department_filters_lower = {d.lower() for d in department_filters if d}
        records = [r for r in records if (r.department or '').lower() in department_filters_lower]
    
    if team_filters:
        team_filters_lower = {t.lower() for t in team_filters if t}
        records = [r for r in records if (r.team or '').lower() in team_filters_lower]
    
    total = len(records)
    start = (page - 1) * per_page
    page_records = records[start:start + per_page]

    items: list[dict] = []
    for record in page_records:
        identifier = record.user_id or record.user_email or record.user_name or ''
        schedule = _load_user_schedule_variants(identifier, [record]) if identifier else None
        items.append(_serialize_employee_record(record, schedule))

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

    new_name = target_name
    if 'name' in updates:
        desired = (updates['name'] or '').strip()
        if desired and desired != target_name:
            users[desired] = target_info
            users.pop(target_name, None)
            new_name = desired
            changed = True

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

    for field in ('project', 'department', 'team', 'location', 'plan_start'):
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

    # Apply hierarchy defaults to ensure consistent project/department/team values.
    sample_record = records[0]
    canonical_project, canonical_department, canonical_team = _apply_hierarchy_defaults(
        getattr(sample_record, 'project', None),
        getattr(sample_record, 'department', None),
        getattr(sample_record, 'team', None),
    )
    for record in records:
        if canonical_project:
            record.project = canonical_project
        if canonical_department:
            record.department = canonical_department
        if canonical_team:
            record.team = canonical_team

    # Ensure updates and schedule payload include resolved hierarchy.
    if canonical_project and not updates.get('project'):
        updates['project'] = canonical_project
    if canonical_department and not updates.get('department'):
        updates['department'] = canonical_department
    if canonical_team and not updates.get('team'):
        updates['team'] = canonical_team
    for field, value in (('project', canonical_project), ('department', canonical_department), ('team', canonical_team)):
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


@api_bp.route('/admin/app-users')
@login_required
def admin_app_users():
    _ensure_admin()
    users = User.query.order_by(User.created_at.asc()).all()
    visible = [user for user in users if user.is_admin or user.is_control_manager or not _is_synced_employee(user)]
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
                return jsonify({'error': 'Email уже используется'}), 400
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

    project_resolved, department_resolved, team_resolved = _apply_hierarchy_defaults(
        profile.get('project'),
        profile.get('department'),
        profile.get('team'),
    )
    profile['project'] = project_resolved
    profile['department'] = department_resolved
    profile['team'] = team_resolved
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
    records = query.order_by(AttendanceRecord.record_date.desc()).all()

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
    status_options = sorted({record.status for record in records if record.status})

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
    update_duration('total_minutes', 'total_minutes')
    update_duration('corrected_total_minutes', 'corrected_total_minutes')

    if 'status' in payload:
        status = str(payload.get('status') or '').strip()
        if status:
            record.status = status
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
        {'values': ['Отчет сформирован за период:', '', _resolve_period_display(), '', '', '', '', '', '', ''], 'role': 'summary_period'},
        {'values': ['по команде:', '', _resolve_team_display(), '', '', '', '', '', '', ''], 'role': 'summary_team'},
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
IGNORED_DIFF_PERSONS: tuple[tuple[str, str], ...] = (
    ('bilopolska valentyna', ''),
    ('yerushchenko oksana', ''),
    ('tkachenko oleksandra', 'a.tkachenko@evadav.com'),
    ('sidorov boris', 'boris@evadav.com'),
    ('sluchevskyi gleb', 'glebslu@gmail.com'),
    ('marcinkute ilona', 'i.marcinkute@evadav.com'),
    ('hr evrius', 'hr_cz@evrius.com'),
    ('hreben katsiaryna', 'administration@evadav.com'),
    ('bochkovskyi oleksandr', 'bochkovskiy@evadav.com'),
    ('dolhov andrii', 'a.dolgov@evadav.com'),
    ('dubinin egor', 'e.dubinin@evadav.com'),
    ('hrechka oksana', 'o.hrechka@evadav.com'),
    ('kliushyn anton', 'a.kliushyn@evadav.com'),
    ('lyukshin boris', 'b.lyukshin@evadav.com'),
    ('morkin serhii', 'ms@evadav.com'),
    ('perchatochnikov maksim', ''),
    ('poniatov anton', 'ponyatov.anton@gmail.com'),
    ('postoi anton', ''),
    ('raeva kateryna', 'kateadler17@gmail.com'),
    ('test anna', 'alenakriv91@gmail.com'),
    ('tkachenko ivan', 'i.tkachenko@evadav.com'),
    ('volodin dmitriy', 'd.volodin@evadav.com'),
    ('ovcharenko german', 'german@evadav.com'),
    ('gorobinska tetiana', '')
)

IGNORED_DIFF_EMAILS = {email for _, email in IGNORED_DIFF_PERSONS if email}


def _is_ignored_person(name: str | None, email: str | None) -> bool:
    normalized_name = (name or '').strip().lower()
    normalized_email = (email or '').strip().lower()
    if not normalized_name and not normalized_email:
        return False
    if (normalized_name, normalized_email) in IGNORED_DIFF_PERSONS:
        return True
    if normalized_email and normalized_email in IGNORED_DIFF_EMAILS:
        return True
    if (normalized_name, '') in IGNORED_DIFF_PERSONS:
        return True
    return False
