from __future__ import annotations

import atexit
import logging
from calendar import monthrange
from datetime import date, datetime, timedelta, time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from flask import current_app

from dashboard_app.extensions import db
from dashboard_app.models import AttendanceRecord
from tasks.update_attendance import update_for_date
from tracker_alert.client.peopleforce_api import PeopleForceClient
from tracker_alert.client.yaware_v2_api import client as yaware_client
from tracker_alert.services import user_manager as schedule_user_manager
from tracker_alert.services.attendance_monitor import AttendanceMonitor
from tracker_alert.services.schedule_utils import has_manual_override
from dashboard_app.user_data import clear_user_schedule_cache

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _with_app_context(app, func, *args, **kwargs):
    with app.app_context():
        return func(app, *args, **kwargs)


def _run_daily_attendance(app):
    target = date.today() - timedelta(days=1)
    logger.info("[scheduler] Running daily attendance sync for %s", target)
    monitor = AttendanceMonitor()
    update_for_date(monitor, target, include_absent=True)
    logger.info("[scheduler] Attendance sync completed for %s", target)


def _run_prev_month_resync(app):
    today = date.today()
    prev_month_last_day = today.replace(day=1) - timedelta(days=1)
    year, month = prev_month_last_day.year, prev_month_last_day.month
    start_day = date(year, month, 1)
    days = monthrange(year, month)[1]

    logger.info("[scheduler] Re-sync previous month %04d-%02d", year, month)
    monitor = AttendanceMonitor()
    for offset in range(days):
        target = start_day + timedelta(days=offset)
        update_for_date(monitor, target, include_absent=True)
    logger.info("[scheduler] Previous month sync finished")


def _cleanup_old_records(app):
    cutoff = date.today().replace(day=1)
    prev_month_start = (cutoff - timedelta(days=1)).replace(day=1)
    filters = [
        AttendanceRecord.record_date < prev_month_start,
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
    logger.info("[scheduler] Cleanup removed %s records older than %s", deleted, prev_month_start)


def _sync_peopleforce_metadata(app):
    logger.info("[scheduler] Running PeopleForce metadata sync")
    client = PeopleForceClient()
    employees = client.get_employees(force_refresh=True)
    data = schedule_user_manager.load_users()
    users = data.get("users", {}) if isinstance(data, dict) else {}

    employees_by_email = {}
    for emp in employees:
        email = (emp.get("email") or "").strip().lower()
        if email:
            employees_by_email[email] = emp

    updated = False
    new_employees: list[str] = []
    for name, info in users.items():
        if not isinstance(info, dict):
            continue
        email = (info.get("email") or "").strip().lower()
        if not email:
            continue
        employee = employees_by_email.get(email)
        if not employee:
            continue

        location_obj = employee.get("location") or {}
        location_name = ""
        if isinstance(location_obj, dict):
            location_name = (location_obj.get("name") or "").strip()
        if location_name and not has_manual_override(info, "location") and info.get("location") != location_name:
            info["location"] = location_name
            updated = True

        department_obj = employee.get("department") or {}
        department_name = ""
        if isinstance(department_obj, dict):
            department_name = (department_obj.get("name") or "").strip()
        if department_name and not has_manual_override(info, "department") and info.get("department") != department_name:
            info["department"] = department_name
            updated = True

    for email, employee in employees_by_email.items():
        existing = None
        for info in users.values():
            if isinstance(info, dict) and (info.get("email") or "").strip().lower() == email:
                existing = info
                break
        if existing:
            continue
        full_name = employee.get("full_name") or f"{employee.get('first_name', '')} {employee.get('last_name', '')}".strip()
        if full_name:
            new_employees.append(full_name)

    if updated:
        schedule_user_manager.save_users(data)
        logger.info("[scheduler] Updated schedule metadata from PeopleForce")

    if new_employees:
        logger.info("[scheduler] Нові співробітники в PeopleForce (потрібно додати вручну): %s", ", ".join(new_employees[:10]))


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
    global _scheduler
    if not app.config.get("ENABLE_SCHEDULER"):
        return

    if _scheduler:
        return

    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: _with_app_context(app, _run_daily_attendance), CronTrigger(hour=5, minute=0))
    scheduler.add_job(lambda: _with_app_context(app, _sync_peopleforce_metadata), CronTrigger(hour=6, minute=0))
    scheduler.add_job(lambda: _with_app_context(app, _run_prev_month_resync), CronTrigger(day="1", hour=5, minute=15))
    scheduler.add_job(lambda: _with_app_context(app, _cleanup_old_records), CronTrigger(day="1", hour=5, minute=45))
    scheduler.start()

    _scheduler = scheduler
    atexit.register(lambda: scheduler.shutdown(wait=False))

    logger.info("[scheduler] Background scheduler started (tz=%s)", current_app.config.get("TIMEZONE", "UTC"))
