"""Мапперы для преобразования v2 API данных в формат для Google Sheets."""
from __future__ import annotations
from typing import Any, Dict, List
from datetime import date


def seconds_to_hours(seconds: int) -> float:
    """Перетворити секунди в години (округлено до 2 знаків)."""
    return round(seconds / 3600, 2)


def seconds_to_hhmm(seconds: int) -> str:
    """Перетворити секунди в формат HH:MM."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


def parse_summary_by_day(
    record: Dict[str, Any],
    target_date: date
) -> Dict[str, Any]:
    """
    Преобразовать данные из getSummaryByDay в формат для Sheets.
    
    Args:
        record: Запись из getSummaryByDay
        target_date: Дата для которой данные
        
    Returns:
        Dictionary с данными для одной строки в Sheets
    """
    # Время в секундах (уже есть в response)
    total_seconds = int(record.get("total", 0))
    productive_seconds = int(record.get("productive", 0))
    uncategorized_seconds = int(record.get("uncategorized", 0))
    distracting_seconds = int(record.get("distracting", 0))
    
    # Конвертуємо в години
    total_h = seconds_to_hours(total_seconds)
    productive_h = seconds_to_hours(productive_seconds)
    uncategorized_h = seconds_to_hours(uncategorized_seconds)
    distracting_h = seconds_to_hours(distracting_seconds)
    
    # Парсимо ім'я (формат: "Name Surname, email@example.com")
    user_field = record.get("user", "")
    if ", " in user_field:
        full_name = user_field.split(", ")[0]
    else:
        full_name = user_field
    
    # Форматуємо дату як текст щоб Google Sheets не конвертувала в число
    # Використовуємо формат ДД.ММ.РРРР
    date_str = target_date.strftime("%d.%m.%Y")
    
    return {
        "date": date_str,  # Тепер це текст, не ISO формат
        "full_name": full_name,
        "group_name": record.get("group", ""),
        "fact_start": record.get("time_start", ""),  # ✅ Время начала!
        "non_productive_hours": distracting_h,
        "not_categorized_hours": uncategorized_h,
        "productive_hours": productive_h,
        "total_hours": total_h,
    }


def parse_worked_hours_v2(
    user_data: Dict[str, Any],
    target_date: date
) -> Dict[str, Any]:
    """
    УСТАРЕВШИЙ: Преобразовать данные из getEmployeesWorkedHours v2 в формат для Sheets.
    
    DEPRECATED! Используйте parse_summary_by_day_record вместо этого.
    
    Args:
        user_data: Объединенные данные пользователя + статистика
        target_date: Дата для которой данные
        
    Returns:
        Dictionary с данными для одной строки в Sheets
    """
    total_seconds = int(user_data.get("totalTime") or 0)
    productive_seconds = int(user_data.get("productiveTime") or 0)
    neutral_seconds = int(user_data.get("neutralTime") or 0)
    distracting_seconds = int(user_data.get("distractingTime") or 0)

    non_productive_seconds = distracting_seconds
    not_categorized_seconds = neutral_seconds

    total_h = seconds_to_hours(total_seconds)
    productive_h = seconds_to_hours(productive_seconds)
    non_productive_h = seconds_to_hours(non_productive_seconds)
    not_categorized_h = seconds_to_hours(not_categorized_seconds)

    full_name = f"{user_data.get('firstname', '')} {user_data.get('lastname', '')}".strip()
    if not full_name.strip():
        full_name = user_data.get('full_name', '').strip()

    return {
        "date": target_date.isoformat(),
        "full_name": full_name,
        "group_name": user_data.get("group_name", ""),
        "fact_start": user_data.get("fact_start", ""),
        "non_productive_hours": non_productive_h,
        "not_categorized_hours": not_categorized_h,
        "productive_hours": productive_h,
        "total_hours": total_h,
    }


def format_for_sheets_row(data: Dict[str, Any]) -> List[Any]:
    """
    Преобразовать parsed данные в список значений для строки Sheets.
    
    Формат колонок:
    Data | Full Name | Group | Fact start | Non productive | Not categorized | Prodactive | Total
    """
    return [
        data["date"],
        data["full_name"],
        data["group_name"],
        data["fact_start"],
        data["non_productive_hours"],
        data["not_categorized_hours"],
        data["productive_hours"],
        data["total_hours"],
    ]


def get_sheets_headers() -> List[str]:
    """Получить заголовки для Google Sheets."""
    return [
        "Data",
        "Full Name",
        "Group",
        "Fact start",
        "Non productive",
        "Not categorized",
        "Prodactive",
        "Total"
    ]
