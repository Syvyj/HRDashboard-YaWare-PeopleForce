"""
Форматирование отчетов для Telegram.
"""
from datetime import date
from typing import Dict, List, Optional, Tuple
from .attendance_monitor import AttendanceStatus


def format_attendance_report(report: dict, report_date: str | None = None, leaves_list: list | None = None) -> str:
    """
    Форматировать отчет о присутствии для Telegram.
    
    Args:
        report: Словарь с данными отчета
        report_date: Опционально дата отчета (если не в report['date'])
        leaves_list: Список отпусков из PeopleForce API
    Returns:
        Відформатоване повідомлення
    """
    date_str = report.get('date') or (report_date.isoformat() if report_date else date.today().isoformat())
    late_users = report['late']
    absent_users = report['absent']
    total = report['total_issues']
    
    if total == 0:
        return f"✅ Отчет за {date_str}\n\nВсе сотрудники вовремя! 🎉"
    
    def format_minutes(minutes: int) -> str:
        """Конвертувати хвилини в формат години:хвилини."""
        hours = minutes // 60
        mins = minutes % 60
        if hours > 0:
            return f"{hours}:{mins:02d}"
        return f"0:{mins:02d}"
    
    lines = [
        "=" * 40,
        f"📊 ОТЧЕТ ПО ОПОЗДАНИЯМ за {date_str}",
        "=" * 40,
        ""
    ]
    
    def build_group_key(status: AttendanceStatus) -> Tuple[str, str, str]:
        return (
            status.user.project or "—",
            status.user.department or "—",
            status.user.team or "—"
        )

    def format_group_header(project: str, department: str, team: str) -> str:
        parts = [project]
        if department and department != "—":
            parts.append(department)
        if team and team != "—":
            parts.append(team)
        header = " / ".join(parts)
        return header or "—"

    def group_statuses(statuses: List[AttendanceStatus]) -> Dict[Tuple[str, str, str], List[AttendanceStatus]]:
        grouped: Dict[Tuple[str, str, str], List[AttendanceStatus]] = {}
        for status in statuses:
            key = build_group_key(status)
            grouped.setdefault(key, []).append(status)
        return grouped

    # Спізнились
    if late_users:
        lines.append(f"⚠️ Опоздали ({len(late_users)} чел):")
        lines.append("-" * 40)
        grouped_late = group_statuses(late_users)
        for key in sorted(grouped_late.keys()):
            header = format_group_header(*key)
            for status in sorted(grouped_late[key], key=lambda s: s.user.name):
                lines.append(f"🔹 **{status.user.name}**")
                lines.append(f"   • {header}")
                if status.user.location:
                    lines.append(f"     📍 {status.user.location}")
                lines.append(
                    f"     ⏰ График: {status.expected_time} | Пришел: {status.actual_time}"
                )
                lines.append(f"     ⏱️ Опоздание: {format_minutes(status.minutes_late)} ч")
            lines.append("")
    
        # Добавляем блок PeopleForce (отсутствующие по уважительным причинам)
    if leaves_list:
        lines.append(f"✅ Отсутствуют (уважительные причины) ({len(leaves_list)} чел):")
        lines.append("-" * 40)
        
        for leave in leaves_list:
            # Получаем имя сотрудника
            employee_data = leave.get("employee", {})
            if isinstance(employee_data, dict):
                first_name = employee_data.get("first_name", "")
                last_name = employee_data.get("last_name", "")
                name = f"{first_name} {last_name}".strip() or "Unknown"
            else:
                name = str(employee_data)
            
            # leave_type може бути string або dict
            leave_type_data = leave.get("leave_type", "Неизвестно")
            if isinstance(leave_type_data, dict):
                leave_type_name = leave_type_data.get("name", "Неизвестно")
            else:
                leave_type_name = str(leave_type_data)
            
            lines.append(f"� **{name}**")
            lines.append(f"   📄 Причина: {leave_type_name}")
            lines.append("")
    
    # Відсутні без причини
    if absent_users:
        lines.append(f"❌ Отсутствуют без причины ({len(absent_users)} чел):")
        lines.append("-" * 40)
        grouped_absent = group_statuses(absent_users)
        for key in sorted(grouped_absent.keys()):
            header = format_group_header(*key)
            for status in sorted(grouped_absent[key], key=lambda s: s.user.name):
                lines.append(f"🔹 **{status.user.name}**")
                lines.append(f"   • {header}")
                if status.user.location:
                    lines.append(f"     📍 {status.user.location}")
                if status.expected_time:
                    lines.append(f"     ⏰ График: {status.expected_time}")
            lines.append("")
    
    return "\n".join(lines)


def format_short_summary(report: Dict) -> str:
    """Короткий саммарі для швидкого перегляду."""
    total = report['total_issues']
    late_count = len(report['late'])
    absent_count = len(report['absent'])
    
    if total == 0:
        return "✅ Все вовремя"
    
    parts = []
    if late_count:
        parts.append(f"⚠️ {late_count} опоздали")
    if absent_count:
        parts.append(f"❌ {absent_count} отсутствуют")
    
    return " | ".join(parts)
