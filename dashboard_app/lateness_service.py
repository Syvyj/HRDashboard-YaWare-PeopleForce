from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Iterable

from dashboard_app.extensions import db
from dashboard_app.models import LatenessRecord
from dashboard_app.constants import SEVEN_DAY_WORK_WEEK_IDS
from tracker_alert.services.attendance_monitor import AttendanceMonitor
from tracker_alert.client.yaware_v2_api import client as yaware_client

logger = logging.getLogger(__name__)


class LatenessCollectorError(Exception):
    """Raised when lateness collection fails."""


def _normalize_time(value: str | None) -> str:
    """Нормалізує час до формату HH:MM."""
    if not value:
        return ''
    text = str(value).strip()
    if not text:
        return ''
    # Спробувати розпарсити з різними форматами
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).strftime('%H:%M')
        except ValueError:
            continue
    return text


def _time_to_minutes(time_str: str | None) -> int | None:
    """Конвертує час HH:MM в хвилини від початку дня."""
    if not time_str:
        return None
    try:
        dt = datetime.strptime(time_str, '%H:%M')
        return dt.hour * 60 + dt.minute
    except ValueError:
        return None


def _calculate_lateness(actual_start: str | None, scheduled_start: str | None) -> int:
    """Розраховує кількість хвилин запізнення."""
    actual_min = _time_to_minutes(actual_start)
    scheduled_min = _time_to_minutes(scheduled_start)
    if actual_min is None or scheduled_min is None:
        return 0
    diff = actual_min - scheduled_min
    return diff if diff > 0 else 0


def _fetch_lateness_data_from_yaware(target_date: date, monitor: AttendanceMonitor) -> list[dict]:
    """
    Отримує дані про запізнення з YaWare та PeopleForce.
    НЕ чіпає attendance_records - це окрема система!
    """
    # Отримуємо графіки з user_schedules.json
    schedules_by_id = monitor.schedules
    schedules_by_email = monitor.schedules_by_email
    
    # Отримуємо відпустки з PeopleForce
    leaves_raw = monitor._get_leaves_for_date(target_date)
    leaves_reason = {}
    for email, leave in leaves_raw.items():
        leave_type = leave.get('leave_type', '')
        if isinstance(leave_type, dict):
            leave_type = leave_type.get('name', '')
        leaves_reason[email.lower()] = leave_type or 'Отпуск'
    
    # Отримуємо дані з YaWare
    try:
        summary = yaware_client.get_summary_by_day(target_date.isoformat()) or []
        logger.info(f"Got {len(summary)} entries from YaWare for {target_date}")
    except Exception as e:
        logger.error(f"Failed to get YaWare data for {target_date}: {e}")
        summary = []
    
    results = []
    skipped_no_schedule = 0
    skipped_no_scheduled_start = 0
    skipped_no_actual_start = 0
    skipped_early = 0
    
    for entry in summary:
        user_id = str(entry.get('user_id', ''))
        
        # Витягуємо email з поля 'user' (формат: "Name, email@domain.com")
        email = ''
        user_field = entry.get('user', '')
        if isinstance(user_field, str) and ',' in user_field:
            email = user_field.split(',')[1].strip().lower()
        
        # Знаходимо графік
        schedule = schedules_by_id.get(user_id) or schedules_by_email.get(email)
        if not schedule:
            skipped_no_schedule += 1
            continue
        
        # Беремо ім'я та email зі schedule (пріоритет над YaWare)
        user_name = getattr(schedule, 'name', '') or entry.get('name', '')
        if not email and hasattr(schedule, 'email') and schedule.email:
            email = schedule.email.lower()
        
        scheduled_start = getattr(schedule, 'start_time', None)
        if not scheduled_start:
            skipped_no_scheduled_start += 1
            continue
        
        # Отримуємо фактичний старт з YaWare summary (time_start)
        actual_start = _normalize_time(entry.get('time_start', ''))
        
        # Перевіряємо чи є відпустка/лікарняний
        leave_reason = leaves_reason.get(email, '')
        
        # Якщо немає фактичного старту - користувач відсутній
        if not actual_start or actual_start == '00:00':
            skipped_no_actual_start += 1
            # Додаємо тільки якщо є причина відсутності
            if leave_reason:
                results.append({
                    'user_id': user_id,
                    'user_email': email,
                    'user_name': user_name,
                    'project': getattr(schedule, 'project', ''),
                    'department': getattr(schedule, 'department', ''),
                    'team': getattr(schedule, 'team', ''),
                    'location': getattr(schedule, 'location', ''),
                    'scheduled_start': scheduled_start,
                    'actual_start': None,
                    'minutes_late': 0,
                    'status': 'absent',
                    'control_manager': getattr(schedule, 'control_manager', ''),
                    'leave_reason': leave_reason,
                })
            continue
        
        # Перевіряємо чи це людина з 24/7 графіком (для них не треба рахувати запізнення)
        pf_id = getattr(schedule, 'peopleforce_id', None)
        is_24_7_worker = False
        if pf_id:
            try:
                is_24_7_worker = int(pf_id) in SEVEN_DAY_WORK_WEEK_IDS
            except (TypeError, ValueError):
                pass
        
        if is_24_7_worker:
            skipped_early += 1
            continue
        
        # Якщо є відпустка - показуємо як відсутнього (навіть якщо увімкнув комп'ютер)
        if leave_reason:
            results.append({
                'user_id': user_id,
                'user_email': email,
                'user_name': user_name,
                'project': getattr(schedule, 'project', ''),
                'department': getattr(schedule, 'department', ''),
                'team': getattr(schedule, 'team', ''),
                'location': getattr(schedule, 'location', ''),
                'scheduled_start': scheduled_start,
                'actual_start': actual_start,
                'minutes_late': 0,
                'status': 'absent',
                'control_manager': getattr(schedule, 'control_manager', ''),
                'leave_reason': leave_reason,
            })
            continue
        
        # Розраховуємо запізнення
        minutes_late = _calculate_lateness(actual_start, scheduled_start)
        if minutes_late > 0:
            results.append({
                'user_id': user_id,
                'user_email': email,
                'user_name': user_name,
                'project': getattr(schedule, 'project', ''),
                'department': getattr(schedule, 'department', ''),
                'team': getattr(schedule, 'team', ''),
                'location': getattr(schedule, 'location', ''),
                'scheduled_start': scheduled_start,
                'actual_start': actual_start,
                'minutes_late': minutes_late,
                'status': 'late',
                'control_manager': getattr(schedule, 'control_manager', ''),
                'leave_reason': None,
            })
        else:
            skipped_early += 1
    
    logger.info(f"Processing summary: skipped {skipped_no_schedule} (no schedule), "
                f"{skipped_no_scheduled_start} (no scheduled_start), "
                f"{skipped_no_actual_start} (no actual_start), "
                f"{skipped_early} (came early). Found {len(results)} lateness records.")
    
    return results


