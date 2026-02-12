from __future__ import annotations

import atexit
import logging
import os
import re
from datetime import date, datetime, timedelta, time
from collections import deque

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import pytz

from flask import current_app

from dashboard_app.extensions import db
from dashboard_app.models import AttendanceRecord
from dashboard_app.lateness_service import collect_lateness_for_date
from tasks.update_attendance import update_for_date
from tracker_alert.client.peopleforce_api import PeopleForceClient
from tracker_alert.client.yaware_v2_api import client as yaware_client
from tracker_alert.services import user_manager as schedule_user_manager
from tracker_alert.services.attendance_monitor import AttendanceMonitor
from tracker_alert.services.schedule_utils import has_manual_override
from dashboard_app.user_data import clear_user_schedule_cache
from dashboard_app.hierarchy_adapter import (
    load_level_grade_data,
    get_adapted_hierarchy_for_user,
    apply_adapted_hierarchy,
)

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
SCHEDULER: BackgroundScheduler | None = None
LOCAL_TZ = pytz.timezone("Europe/Warsaw")
SCHEDULER_LOG = deque(maxlen=200)


def _backup_database(app):
    """Бекап перед синхронізацією: БД, week/monthly notes, user_schedules (як у scripts/sync_from_server.sh). Залишаємо останні 7 бекапів."""
    import shutil
    try:
        instance_path = app.instance_path
        base_dir = app.config.get("BASE_DIR") or os.path.dirname(instance_path)
        config_dir = os.path.join(base_dir, "config")
        backups_root = os.path.join(base_dir, "backups")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(backups_root, f"auto_backup_{timestamp}")
        backup_instance = os.path.join(backup_dir, "instance")
        backup_config = os.path.join(backup_dir, "config")
        os.makedirs(backup_instance, exist_ok=True)
        os.makedirs(backup_config, exist_ok=True)

        # instance/dashboard.db
        db_path = os.path.join(instance_path, "dashboard.db")
        if os.path.exists(db_path):
            shutil.copy2(db_path, os.path.join(backup_instance, "dashboard.db"))
            logger.info("[scheduler] Backup: dashboard.db")
        else:
            logger.warning("[scheduler] Database file not found: %s", db_path)

        # instance/week_notes.json, monthly_notes.json
        for name in ("week_notes.json", "monthly_notes.json"):
            src = os.path.join(instance_path, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(backup_instance, name))
                logger.info("[scheduler] Backup: %s", name)

        # config/user_schedules.json
        user_schedules_path = os.path.join(config_dir, "user_schedules.json")
        if os.path.exists(user_schedules_path):
            shutil.copy2(user_schedules_path, os.path.join(backup_config, "user_schedules.json"))
            logger.info("[scheduler] Backup: user_schedules.json")
        else:
            logger.warning("[scheduler] user_schedules.json not found: %s", user_schedules_path)

        logger.info("[scheduler] Full backup created: %s", backup_dir)

        # Видаляємо старі автобекапи (залишаємо останні 7)
        if not os.path.isdir(backups_root):
            return
        backup_dirs = sorted(
            [d for d in os.listdir(backups_root) if d.startswith("auto_backup_") and os.path.isdir(os.path.join(backups_root, d))],
            reverse=True,
        )
        for old_name in backup_dirs[7:]:
            old_path = os.path.join(backups_root, old_name)
            shutil.rmtree(old_path, ignore_errors=True)
            logger.info("[scheduler] Removed old backup: %s", old_name)

    except Exception as e:
        logger.error("[scheduler] Failed to create backup: %s", e, exc_info=True)


def _with_app_context(app, func, *args, **kwargs):
    with app.app_context():
        return func(app, *args, **kwargs)


def _run_daily_attendance(app):
    """Синхронізація вчорашнього дня з YaWare (та сама логіка, що кнопка «Синхрон даты» на сайті)."""
    target = date.today() - timedelta(days=1)
    logger.info("[scheduler] Running daily attendance sync for %s", target)
    monitor = AttendanceMonitor()
    update_for_date(monitor, target, include_absent=True)
    logger.info("[scheduler] Attendance sync completed for %s", target)


