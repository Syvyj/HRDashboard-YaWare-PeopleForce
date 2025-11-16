from __future__ import annotations

import atexit
import logging
import re
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
SCHEDULER: BackgroundScheduler | None = None


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
    
    # Створюємо словник менеджерів для швидкого доступу
    managers_cache = {}
    
    # Перший проход - синхронізуємо всі дані
    for name, info in users.items():
        if not isinstance(info, dict):
            continue
        email = (info.get("email") or "").strip().lower()
        if not email:
            continue
        employee = employees_by_email.get(email)
        if not employee:
            continue

        # Оновлюємо project (DIVISION)
        project_obj = employee.get("division") or {}
        project_name = ""
        if isinstance(project_obj, dict):
            project_name = (project_obj.get("name") or "").strip()
        if project_name and not has_manual_override(info, "project") and info.get("project") != project_name:
            info["project"] = project_name
            updated = True
            logger.debug(f"Оновлено project (DIVISION) для {name}: {project_name}")

        # Оновлюємо department (DIRECTION/UNIT)
        department_obj = employee.get("department") or {}
        department_name = ""
        if isinstance(department_obj, dict):
            department_name = (department_obj.get("name") or "").strip()
        if department_name and not has_manual_override(info, "department") and info.get("department") != department_name:
            info["department"] = department_name
            updated = True
            logger.debug(f"Оновлено department (DIRECTION/UNIT) для {name}: {department_name}")
        
        # Синхронізуємо додаткові дані з PeopleForce (детальний запит)
        peopleforce_id = info.get("peopleforce_id")
        if peopleforce_id:
            try:
                detailed_data = client.get_employee_detail(peopleforce_id)
                if detailed_data:
                    # Отримуємо позицію
                    position_obj = detailed_data.get("position") or {}
                    position_name = ""
                    if isinstance(position_obj, dict):
                        position_name = (position_obj.get("name") or "").strip()
                    if position_name and info.get("position") != position_name:
                        info["position"] = position_name
                        updated = True
                        logger.debug(f"Оновлено position для {name}: {position_name}")
                    
                    # Отримуємо робочий телеграм з custom fields
                    fields = detailed_data.get("fields", {})
                    work_telegram_raw = fields.get("1", {}).get("value", "").strip() if isinstance(fields.get("1"), dict) else ""
                    work_telegram = _clean_telegram_username(work_telegram_raw)
                    
                    # Якщо знайдено робочий телеграм і він відрізняється
                    if work_telegram and info.get("telegram_username") != work_telegram:
                        info["telegram_username"] = work_telegram
                        updated = True
                        logger.debug(f"Оновлено telegram для {name}: {work_telegram}")
                    
                    # Отримуємо team_lead з custom fields
                    team_lead_field = fields.get("team_lead") or {}
                    team_lead_name = ""
                    if isinstance(team_lead_field, dict):
                        team_lead_name = (team_lead_field.get("value") or "").strip()
                    if team_lead_name and info.get("team_lead") != team_lead_name:
                        info["team_lead"] = team_lead_name
                        updated = True
                        logger.debug(f"Оновлено team_lead для {name}: {team_lead_name}")
                    
                    # Отримуємо дані про керівника
                    reporting_to = detailed_data.get("reporting_to")
                    if reporting_to and isinstance(reporting_to, dict):
                        manager_id = reporting_to.get("id")
                        
                        # Отримуємо детальні дані про керівника (використовуємо кеш)
                        if manager_id not in managers_cache:
                            manager_detail = client.get_employee_detail(manager_id)
                            if manager_detail:
                                manager_fields = manager_detail.get("fields", {})
                                manager_tg_raw = manager_fields.get("1", {}).get("value", "").strip() if isinstance(manager_fields.get("1"), dict) else ""
                                manager_tg = _clean_telegram_username(manager_tg_raw)
                                # Зберігаємо всі дані про керівника в кеш
                                managers_cache[manager_id] = {
                                    "first_name": reporting_to.get("first_name", ""),
                                    "last_name": reporting_to.get("last_name", ""),
                                    "telegram": manager_tg,
                                    "division": manager_detail.get("division", {}).get("name") if isinstance(manager_detail.get("division"), dict) else manager_detail.get("division"),
                                    "department": manager_detail.get("department", {}).get("name") if isinstance(manager_detail.get("department"), dict) else manager_detail.get("department"),
                                }
                        
                        manager_info = managers_cache.get(manager_id)
                        if manager_info:
                            # Формуємо ім'я керівника у форматі Прізвище_Ім'я
                            manager_name = f"{manager_info['last_name']}_{manager_info['first_name']}"
                            manager_telegram = manager_info['telegram']
                            
                            # Оновлюємо дані керівника якщо змінилися
                            if info.get("manager_name") != manager_name:
                                info["manager_name"] = manager_name
                                updated = True
                                logger.debug(f"Оновлено manager_name для {name}: {manager_name}")
                            
                            if manager_telegram and info.get("manager_telegram") != manager_telegram:
                                info["manager_telegram"] = manager_telegram
                                updated = True
                                logger.debug(f"Оновлено manager_telegram для {name}: {manager_telegram}")
                            
                            # Якщо у користувача нема DIRECTION/UNIT, беремо від team lead'а
                            if not info.get("department") and manager_info.get("department"):
                                info["department"] = manager_info["department"]
                                updated = True
                                logger.debug(f"Оновлено department для {name} (з team lead): {manager_info['department']}")
                    
            except Exception as e:
                logger.error(f"Помилка при синхронізації telegram/manager для {name}: {e}")
                continue

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
        logger.info("[scheduler] Updated schedule metadata from PeopleForce (including hierarchy and manager)")

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

    scheduler = BackgroundScheduler(timezone='UTC')
    # 10:15 UTC (12:15 Warsaw) - Синхронізація з YaWare за минулу добу (Mon-Fri)
    scheduler.add_job(lambda: _with_app_context(app, _run_daily_attendance), 
                      CronTrigger(hour=10, minute=15, day_of_week='mon-fri', timezone='UTC'),
                      id='daily_attendance_sync', replace_existing=True)
    # 10:17 UTC (12:17 Warsaw) - Синхронізація з PeopleForce + ієрархія (Mon-Fri)
    def sync_peopleforce_with_hierarchy():
        _sync_organizational_hierarchy(app)
        _sync_peopleforce_metadata(app)
    scheduler.add_job(lambda: _with_app_context(app, sync_peopleforce_with_hierarchy), 
                      CronTrigger(hour=10, minute=17, day_of_week='mon-fri', timezone='UTC'),
                      id='peopleforce_metadata_sync', replace_existing=True)
    # 1-го числа місяця о 03:15 UTC (05:15 Warsaw) - Ресинхронізація минулого місяця
    scheduler.add_job(lambda: _with_app_context(app, _run_prev_month_resync), 
                      CronTrigger(day="1", hour=3, minute=15, timezone='UTC'),
                      id='prev_month_resync', replace_existing=True)
    # Automatic cleanup disabled - keep all records indefinitely
    # scheduler.add_job(lambda: _with_app_context(app, _cleanup_old_records), CronTrigger(day="1", hour=5, minute=45),
    #                   id='cleanup_old_records', replace_existing=True)
    scheduler.start()

    _scheduler = scheduler
    global SCHEDULER
    SCHEDULER = scheduler
    atexit.register(lambda: scheduler.shutdown(wait=False))

    logger.info(
        "[scheduler] Background scheduler started (timezone: UTC):\n"
        "  - 10:15 UTC (12:15 Warsaw) - YaWare attendance sync (Mon-Fri)\n"
        "  - 10:17 UTC (12:17 Warsaw) - PeopleForce metadata + hierarchy sync (Mon-Fri)\n"
        "  - 03:15 UTC (05:15 Warsaw) on 1st day of month - Previous month resync"
    )
