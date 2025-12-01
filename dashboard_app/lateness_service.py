from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

from dashboard_app.extensions import db
from dashboard_app.models import AttendanceRecord, LatenessRecord
from dashboard_app.user_data import get_user_schedule
from dashboard_app.constants import SEVEN_DAY_WORK_WEEK_IDS
from tasks.update_attendance import update_for_date
from tracker_alert.services.attendance_monitor import AttendanceMonitor

logger = logging.getLogger(__name__)


class LatenessCollectorError(Exception):
    """Raised when lateness collection fails."""


def _ensure_attendance_data(monitor: AttendanceMonitor, target_date: date, include_absent: bool, skip_weekends: bool) -> bool:
    if skip_weekends and target_date.weekday() >= 5:
        return False
    update_for_date(monitor, target_date, include_absent=include_absent)
    return True


def _load_lateness_records(target_date: date) -> Iterable[AttendanceRecord]:
    return (
        AttendanceRecord.query.filter(
            AttendanceRecord.record_date == target_date,
            AttendanceRecord.status.in_(('late', 'absent')),
        )
        .order_by(AttendanceRecord.user_name.asc())
        .all()
    )


def _lookup_schedule(record: AttendanceRecord) -> dict | None:
    for key in (record.user_email, record.user_name, record.user_id):
        if not key:
            continue
        schedule = get_user_schedule(str(key).lower())
        if schedule:
            return schedule
    return None


def _resolve_schedule_start(record: AttendanceRecord) -> str | None:
    schedule = _lookup_schedule(record)
    if not schedule:
        return None
    return schedule.get('start_time') or schedule.get('plan_start')


def _is_weekend_worker(record: AttendanceRecord) -> bool:
    schedule = _lookup_schedule(record)
    if not schedule:
        return False
    pf_id = schedule.get('peopleforce_id')
    try:
        pf_int = int(pf_id)
    except (TypeError, ValueError):
        return False
    return pf_int in SEVEN_DAY_WORK_WEEK_IDS


def collect_lateness_for_date(target_date: date, *, include_absent: bool = True, skip_weekends: bool = False) -> int:
    logger.info(f"Starting lateness collection for {target_date}, include_absent={include_absent}, skip_weekends={skip_weekends}")
    monitor = AttendanceMonitor()
    performed = _ensure_attendance_data(monitor, target_date, include_absent, skip_weekends)
    if not performed:
        logger.info(f"Skipped {target_date} (weekend)")
        return 0

    try:
        records = _load_lateness_records(target_date)
        logger.info(f"Loaded {len(records)} lateness records from AttendanceRecord for {target_date}")
        
        deleted = LatenessRecord.query.filter_by(record_date=target_date).delete()
        logger.info(f"Deleted {deleted} existing lateness records for {target_date}")
        inserted = 0

        is_weekend = target_date.weekday() >= 5
        for record in records:
            if is_weekend and not _is_weekend_worker(record):
                continue
            # Пропускаємо записи без реального запізнення
            if record.status == 'late':
                minutes = record.minutes_late or 0
                if minutes <= 0:
                    continue
            scheduled_start = record.scheduled_start or ''
            if not scheduled_start or scheduled_start == '00:00':
                schedule_start = _resolve_schedule_start(record)
                if schedule_start:
                    scheduled_start = schedule_start

            db.session.add(
                LatenessRecord(
                    record_date=record.record_date,
                    user_name=record.user_name,
                    user_email=record.user_email,
                    user_id=record.user_id,
                    project=record.project,
                    department=record.department,
                    team=record.team,
                    location=record.location,
                    scheduled_start=scheduled_start or record.scheduled_start,
                    actual_start=record.actual_start,
                    minutes_late=record.minutes_late if record.minutes_late and record.minutes_late > 0 else 0,
                    status=record.status,
                    control_manager=record.control_manager,
                    leave_reason=record.leave_reason,
                )
            )
            inserted += 1

        db.session.commit()
        logger.info(f"Successfully saved {inserted} lateness records for {target_date}")
        return inserted
    except Exception as exc:
        logger.error(f"Failed to collect lateness for {target_date}: {exc}", exc_info=True)
        db.session.rollback()
        raise LatenessCollectorError(str(exc)) from exc