def _run_today_lateness_sync(app):
    """Синхронізація запізнень за сьогодні з YaWare (лише lateness_records, не attendance_records). Та сама логіка, що кнопка «Синхронізувати день» на сторінці Опоздания. О 10:00, щоб до 10:02 бот міг сформувати звіт."""
    target = date.today()
    logger.info("[scheduler] Running today lateness sync for %s (lateness only)", target)
    collect_lateness_for_date(target, include_absent=True, skip_weekends=False)
    logger.info("[scheduler] Today lateness sync completed for %s", target)


def _run_weekly_attendance_backfill(app):
    """
    Пересинхронізація за останні 7 днів, щоб підтягнути відпустки/лікарняні,
    оформлені заднім числом у PeopleForce.
    """
    monitor = AttendanceMonitor()
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=6)
    logger.info("[scheduler] Running weekly attendance backfill for %s .. %s", start, end)
    current = start
    while current <= end:
        update_for_date(monitor, current, include_absent=True)
        current += timedelta(days=1)
    logger.info("[scheduler] Weekly attendance backfill completed")


def _cleanup_old_records(app):
    # Keep records for 1 year instead of 1 month
    cutoff = date.today() - timedelta(days=365)
    filters = [
        AttendanceRecord.record_date < cutoff,
        AttendanceRecord.manual_scheduled_start.is_(False),
        AttendanceRecord.manual_actual_start.is_(False),
        AttendanceRecord.manual_minutes_late.is_(False),
        AttendanceRecord.manual_non_productive_minutes.is_(False),
        AttendanceRecord.manual_not_categorized_minutes.is_(False),
        AttendanceRecord.manual_productive_minutes.is_(False),
        AttendanceRecord.manual_total_minutes.is_(False),
        AttendanceRecord.manual_corrected_total_minutes.is_(False),
        AttendanceRecord.manual_status.is_(False),
        AttendanceRecord.manual_notes.is_(False),
        AttendanceRecord.manual_leave_reason.is_(False),
    ]
    deleted = AttendanceRecord.query.filter(*filters).delete(synchronize_session=False)
    db.session.commit()
    logger.info("[scheduler] Cleanup removed %s records older than %s", deleted, cutoff)


def _clean_telegram_username(value: str) -> str:
    """Очищує telegram username від HTML тегів та зайвих символів."""
    if not value:
        return ""
    
    # Видаляємо HTML теги
    value = re.sub(r'<[^>]+>', '', value)
    # Видаляємо зайві пробіли
    value = value.strip()
    # Видаляємо @ якщо є на початку
    value = value.lstrip('@')
    
    return value


def append_scheduler_log(job_id: str, status: str, message: str = "", scheduled_time: datetime | None = None) -> None:
    """Додати запис у журнал виконання задач."""
    finished_at = datetime.now(LOCAL_TZ)
    scheduled_local = scheduled_time.astimezone(LOCAL_TZ) if scheduled_time else None
    duration = None
    if scheduled_local:
        duration = (finished_at - scheduled_local).total_seconds()
        if duration < 0:
            duration = None
    entry = {
        "job_id": job_id,
        "status": status,
        "message": (message or "")[:500],
        "scheduled_time": scheduled_local.isoformat() if scheduled_local else None,
        "finished_at": finished_at.isoformat(),
        "duration_seconds": duration,
    }
    SCHEDULER_LOG.appendleft(entry)


def _scheduler_event_listener(event):
    status = "success"
    message = ""
    if event.code == EVENT_JOB_ERROR:
        status = "error"
        message = str(getattr(event, "exception", ""))[:500]
    append_scheduler_log(event.job_id, status, message, getattr(event, "scheduled_run_time", None))


