"""
Сервіс моніторингу присутності співробітників.
Інтеграція YaWare + PeopleForce для виявлення запізнень.
"""
from __future__ import annotations
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from ..client.yaware_v2_api import YaWareV2Client
from ..client.peopleforce_api import get_peopleforce_client

logger = logging.getLogger(__name__)

LOCATION_REPLACEMENTS = {
    "remote ukraine": "UA",
    "remote other countries": "Remote",
}


def _normalize_location(value: Optional[str]) -> str:
    if not value:
        return ""
    stripped = value.strip()
    if not stripped:
        return ""
    replacement = LOCATION_REPLACEMENTS.get(stripped.casefold())
    return replacement if replacement is not None else stripped


@dataclass
class UserSchedule:
    """График пользователя из базы."""
    name: str
    email: str
    user_id: str
    start_time: str
    location: str
    project: str = ""
    department: str = ""
    team: str = ""
    control_manager: Optional[int] = None
    exclude_from_reports: bool = False
    note: Optional[str] = None


@dataclass
class AttendanceStatus:
    """Статус присутствия пользователя."""
    user: UserSchedule
    status: str  # 'on_leave', 'late', 'absent', 'on_time', 'early'
    actual_time: Optional[str] = None
    expected_time: Optional[str] = None
    minutes_late: int = 0
    leave_info: Optional[dict] = None


