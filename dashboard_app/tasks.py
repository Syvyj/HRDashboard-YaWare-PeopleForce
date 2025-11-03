from __future__ import annotations

import atexit
import logging
from calendar import monthrange
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from flask import current_app

from dashboard_app.extensions import db
from dashboard_app.models import AttendanceRecord
from tasks.update_attendance import update_for_date
from tracker_alert.client.peopleforce_api import PeopleForceClient
from tracker_alert.services import user_manager as schedule_user_manager
from tracker_alert.services.attendance_monitor import AttendanceMonitor

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
        if location_name and info.get("location") != location_name:
            info["location"] = location_name
            updated = True

        department_obj = employee.get("department") or {}
        department_name = ""
        if isinstance(department_obj, dict):
            department_name = (department_obj.get("name") or "").strip()
        if department_name and info.get("department") != department_name:
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
