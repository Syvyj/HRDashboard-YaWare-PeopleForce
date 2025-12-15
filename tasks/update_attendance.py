from __future__ import annotations
import argparse
from datetime import date, timedelta, datetime
from typing import Dict, Tuple

from dashboard_app.extensions import db
from dashboard_app.models import AttendanceRecord
from tracker_alert.services.attendance_monitor import AttendanceMonitor
from tracker_alert.client.yaware_v2_api import client as yaware_client


def parse_args():
    parser = argparse.ArgumentParser(description='Обновить attendance данные в базе дашборда')
    parser.add_argument('--date', help='Дата в формате YYYY-MM-DD. По умолчанию вчера.')
    parser.add_argument('--start-date', help='Начальная дата для диапазона (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='Конечная дата для диапазона (YYYY-MM-DD)')
    parser.add_argument('--email', help='Email конкретного пользователя для синхронизации')
    parser.add_argument('--skip-absent', action='store_true', help='Не сохранять запись о отсутствующих.')
    return parser.parse_args()


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def time_to_minutes(value: str | None) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value, '%H:%M')
        return dt.hour * 60 + dt.minute
    except ValueError:
        return None


def seconds_to_minutes(value) -> int:
    if value in (None, ''):
        return 0
    try:
        return int(int(value) / 60)
    except (TypeError, ValueError):
        return 0


def minutes_to_diff(actual: str | None, scheduled: str | None) -> int:
    actual_minutes = time_to_minutes(actual)
    scheduled_minutes = time_to_minutes(scheduled)
    if actual_minutes is None or scheduled_minutes is None:
        return 0
    return actual_minutes - scheduled_minutes


def normalize_time(value: str | None) -> str:
    if not value:
        return ''
    text = str(value).strip()
    if not text:
        return ''
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).strftime('%H:%M')
        except ValueError:
            continue
    return text


def determine_status(minutes_late: int, has_data: bool, leave_reason: str | None) -> str:
    if leave_reason:
        return 'leave'
    if not has_data:
        return 'absent'
    if minutes_late > AttendanceMonitor.GRACE_PERIOD_MINUTES:
        return 'late'
    return 'present'


