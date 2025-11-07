"""Модуль для генерації звітів про запізнення та робочий час"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict

from tracker_alert.client.yaware_v2_api import client as yaware_client
from tracker_alert.client.peopleforce_api import PeopleForceClient
from tracker_alert.domain.schedules import schedule_manager

logger = logging.getLogger(__name__)


class AttendanceReport:
    """Генератор звітів про присутність та запізнення."""
    
    def __init__(self):
        self.pf_client = PeopleForceClient()
        self._pf_map: Optional[Dict[str, Any]] = None
    
    def _get_peopleforce_map(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Отримати мапінг email -> PeopleForce дані."""
        if self._pf_map is None or force_refresh:
            employees = self.pf_client.get_employees()
            self._pf_map = {emp['email']: emp for emp in employees}
            logger.info(f"Завантажено {len(self._pf_map)} співробітників з PeopleForce")
        return self._pf_map
    
    def _parse_user_data(self, yaware_record: Dict[str, Any]) -> Dict[str, Any]:
        """Розпарсити дані користувача з YaWare."""
        user_full = yaware_record.get("user", "")
        
        if ", " in user_full:
            name = user_full.split(", ")[0]
            email = user_full.split(", ")[1]
        else:
            name = user_full
            email = ""
        
        time_start = str(yaware_record.get("time_start") or '').strip()
        time_end = str(yaware_record.get("time_end") or '').strip()
        return {
            "name": name,
            "email": email,
            "department": yaware_record.get("group", ""),
            "time_start": time_start,
            "time_end": time_end,
            "total_seconds": int(yaware_record.get("total", 0)),
            "productive_seconds": int(yaware_record.get("productive", 0)),
            "distracting_seconds": int(yaware_record.get("distracting", 0)),
            "uncategorized_seconds": int(yaware_record.get("uncategorized", 0)),
        }
    
    def _get_location(self, email: str) -> Optional[str]:
        """Отримати локацію користувача з PeopleForce."""
        pf_map = self._get_peopleforce_map()
        pf_data = pf_map.get(email)
        
        if pf_data:
            location_obj = pf_data.get("location")
            if location_obj and isinstance(location_obj, dict):
                return location_obj.get("name")
        return None
    
    def _get_leave_status(self, email: str, date: str) -> Optional[Dict[str, Any]]:
        """Перевірити чи користувач у відпустці."""
        from datetime import datetime
        date_obj = datetime.fromisoformat(date).date() if isinstance(date, str) else date
        leave = self.pf_client.get_employee_leave_on_date(email, date_obj)
        return leave
    
    def _format_time(self, seconds: int) -> str:
        """Форматувати секунди в HH:MM."""
        if not seconds:
            return "00:00"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"
    
    def generate_daily_report(self, date: str = None) -> Dict[str, Any]:
        """
        Згенерувати повний звіт за день.
        
        Args:
            date: Дата у форматі YYYY-MM-DD (якщо None - сьогодні)
            
        Returns:
            Словник з повною інформацією про присутність
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        logger.info(f"Генеруємо звіт за {date}...")
        
        # Отримуємо дані з YaWare
        yaware_data = yaware_client.get_summary_by_day(date)
        logger.info(f"Отримано {len(yaware_data)} записів з YaWare")
        
        # Завантажуємо PeopleForce дані
        self._get_peopleforce_map()
        
        # Структура для звіту
        report = {
            "date": date,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_users": 0,
                "users_worked": 0,
                "users_late": 0,
                "users_left_early": 0,
                "users_on_leave": 0,
                "users_absent": 0
            },
            "by_schedule": {},
            "late_users": [],
            "early_leave_users": [],
            "on_leave": [],
            "absent_users": [],
            "top_productive": [],
            "needs_attention": []
        }
        
        # Обробляємо кожного користувача
        users_by_schedule = defaultdict(list)
        
        for record in yaware_data:
            user_data = self._parse_user_data(record)
            email = user_data["email"]
            
            if not email:
                continue
            
            # Локація та графік
            location = self._get_location(email)
            schedule = schedule_manager.get_schedule_for_user(
                email=email,
                location=location,
                department=user_data["department"]
            )
            
            # Статус відпустки
            leave_status = self._get_leave_status(email, date)
            
            # Повна інформація про користувача
            user_info = {
                **user_data,
                "location": location,
                "schedule_id": schedule.get("schedule_id"),
                "schedule_name": schedule.get("name"),
                "expected_start": schedule.get("start_time"),
                "expected_end": schedule.get("end_time"),
                "on_leave": leave_status is not None,
                "leave_type": leave_status.get("leave_type") if leave_status else None,
                "is_late": False,
                "minutes_late": 0,
                "left_early": False,
                "minutes_early": 0,
                "total_formatted": self._format_time(user_data["total_seconds"]),
                "productive_formatted": self._format_time(user_data["productive_seconds"])
            }
            
            # Перевіряємо запізнення (якщо не у відпустці і є час початку)
            actual_start = (user_data["time_start"] or "").strip()
            if not user_info["on_leave"] and actual_start and actual_start != "—":
                if schedule.get("start_time"):
                    is_late, minutes_late = schedule_manager.is_late(
                        actual_start,
                        email,
                        location,
                        user_data["department"]
                    )
                    user_info["is_late"] = is_late
                    user_info["minutes_late"] = minutes_late
                    
                    if is_late:
                        report["late_users"].append(user_info)
                        report["summary"]["users_late"] += 1
            
            # Перевіряємо раннє завершення
            actual_end = (user_data["time_end"] or "").strip()
            if not user_info["on_leave"] and actual_end and actual_end != "—":
                if schedule.get("end_time"):
                    left_early, minutes_early = schedule_manager.left_early(
                        actual_end,
                        email,
                        location,
                        user_data["department"]
                    )
                    user_info["left_early"] = left_early
                    user_info["minutes_early"] = minutes_early
                    
                    if left_early:
                        report["early_leave_users"].append(user_info)
                        report["summary"]["users_left_early"] += 1
            
            # Групуємо по графіках
            schedule_id = user_info["schedule_id"]
            users_by_schedule[schedule_id].append(user_info)
            
            # Статистика
            report["summary"]["total_users"] += 1
            
            if user_info["on_leave"]:
                report["on_leave"].append(user_info)
                report["summary"]["users_on_leave"] += 1
            elif user_data["total_seconds"] > 0:
                report["summary"]["users_worked"] += 1
            
            # Топ продуктивних (більше 6 годин продуктивного часу)
            if user_data["productive_seconds"] > 6 * 3600:
                report["top_productive"].append(user_info)
            
            # Потребують уваги (працювали мало або багато відволікань)
            if not user_info["on_leave"]:
                if user_data["total_seconds"] < 4 * 3600:  # Менше 4 годин
                    user_info["attention_reason"] = "Мало відпрацьовано"
                    report["needs_attention"].append(user_info)
                elif user_data["distracting_seconds"] > user_data["productive_seconds"]:
                    user_info["attention_reason"] = "Більше відволікань ніж продуктивного часу"
                    report["needs_attention"].append(user_info)
        
        # Сортуємо списки
        report["late_users"].sort(key=lambda x: x["minutes_late"], reverse=True)
        report["early_leave_users"].sort(key=lambda x: x["minutes_early"], reverse=True)
        report["top_productive"].sort(key=lambda x: x["productive_seconds"], reverse=True)
        
        # Статистика по графіках
        for schedule_id, users in users_by_schedule.items():
            schedule_info = schedule_manager.get_all_schedules().get(schedule_id, {})
            
            late_count = sum(1 for u in users if u["is_late"])
            on_leave_count = sum(1 for u in users if u["on_leave"])
            worked_count = sum(1 for u in users if u["total_seconds"] > 0 and not u["on_leave"])
            
            report["by_schedule"][schedule_id] = {
                "name": schedule_info.get("name", schedule_id),
                "start_time": schedule_info.get("start_time"),
                "end_time": schedule_info.get("end_time"),
                "total_users": len(users),
                "worked": worked_count,
                "late": late_count,
                "on_leave": on_leave_count,
                "late_percentage": (late_count / len(users) * 100) if users else 0
            }
        
        logger.info(f"✅ Звіт згенеровано: {report['summary']['total_users']} користувачів")
        
        return report
    
    def format_report_text(self, report: Dict[str, Any], detailed: bool = True) -> str:
        """
        Відформатувати звіт у текстовий вигляд.
        
        Args:
            report: Звіт від generate_daily_report()
            detailed: Чи показувати детальну інформацію
            
        Returns:
            Текстове представлення звіту
        """
        lines = []
        
        # Заголовок
        date_obj = datetime.strptime(report["date"], "%Y-%m-%d")
        date_formatted = date_obj.strftime("%d.%m.%Y (%A)")
        
        lines.append("="*80)
        lines.append(f"📊 ЗВІТ ПРО ПРИСУТНІСТЬ ТА ЗАПІЗНЕННЯ")
        lines.append(f"📅 Дата: {date_formatted}")
        lines.append("="*80)
        lines.append("")
        
        # Загальна статистика
        summary = report["summary"]
        lines.append("📈 ЗАГАЛЬНА СТАТИСТИКА:")
        lines.append("")
        lines.append(f"  👥 Всього користувачів: {summary['total_users']}")
        lines.append(f"  ✅ Працювали: {summary['users_worked']}")
        lines.append(f"  ⏰ Запізнилися: {summary['users_late']}")
        lines.append(f"  🏃 Пішли раніше: {summary['users_left_early']}")
        lines.append(f"  🏖️ У відпустці: {summary['users_on_leave']}")
        lines.append("")
        
        # Статистика по графіках
        lines.append("📊 ПО ГРАФІКАХ РОБОТИ:")
        lines.append("")
        
        for schedule_id, stats in sorted(report["by_schedule"].items()):
            lines.append(f"  📅 {stats['name']}")
            if stats['start_time']:
                lines.append(f"     Графік: {stats['start_time']} - {stats['end_time']}")
            lines.append(f"     Користувачів: {stats['total_users']}")
            lines.append(f"     Працювали: {stats['worked']}")
            lines.append(f"     Запізнилися: {stats['late']} ({stats['late_percentage']:.1f}%)")
            lines.append(f"     У відпустці: {stats['on_leave']}")
            lines.append("")
        
        # Запізнення
        if report["late_users"]:
            lines.append("="*80)
            lines.append(f"⏰ ЗАПІЗНИЛИСЯ ({len(report['late_users'])} осіб):")
            lines.append("="*80)
            lines.append("")
            
            # Групуємо по графіках
            late_by_schedule = defaultdict(list)
            for user in report["late_users"]:
                late_by_schedule[user["schedule_id"]].append(user)
            
            for schedule_id, users in late_by_schedule.items():
                schedule_name = users[0]["schedule_name"]
                expected = users[0]["expected_start"]
                
                lines.append(f"📅 {schedule_name} (очікуваний початок: {expected})")
                lines.append("")
                
                for i, user in enumerate(users[:20], 1):  # Топ-20
                    lines.append(f"  {i}. {user['name']}")
                    lines.append(f"     📧 {user['email']}")
                    lines.append(f"     📍 {user['location'] or 'Unknown'}")
                    lines.append(f"     🏢 {user['department']}")
                    lines.append(f"     ⏰ Початок: {user['time_start']} (запізнення: {user['minutes_late']} хв)")
                    lines.append(f"     ⏱️ Відпрацьовано: {user['total_formatted']}")
                    lines.append("")
                
                if len(users) > 20:
                    lines.append(f"  ... та ще {len(users) - 20} осіб")
                    lines.append("")
        
        # Відпустки
        if report["on_leave"] and detailed:
            lines.append("="*80)
            lines.append(f"🏖️ У ВІДПУСТЦІ ({len(report['on_leave'])} осіб):")
            lines.append("="*80)
            lines.append("")
            
            for user in report["on_leave"][:10]:
                lines.append(f"  • {user['name']} ({user['email']})")
                lines.append(f"    Тип: {user['leave_type']}")
                lines.append("")
        
        # Потребують уваги
        if report["needs_attention"] and detailed:
            lines.append("="*80)
            lines.append(f"⚠️ ПОТРЕБУЮТЬ УВАГИ ({len(report['needs_attention'])} осіб):")
            lines.append("="*80)
            lines.append("")
            
            for user in report["needs_attention"][:10]:
                lines.append(f"  • {user['name']} ({user['email']})")
                lines.append(f"    Причина: {user['attention_reason']}")
                lines.append(f"    Відпрацьовано: {user['total_formatted']}")
                lines.append("")
        
        lines.append("="*80)
        lines.append(f"✅ Звіт згенеровано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("="*80)
        
        return "\n".join(lines)


# Глобальний інстанс генератора звітів
report_generator = AttendanceReport()