def _sync_organizational_hierarchy(app):
    """Синхронізує повну організаційну ієрархію з PeopleForce"""
    logger.info("[scheduler] Running organizational hierarchy sync")
    try:
        client = PeopleForceClient()
        
        # Завантажуємо поточні дані
        data = schedule_user_manager.load_users()
        if not isinstance(data, dict):
            data = {}
        
        # Завантажуємо всі рівні ієрархії через API endpoints
        divisions = []
        directions = []
        units = []
        teams = []
        
        try:
            divisions = client._get('/divisions') or []
            if isinstance(divisions, dict) and 'data' in divisions:
                divisions = divisions['data']
        except:
            logger.warning("Could not fetch divisions")
        
        try:
            directions = client._get('/directions') or []
            if isinstance(directions, dict) and 'data' in directions:
                directions = directions['data']
        except:
            logger.warning("Could not fetch directions")
        
        try:
            units = client._get('/units') or []
            if isinstance(units, dict) and 'data' in units:
                units = units['data']
        except:
            logger.warning("Could not fetch units")
        
        try:
            teams = client._get('/teams') or []
            if isinstance(teams, dict) and 'data' in teams:
                teams = teams['data']
        except:
            logger.warning("Could not fetch teams")
        
        # Зберігаємо ієрархію в _metadata
        hierarchy = {
            'divisions': [
                {
                    'id': div.get('id'),
                    'name': div.get('name'),
                    'parent_id': div.get('parent_id')
                }
                for div in (divisions if isinstance(divisions, list) else [])
            ],
            'directions': [
                {
                    'id': direc.get('id'),
                    'name': direc.get('name'),
                    'parent_id': direc.get('parent_id')
                }
                for direc in (directions if isinstance(directions, list) else [])
            ],
            'units': [
                {
                    'id': unit.get('id'),
                    'name': unit.get('name'),
                    'parent_id': unit.get('parent_id')
                }
                for unit in (units if isinstance(units, list) else [])
            ],
            'teams': [
                {
                    'id': team.get('id'),
                    'name': team.get('name'),
                    'parent_id': team.get('parent_id')
                }
                for team in (teams if isinstance(teams, list) else [])
            ]
        }
        
        if not isinstance(data.get('_metadata'), dict):
            data['_metadata'] = {}
        
        data['_metadata']['organizational_hierarchy'] = hierarchy
        data['_metadata']['hierarchy_synced_at'] = datetime.now().isoformat()
        
        schedule_user_manager.save_users(data)
        logger.info(f"[scheduler] Organizational hierarchy synced: {len(divisions)} divisions, {len(directions)} directions, {len(units)} units, {len(teams)} teams")
        
    except Exception as e:
        logger.error(f"[scheduler] Error syncing organizational hierarchy: {e}")


def _sync_peopleforce_metadata(app):
    """Синхронізувати лише статуси PeopleForce (відпустка/лікарняний)."""
    logger.info("[scheduler] Running PeopleForce leave status sync")
    client = PeopleForceClient()
    today = date.today()
    try:
        leaves = client.get_leave_requests(start_date=today, end_date=today)
    except Exception as exc:
        logger.error("[scheduler] Failed to fetch leave requests: %s", exc, exc_info=True)
        return

    leave_by_email: dict[str, dict] = {}
    for leave in leaves or []:
        employee = leave.get("employee") or {}
        email = (employee.get("email") or "").strip().lower()
        if not email:
            continue
        leave_type = leave.get("leave_type")
        if isinstance(leave_type, dict):
            leave_name = (leave_type.get("name") or "").strip()
        else:
            leave_name = str(leave_type or "").strip()
        entries = leave.get("entries") or []
        amount = 1.0
        for entry in entries:
            if entry.get("date") == today.isoformat():
                try:
                    amount = float(entry.get("amount", amount))
                except (TypeError, ValueError):
                    amount = 1.0
                break
        leave_by_email[email] = {
            "status": leave_name or "Leave",
            "amount": amount,
            "starts_on": leave.get("starts_on"),
            "ends_on": leave.get("ends_on"),
            "state": leave.get("state"),
        }

    data = schedule_user_manager.load_users()
    users = data.get("users", {}) if isinstance(data, dict) else {}
    leave_fields = [
        "peopleforce_leave_status",
        "peopleforce_leave_amount",
        "peopleforce_leave_start",
        "peopleforce_leave_end",
        "peopleforce_leave_state",
        "peopleforce_leave_updated_at",
    ]

    updated = False
    for info in users.values():
        if not isinstance(info, dict):
            continue
        email = (info.get("email") or "").strip().lower()
        leave_info = leave_by_email.get(email)

        if leave_info:
            new_values = {
                "peopleforce_leave_status": leave_info["status"],
                "peopleforce_leave_amount": leave_info["amount"],
                "peopleforce_leave_start": leave_info["starts_on"],
                "peopleforce_leave_end": leave_info["ends_on"],
                "peopleforce_leave_state": leave_info["state"],
                "peopleforce_leave_updated_at": today.isoformat(),
            }
            for key, value in new_values.items():
                if info.get(key) != value:
                    info[key] = value
                    updated = True
        else:
            for key in leave_fields:
                if key in info:
                    info.pop(key)
                    updated = True

    if updated:
        if not schedule_user_manager.save_users(data):
            raise RuntimeError("Не вдалося зберегти user_schedules.json після синхронізації PeopleForce")
        clear_user_schedule_cache()
        logger.info("[scheduler] Updated leave statuses from PeopleForce")
    
    try:
        stats = _run_level_grade_adaptation(app, force=True)
        if stats['updated']:
            logger.info("[scheduler] Level_Grade adaptation applied to %s/%s users", stats['updated'], stats['total'])
    except FileNotFoundError:
        logger.warning("[scheduler] Level_Grade.json not found, skipping hierarchy adaptation")
    except Exception as exc:
        logger.error("[scheduler] Failed to auto-adapt hierarchy: %s", exc, exc_info=True)