def collect_lateness_for_date(target_date: date, *, include_absent: bool = True, skip_weekends: bool = False) -> int:
    """
    Збирає дані про запізнення з YaWare та PeopleForce.
    ВАЖЛИВО: НЕ чіпає attendance_records - це окрема система!
    """
    logger.info(f"Starting lateness collection for {target_date}, include_absent={include_absent}, skip_weekends={skip_weekends}")
    
    if skip_weekends and target_date.weekday() >= 5:
        logger.info(f"Skipped {target_date} (weekend)")
        return 0

    try:
        # Створюємо AttendanceMonitor для доступу до user_schedules.json та PeopleForce
        monitor = AttendanceMonitor()
        
        # Отримуємо дані про запізнення безпосередньо з YaWare та PeopleForce
        lateness_data = _fetch_lateness_data_from_yaware(target_date, monitor)
        logger.info(f"Fetched {len(lateness_data)} lateness records from YaWare for {target_date}")
        
        # Видаляємо старі записи про запізнення
        deleted = LatenessRecord.query.filter_by(record_date=target_date).delete()
        logger.info(f"Deleted {deleted} existing lateness records for {target_date}")
        
        inserted = 0
        is_weekend = target_date.weekday() >= 5
        
        for data in lateness_data:
            # Пропускаємо відсутніх, якщо не потрібно
            if data['status'] == 'absent' and not include_absent:
                continue
            
            # Перевіряємо чи працює в вихідні
            if is_weekend:
                schedule = monitor.schedules.get(data['user_id'])
                if schedule:
                    pf_id = getattr(schedule, 'peopleforce_id', None)
                    try:
                        pf_int = int(pf_id)
                        if pf_int not in SEVEN_DAY_WORK_WEEK_IDS:
                            continue
                    except (TypeError, ValueError):
                        continue
                else:
                    continue
            
            db.session.add(
                LatenessRecord(
                    record_date=target_date,
                    user_name=data['user_name'],
                    user_email=data['user_email'],
                    user_id=data['user_id'],
                    project=data['project'],
                    department=data['department'],
                    team=data['team'],
                    location=data['location'],
                    scheduled_start=data['scheduled_start'],
                    actual_start=data['actual_start'],
                    minutes_late=data['minutes_late'],
                    status=data['status'],
                    control_manager=data['control_manager'],
                    leave_reason=data['leave_reason'],
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