class AttendanceMonitor:
    """Моніторинг присутності співробітників."""
    
    # Grace period - дозволене запізнення
    GRACE_PERIOD_MINUTES = 15
    
    def __init__(self, schedules_path: str = "config/user_schedules.json"):
        self.yaware_client = YaWareV2Client()
        self.pf_client = get_peopleforce_client()
        self.schedules, self.schedules_by_email = self._load_schedules(schedules_path)
    
    def _load_schedules(self, path: str) -> tuple[Dict[str, UserSchedule], Dict[str, UserSchedule]]:
        """Загрузить графики пользователей."""
        schedules: Dict[str, UserSchedule] = {}
        schedules_by_email: Dict[str, UserSchedule] = {}
        
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for name, user_data in data.get('users', {}).items():
            start_time = user_data.get('start_time') or ''
            
            control_manager = user_data.get('control_manager')
            if control_manager is not None:
                try:
                    control_manager = int(control_manager)
                except (TypeError, ValueError):
                    control_manager = None

            schedule = UserSchedule(
                name=name,
                email=user_data.get('email', ''),
                user_id=str(user_data.get('user_id', '')),
                start_time=start_time,
                location=_normalize_location(user_data.get('location', '')),
                project=user_data.get('project', '') or "",
                department=user_data.get('department', '') or "",
                team=user_data.get('team', '') or "",
                control_manager=control_manager,
                exclude_from_reports=user_data.get('exclude_from_reports', False),
                note=user_data.get('note')
            )
            
            # Фільтруємо виключених і нічні зміни
            if schedule.exclude_from_reports or schedule.note == 'Нічна зміна':
                continue
            
            schedules[schedule.user_id] = schedule
            email_key = schedule.email.lower()
            if email_key:
                schedules_by_email[email_key] = schedule

        logger.info(f"Загружено {len(schedules)} графиков пользователей")
        return schedules, schedules_by_email
    
    def _get_leaves_for_date(self, check_date: date) -> Dict[str, dict]:
        """
        Получить отпуска на конкретную дату.
        
        Returns:
            Dict[email, dict] где dict содержит:
            - leave_type: название типа отпуска
            - amount: 0.5 для половины дня, 1.0 для полного дня
            - все остальные поля из leave request
        """
        all_leaves = self.pf_client.get_leave_requests(
            start_date=check_date,
            end_date=check_date
        )
        
        leaves_by_email = {}
        for leave in all_leaves:
            emp_email = leave.get("employee", {}).get("email", "").lower()
            leave_start = date.fromisoformat(leave["starts_on"])
            leave_end = date.fromisoformat(leave["ends_on"])
            
            # Проверяем дата ли в периоде отпуска
            if leave_start <= check_date <= leave_end:
                # Ищем запись для конкретной даты в entries
                entries = leave.get("entries", [])
                amount = 1.0  # по умолчанию полный день
                
                for entry in entries:
                    entry_date_str = entry.get("date", "")
                    if entry_date_str:
                        entry_date = date.fromisoformat(entry_date_str)
                        if entry_date == check_date:
                            amount = float(entry.get("amount", 1.0))
                            break
                
                leave_with_amount = leave.copy()
                leave_with_amount["amount"] = amount
                leaves_by_email[emp_email] = leave_with_amount
        
        logger.info(f"Знайдено {len(leaves_by_email)} відсутностей на {check_date}")
        return leaves_by_email
    
    def _calculate_lateness(self, actual: str, expected: str) -> int:
        """Розрахувати запізнення в хвилинах."""
        if not actual or not expected:
            return 0
        try:
            actual_time = datetime.strptime(actual, "%H:%M")
            expected_time = datetime.strptime(expected, "%H:%M")
            diff = actual_time - expected_time
            return int(diff.total_seconds() / 60)
        except ValueError:
            return 0
    
    def check_attendance(self, check_date: date) -> List[AttendanceStatus]:
        """
        Проверить присутствие всех сотрудников на дату.
        
        Returns:
            Список статусів (тільки late та absent)
        """
        logger.info(f"Проверка присутствия на {check_date}")
        
        # Получаем данные
        yaware_data = self.yaware_client.get_summary_by_day(check_date.isoformat())
        yaware_by_id = {
            str(record['user_id']): record 
            for record in yaware_data 
            if 'user_id' in record
        }
        
        leaves_by_email = self._get_leaves_for_date(check_date)
        
        # Анализируем каждого пользователя
        results = []
        
        for user_id, schedule in self.schedules.items():
            email = schedule.email.lower() if schedule.email else ''
            
            # Пропускаем если в отпуске
            if email in leaves_by_email:
                continue
            
            # Проверяем наличие в YaWare
            yaware_record = yaware_by_id.get(user_id)
            
            if not yaware_record or not yaware_record.get('time_start'):
                # Відсутній без причини
                results.append(AttendanceStatus(
                    user=schedule,
                    status='absent',
                    expected_time=schedule.start_time
                ))
                continue
            
            # Сравниваем время прихода
            actual_time = yaware_record['time_start'][:5]  # HH:MM
            minutes_late = self._calculate_lateness(actual_time, schedule.start_time)
            
            # Враховуємо grace period
            if minutes_late > self.GRACE_PERIOD_MINUTES:
                results.append(AttendanceStatus(
                    user=schedule,
                    status='late',
                    actual_time=actual_time,
                    expected_time=schedule.start_time,
                    minutes_late=minutes_late
                ))
        
        logger.info(f"Знайдено проблем: {len(results)} (late: {sum(1 for r in results if r.status == 'late')}, absent: {sum(1 for r in results if r.status == 'absent')})")
        return results

    def get_daily_report(self, check_date: Optional[date] = None) -> Dict:
        """
        Получить ежедневный отчет о присутствии.
        
        Returns:
            Dict з категоріями late та absent
        """
        if check_date is None:
            check_date = date.today()
        
        statuses = self.check_attendance(check_date)
        
        return {
            'date': check_date.isoformat(),
            'late': [s for s in statuses if s.status == 'late'],
            'absent': [s for s in statuses if s.status == 'absent'],
            'total_issues': len(statuses)
        }

    def filter_report_by_managers(
        self,
        report: Dict,
        allowed_managers: Optional[List[int]],
        leaves_list: Optional[List[dict]] = None
    ) -> tuple[Dict, Optional[List[dict]]]:
        """Відфільтрувати звіт за списком контроль‑менеджерів."""
        if not allowed_managers:
            return report, leaves_list

        allowed_set = {int(mid) for mid in allowed_managers}

        def is_allowed(schedule: UserSchedule) -> bool:
            return schedule.control_manager is not None and schedule.control_manager in allowed_set

        filtered_late = [status for status in report['late'] if is_allowed(status.user)]
        filtered_absent = [status for status in report['absent'] if is_allowed(status.user)]

        filtered_report = {
            'date': report.get('date'),
            'late': filtered_late,
            'absent': filtered_absent,
            'total_issues': len(filtered_late) + len(filtered_absent)
        }

        filtered_leaves = leaves_list
        if leaves_list is not None:
            filtered_leaves = []
            for leave in leaves_list:
                employee = leave.get("employee", {})
                email = ""
                if isinstance(employee, dict):
                    email = employee.get("email", "")
                email = email.lower()
                schedule = self.schedules_by_email.get(email)
                if schedule and is_allowed(schedule):
                    filtered_leaves.append(leave)

        return filtered_report, filtered_leaves