MANUAL_FIELD_ATTRS = {
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


def _record_key_from_values(user_id: str | None, email: str | None, user_name: str | None) -> str:
    for value in (user_id, email, user_name):
        if value:
            lowered = str(value).strip().lower()
            if lowered:
                return lowered
    return ''


def _extract_manual_overrides(record: AttendanceRecord) -> dict | None:
    manual_values = {}
    manual_flags: list[str] = []
    for field, flag_attr in MANUAL_FIELD_ATTRS.items():
        if getattr(record, flag_attr, False):
            manual_flags.append(flag_attr)
            manual_values[field] = getattr(record, field)
    if not manual_flags:
        return None
    return {
        'values': manual_values,
        'flags': manual_flags,
        'applied': False,
    }


def _resolve_manual_key(key: str, manual_map: dict[str, dict], alias_map: dict[str, str]) -> tuple[str | None, dict | None]:
    if not key:
        return None, None
    manual = manual_map.get(key)
    if manual:
        return key, manual
    canonical = alias_map.get(key)
    if canonical:
        manual = manual_map.get(canonical)
        if manual:
            return canonical, manual
    return None, None


def _apply_manual_overrides(record: AttendanceRecord, key: str, manual_map: dict[str, dict], alias_map: dict[str, str]) -> None:
    canonical_key, manual = _resolve_manual_key(key, manual_map, alias_map)
    if not manual:
        return
    values = manual.get('values', {})
    flags = manual.get('flags', [])
    for field, value in values.items():
        setattr(record, field, value)
    for flag_attr in flags:
        setattr(record, flag_attr, True)
    manual['applied'] = True
    if canonical_key:
        manual_map[canonical_key] = manual


def update_for_date(monitor: AttendanceMonitor, target_date: date, include_absent: bool) -> None:
    schedules_by_id: Dict[str, AttendanceMonitor.UserSchedule] = monitor.schedules
    schedules_by_email: Dict[str, AttendanceMonitor.UserSchedule] = monitor.schedules_by_email
    leaves_raw = monitor._get_leaves_for_date(target_date)  # email -> leave (with amount field)
    leaves_reason = {}
    leaves_amount = {}  # email -> amount (0.5 or 1.0)
    
    for email, leave in leaves_raw.items():
        leave_type = leave.get('leave_type', '')
        if isinstance(leave_type, dict):
            leave_type = leave_type.get('name', '')
        leaves_reason[email.lower()] = leave_type or 'Отпуск'
        leaves_amount[email.lower()] = leave.get('amount', 1.0)

    try:
        summary = yaware_client.get_summary_by_day(target_date.isoformat()) or []
    except Exception as e:
        print(f"[WARN] Не удалось получить данные YaWare за {target_date}: {e}")
        summary = []

    # Допоміжно тягнемо старт моніторингу з нового ендпоінта
    monitoring_start_by_id: dict[str, str] = {}
    day_index = target_date.weekday() + 1  # 1..7
    user_ids_for_monitoring: set[str] = set()
    for entry in summary:
        user_id_val = str(entry.get('user_id') or '').strip()
        if user_id_val:
            user_ids_for_monitoring.add(user_id_val)
    if user_ids_for_monitoring:
        monitoring_payload = yaware_client.get_begin_end_monitoring_by_employees(list(user_ids_for_monitoring)) or []
        for item in monitoring_payload:
            if not isinstance(item, dict):
                continue
            uid = str(item.get('user_id') or '').strip()
            if not uid:
                continue
            for day_info in item.get('data') or []:
                if str(day_info.get('day')) != str(day_index):
                    continue
                start_val = normalize_time(day_info.get('start_monitoring'))
                if start_val:
                    monitoring_start_by_id[uid] = start_val
                break

    existing_records = AttendanceRecord.query.filter_by(record_date=target_date).all()
    manual_overrides: dict[str, dict] = {}
    manual_aliases: dict[str, str] = {}
    for existing in existing_records:
        manual = _extract_manual_overrides(existing)
        if not manual:
            continue
        canonical_key = _record_key_from_values(existing.user_id, existing.user_email, existing.user_name)
        if not canonical_key:
            continue
        manual['snapshot'] = {
            'record_date': existing.record_date,
            'user_id': existing.user_id,
            'user_name': existing.user_name,
            'user_email': existing.user_email,
            'project': existing.project,
            'department': existing.department,
            'team': existing.team,
            'location': existing.location,
            'scheduled_start': existing.scheduled_start,
            'actual_start': existing.actual_start,
            'minutes_late': existing.minutes_late,
            'non_productive_minutes': existing.non_productive_minutes,
            'not_categorized_minutes': existing.not_categorized_minutes,
            'productive_minutes': existing.productive_minutes,
            'total_minutes': existing.total_minutes,
            'corrected_total_minutes': existing.corrected_total_minutes,
            'status': existing.status,
            'control_manager': existing.control_manager,
            'leave_reason': existing.leave_reason,
            'notes': existing.notes,
        }
        manual_overrides[canonical_key] = manual
        for alias in {
            (existing.user_email or '').strip().lower(),
            (existing.user_name or '').strip().lower(),
        }:
            if alias and alias != canonical_key:
                manual_aliases[alias] = canonical_key

    # Delete only daily records, preserve week_total records with notes
    AttendanceRecord.query.filter(
        AttendanceRecord.record_date == target_date,
        db.or_(
            AttendanceRecord.record_type == 'daily',
            AttendanceRecord.record_type.is_(None)
        )
    ).delete(synchronize_session=False)

    processed_ids = set()
    processed_emails = set()
    
    # Лічильник пропущених користувачів (показуються в адмін-панелі "Тільки в YaWare")
    skipped_count = 0

    for entry in summary:
        user_id = str(entry.get('user_id', ''))
        schedule = schedules_by_id.get(user_id)

        email = ''
        user_field = entry.get('user', '')
        if isinstance(user_field, str) and ',' in user_field:
            email = user_field.split(',')[1].strip().lower()
        elif schedule and schedule.email:
            email = schedule.email.lower()

        if not schedule and email:
            schedule = schedules_by_email.get(email)
        
        # ❌ КРИТИЧНО: Якщо користувача НЕМАЄ в нашій базі або він ignored/archived - пропускаємо!
        if not schedule or getattr(schedule, 'ignored', False) or getattr(schedule, 'archived', False):
            user_name = entry.get('user', '').split(',')[0].strip()
            skipped_count += 1
            continue  # Пропускаємо - НЕ ДОДАЄМО в БД автоматично!

        schedule_raw = entry.get('schedule')
        yaware_schedule = schedule_raw if isinstance(schedule_raw, dict) else {}
        schedule_start_yaware = normalize_time(yaware_schedule.get('start_time'))
        actual_start = normalize_time(entry.get('time_start'))

        # Пріоритет: новий ендпоінт моніторингу -> schedule з YaWare -> локальний графік
        monitoring_start = monitoring_start_by_id.get(user_id)
        scheduled_start = monitoring_start or schedule_start_yaware or (schedule.start_time if schedule else '')
        scheduled_start = normalize_time(scheduled_start)

        if schedule and scheduled_start:
            schedule.start_time = scheduled_start

        # Використовуємо Fact Start з YaWare без коригувань
        minutes_late = minutes_to_diff(actual_start, scheduled_start) if scheduled_start else 0

        non_productive = seconds_to_minutes(entry.get('distracting'))
        not_categorized = seconds_to_minutes(entry.get('uncategorized'))
        productive = seconds_to_minutes(entry.get('productive'))
        total_minutes = seconds_to_minutes(entry.get('total'))

        leave_reason = leaves_reason.get(email) if email else None
        leave_amount = leaves_amount.get(email) if email else None
        
        # Отримуємо internal_id зі schedule
        internal_user_id = schedule.internal_id if schedule and hasattr(schedule, 'internal_id') else None
        
        # Якщо є половина дня відпустки (0.5) - дозволяємо YaWare дані для іншої половини
        # Статус буде визначено як "present" або "late" незалежно від leave
        if leave_amount == 0.5:
            # Половина дня відпустки - зберігаємо і leave_reason, і YaWare дані
            status = determine_status(minutes_late, True, None)  # визначаємо без урахування leave
        else:
            # Повний день відпустки або немає відпустки
            status = determine_status(minutes_late, True, leave_reason)

        record = AttendanceRecord(
            record_date=target_date,
            internal_user_id=internal_user_id,
            user_id=user_id or email,
            user_name=schedule.name,
            user_email=schedule.email.lower() if schedule.email else None,
            project=schedule.project,
            department=schedule.department,
            team=schedule.team,
            location=schedule.location,
            scheduled_start=scheduled_start,
            actual_start=actual_start,
            minutes_late=max(minutes_late, 0),
            non_productive_minutes=non_productive,
            not_categorized_minutes=not_categorized,
            productive_minutes=productive,
            total_minutes=total_minutes or (non_productive + not_categorized + productive),
            status=status,
            control_manager=schedule.control_manager,
            leave_reason=leave_reason,
            half_day_amount=leave_amount,
            notes=schedule.note,
            pf_status=leave_reason if leave_reason else None
        )
        
        # Якщо відпустка або за свій рахунок (не половина дня) - обнуляємо actual_start і productive час
        if leave_reason and leave_amount != 0.5:
            record.actual_start = None
            record.productive_minutes = 0
            record.not_categorized_minutes = 0
            record.non_productive_minutes = 0
            record.total_minutes = 0
        
        record_key = _record_key_from_values(record.user_id, record.user_email, record.user_name)
        _apply_manual_overrides(record, record_key, manual_overrides, manual_aliases)
        db.session.add(record)
        if user_id:
            processed_ids.add(user_id)
        if email:
            processed_emails.add(email)

    # Leaves not present in summary
    for email, reason in leaves_reason.items():
        if email in processed_emails:
            continue
        schedule = schedules_by_email.get(email)
        if not schedule:
            continue
        
        leave_amount = leaves_amount.get(email, 1.0)
        
        # Отримуємо internal_id зі schedule
        internal_user_id = schedule.internal_id if hasattr(schedule, 'internal_id') else None
        
        # Якщо половина дня відпустки і немає YaWare даних - все одно створюємо запис
        # (можливо людина взяла відпустку на другу половину дня і не працювала)
        record = AttendanceRecord(
            record_date=target_date,
            internal_user_id=internal_user_id,
            user_id=schedule.user_id or schedule.email,
            user_name=schedule.name,
            user_email=schedule.email,
            project=schedule.project,
            department=schedule.department,
            team=schedule.team,
            location=schedule.location,
            scheduled_start=schedule.start_time,
            actual_start='',
            minutes_late=0,
            non_productive_minutes=0,
            not_categorized_minutes=0,
            productive_minutes=0,
            total_minutes=0,
            status='leave',
            control_manager=schedule.control_manager,
            leave_reason=reason,
            half_day_amount=leave_amount,
            notes=schedule.note,
            pf_status=reason if reason else None
        )
        record_key = _record_key_from_values(record.user_id, record.user_email, record.user_name)
        _apply_manual_overrides(record, record_key, manual_overrides, manual_aliases)
        db.session.add(record)
        processed_ids.add(schedule.user_id)

    if include_absent:
        for user_id, schedule in schedules_by_id.items():
            if user_id in processed_ids:
                continue
            if schedule.email and schedule.email.lower() in leaves_reason:
                continue
            
            # Отримуємо internal_id зі schedule
            internal_user_id = schedule.internal_id if hasattr(schedule, 'internal_id') else None
            
            record = AttendanceRecord(
                record_date=target_date,
                internal_user_id=internal_user_id,
                user_id=schedule.user_id or schedule.email,
                user_name=schedule.name,
                user_email=schedule.email,
                project=schedule.project,
                department=schedule.department,
                team=schedule.team,
                location=schedule.location,
                scheduled_start=schedule.start_time,
                actual_start='',
                minutes_late=0,
                non_productive_minutes=0,
                not_categorized_minutes=0,
                productive_minutes=0,
                total_minutes=0,
                status='absent',
                control_manager=schedule.control_manager,
                leave_reason=None,
                notes=schedule.note,
                pf_status=None
            )
            record_key = _record_key_from_values(record.user_id, record.user_email, record.user_name)
            _apply_manual_overrides(record, record_key, manual_overrides, manual_aliases)
            db.session.add(record)

    for manual in manual_overrides.values():
        if manual.get('applied'):
            continue
        snapshot = manual.get('snapshot')
        if not snapshot:
            continue
        record = AttendanceRecord(**snapshot)
        record_key = _record_key_from_values(record.user_id, record.user_email, record.user_name)
        _apply_manual_overrides(record, record_key, manual_overrides, manual_aliases)
        db.session.add(record)

    db.session.commit()
    print(f"[INFO] Сохранено за {target_date}")
    
    # Статистика пропущених користувачів (показуються в адмін-панелі "Тільки в YaWare")
    if skipped_count > 0:
        print(f"[WARN] Пропущено {skipped_count} користувачів з YaWare (немає в нашій базі)")


def main():
    args = parse_args()

    date_arg = parse_date(args.date)
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)

    if start_date and not end_date:
        end_date = start_date
    if end_date and not start_date:
        start_date = end_date

    if not date_arg and not start_date:
        date_arg = date.today() - timedelta(days=1)

    from dashboard_app import create_app
    app = create_app()
    with app.app_context():
        monitor = AttendanceMonitor()
        if date_arg and not start_date:
            update_for_date(monitor, date_arg, include_absent=not args.skip_absent)
        else:
            current = start_date
            while current <= end_date:
                update_for_date(monitor, current, include_absent=not args.skip_absent)
                current += timedelta(days=1)


if __name__ == '__main__':
    main()