def _run_level_grade_adaptation(app, force: bool = False) -> dict:
    """Run Level_Grade adaptation over all schedule users."""
    base_dir = app.config.get('BASE_DIR', os.path.dirname(os.path.dirname(__file__)))
    level_grade_data = load_level_grade_data(base_dir)
    if not level_grade_data:
        raise FileNotFoundError("Level_Grade.json not found")

    data = schedule_user_manager.load_users()
    users = data.get("users", {}) if isinstance(data, dict) else {}
    if not isinstance(users, dict):
        return {'total': 0, 'updated': 0}

    adapted_count = 0
    changed = False
    total = 0
    for name, info in users.items():
        if not isinstance(info, dict):
            continue
        total += 1
        adapted = get_adapted_hierarchy_for_user(name, info, level_grade_data)
        if not adapted:
            continue
        changed_fields = apply_adapted_hierarchy(info, adapted, force=force)
        if changed_fields:
            adapted_count += 1
            changed = True

    if changed:
        if not schedule_user_manager.save_users(data):
            raise RuntimeError("Не вдалося зберегти user_schedules.json після автозастосування Level_Grade")
        clear_user_schedule_cache()

    return {'total': total, 'updated': adapted_count}


def run_level_grade_adaptation(app, *, force: bool = False) -> dict:
    """Public helper for API/manual triggers."""
    return _run_level_grade_adaptation(app, force=force)


def _normalize_time(value: object | None) -> str | None:
    if value in (None, ''):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 4:
        text = f"{text[:2]}:{text[2:]}"
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return text


def _parse_int(value: object | None) -> int | None:
    if value in (None, ''):
        return None
    try:
        return int(float(str(value).replace(',', '.')))
    except (TypeError, ValueError):
        return None


def _extract_email(record: dict) -> str:
    candidates = [
        record.get("email"),
        record.get("user_email"),
        record.get("userEmail"),
    ]
    user_field = record.get("user") or record.get("full_name") or record.get("fullName")
    if isinstance(user_field, str) and ", " in user_field:
        candidates.append(user_field.split(", ", 1)[1])
    for candidate in candidates:
        if not candidate:
            continue
        email = str(candidate).strip().lower()
        if email:
            return email
    return ""


def _extract_schedule_start(record: dict) -> str | None:
    schedule_obj = record.get("schedule")
    if isinstance(schedule_obj, dict):
        for key in ("start_time", "startTime", "start", "begin"):
            start_value = _normalize_time(schedule_obj.get(key))
            if start_value:
                return start_value

    for key in ("schedule_start", "scheduleStart", "plan_start", "planStart", "expected_start", "expectedStart"):
        start_value = _normalize_time(record.get(key))
        if start_value:
            return start_value

    actual_value = _normalize_time(
        record.get("time_start")
        or record.get("timeStart")
        or record.get("start_time")
        or record.get("startTime")
    )
    lateness_minutes = _parse_int(record.get("lateness") or record.get("lateness_minutes") or record.get("late"))
    if actual_value and lateness_minutes is not None:
        try:
            actual_dt = datetime.strptime(actual_value, "%H:%M")
        except ValueError:
            return actual_value
        plan_dt = (datetime.combine(date.today(), actual_dt.time()) - timedelta(minutes=lateness_minutes)).time()
        return plan_dt.strftime("%H:%M")

    return None


def _gather_schedule_candidates(entry: dict) -> list[str]:
    candidates: list[str] = []

    def visit(obj, path: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                next_path = f"{path}.{key}" if path else str(key)
                visit(value, next_path)
        elif isinstance(obj, list):
            for item in obj:
                visit(item, path)
        else:
            normalized = _normalize_time(obj)
            if not normalized:
                return
            path_lower = path.lower()
            if any(token in path_lower for token in ('start', 'from', 'begin', 'work_start', 'time_from', 'shift_from')):
                candidates.append(normalized)

    visit(entry)
    return candidates


def _parse_schedule_payload(payload: object) -> tuple[dict[str, str], dict[str, str]]:
    id_map: dict[str, str] = {}
    email_map: dict[str, str] = {}

    if not payload:
        return id_map, email_map

    def iterable_from(obj: object) -> list:
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for key in ("data", "items", "schedules", "users", "result"):
                value = obj.get(key)
                if isinstance(value, list):
                    return value
            if all(isinstance(v, (dict, list)) for v in obj.values()):
                return list(obj.values())
        return []

    entries = iterable_from(payload)
    if not entries and isinstance(payload, dict):
        entries = [payload]

    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        user_id = None
        for key in ("user_id", "userId", "employee_id", "employeeId", "id"):
            value = raw_entry.get(key)
            if value not in (None, ""):
                user_id = str(value).strip()
                break
        if not user_id:
            user_block = raw_entry.get("user")
            if isinstance(user_block, dict):
                for key in ("user_id", "userId", "id"):
                    value = user_block.get(key)
                    if value not in (None, ""):
                        user_id = str(value).strip()
                        break
        email = _extract_email(raw_entry)
        if not email and isinstance(raw_entry.get("user"), dict):
            email = _extract_email(raw_entry["user"])

        candidates = _gather_schedule_candidates(raw_entry)
        start_time = min(candidates) if candidates else None
        if not start_time:
            continue
        if user_id and user_id not in id_map:
            id_map[user_id] = start_time
        if email and email not in email_map:
            email_map[email] = start_time

    return id_map, email_map


def _sync_yaware_plan_start(app, target_date: date | None = None) -> int:
    logger.info("[scheduler] Running YaWare schedule sync")
    target = target_date or date.today()
    attempt_dates: list[date] = [target]
    if target.weekday() == 0:
        attempt_dates.append(target - timedelta(days=3))
    elif target.weekday() == 6:
        attempt_dates.append(target - timedelta(days=2))
    else:
        attempt_dates.append(target - timedelta(days=1))
    start_by_id: dict[str, str] = {}
    start_by_email: dict[str, str] = {}

    schedules_payload = yaware_client.get_schedules()
    schedule_id_map, schedule_email_map = _parse_schedule_payload(schedules_payload)
    start_by_id.update(schedule_id_map)
    start_by_email.update(schedule_email_map)

    for attempt in attempt_dates:
        try:
            response = yaware_client.get_summary_by_day(attempt.isoformat()) or []
        except Exception as exc:
            logger.warning("[scheduler] Failed to fetch YaWare summary for %s: %s", attempt, exc)
            if attempt == attempt_dates[-1]:
                raise
            continue

        if isinstance(response, dict):
            possible_lists = []
            for key in ("data", "users", "items"):
                payload = response.get(key)
                if isinstance(payload, list):
                    possible_lists.append(payload)
            if possible_lists:
                response_iterable = possible_lists[0]
            else:
                response_iterable = []
        else:
            response_iterable = response

        for record in response_iterable:
            if not isinstance(record, dict):
                continue
            start_time = _extract_schedule_start(record)
            if not start_time:
                continue
            user_id = str(record.get("user_id") or record.get("id") or "").strip()
            if user_id and user_id not in start_by_id:
                start_by_id[user_id] = start_time

            email = _extract_email(record)
            if email and email not in start_by_email:
                start_by_email[email] = start_time

        if start_by_id or start_by_email:
            break

    if not start_by_id and not start_by_email:
        logger.info("[scheduler] YaWare summary returned no schedule information for %s (attempts: %s)",
                    target, ", ".join(d.isoformat() for d in attempt_dates))
        return 0

    data = schedule_user_manager.load_users()
    users = data.get("users", {}) if isinstance(data, dict) else {}
    if not isinstance(users, dict) or not users:
        logger.info("[scheduler] No schedule users to update")
        return 0

    updated = 0
    for name, info in users.items():
        if not isinstance(info, dict):
            continue
        email = str(info.get("email") or "").strip().lower()
        user_id = str(info.get("user_id") or "").strip()
        current = str(info.get("start_time") or "").strip()
        new_value = None
        if email and email in start_by_email:
            new_value = start_by_email[email]
        elif user_id and user_id in start_by_id:
            new_value = start_by_id[user_id]
        if new_value and new_value != current and not has_manual_override(info, "start_time"):
            info["start_time"] = new_value
            updated += 1

    if updated:
        if not schedule_user_manager.save_users(data):
            raise RuntimeError("Не вдалося зберегти user_schedules.json після синхронізації YaWare")
        clear_user_schedule_cache()
        logger.info("[scheduler] Updated start_time for %s users from YaWare", updated)
    else:
        logger.info("[scheduler] YaWare schedule sync made no changes")
    return updated


def register_tasks(app):
    global _scheduler, SCHEDULER
    if not app.config.get("ENABLE_SCHEDULER"):
        return

    if _scheduler:
        return

    scheduler = BackgroundScheduler(timezone=LOCAL_TZ)
    # 09:14 Warsaw - повний бекап (БД, week/monthly notes, user_schedules) перед синком
    scheduler.add_job(lambda: _with_app_context(app, _backup_database), 
                      CronTrigger(hour=9, minute=14, timezone=LOCAL_TZ),
                      id='pre_sync_backup', replace_existing=True)
    # 10:00 Warsaw - синхронізація запізнень за сьогодні (lateness_records; для звіту о 10:02)
    scheduler.add_job(lambda: _with_app_context(app, _run_today_lateness_sync), 
                      CronTrigger(hour=10, minute=0, day_of_week='mon-fri', timezone=LOCAL_TZ),
                      id='today_lateness_sync', replace_existing=True)
    # 09:30 Warsaw - синхронізація вчорашнього дня з YaWare (щодня)
    scheduler.add_job(lambda: _with_app_context(app, _run_daily_attendance), 
                      CronTrigger(hour=9, minute=30, timezone=LOCAL_TZ),
                      id='daily_attendance_sync', replace_existing=True)
    # Неділя 10:00 Warsaw - пересинк за останні 7 днів (відпустки/лікарняні заднім числом)
    scheduler.add_job(lambda: _with_app_context(app, _run_weekly_attendance_backfill),
                      CronTrigger(day_of_week='sun', hour=10, minute=0, timezone=LOCAL_TZ),
                      id='weekly_attendance_backfill', replace_existing=True)
    scheduler.add_listener(_scheduler_event_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
    scheduler.start()

    _scheduler = scheduler
    global SCHEDULER
    SCHEDULER = scheduler
    app.config['SCHEDULER'] = scheduler
    app.config['SCHEDULER_LOG'] = SCHEDULER_LOG
    atexit.register(lambda: scheduler.shutdown(wait=False))

    logger.info(
        "[scheduler] Background scheduler started (timezone: Europe/Warsaw):\n"
        "  - 09:14 Warsaw - Full backup (DB, notes, user_schedules) before sync\n"
        "  - 10:00 Warsaw (Mon-Fri) - Lateness sync today (lateness_records only, for report at 10:02)\n"
        "  - 09:30 Warsaw - YaWare sync yesterday\n"
        "  - Sun 10:00 Warsaw - Weekly backfill (last 7 days, backdated leave)"
    )
