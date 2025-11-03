"""Мапери для тижневого формату експорту."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import date
import json
import os


# Завантажуємо mapping імен з бази user_schedules.json
def load_name_mapping() -> Dict[str, str]:
    """
    Завантажити mapping імен з YaWare → правильне ім'я з бази.
    
    Returns:
        Dict де ключ - ім'я з YaWare (lowercase), значення - правильне ім'я
    """
    try:
        # Шлях до бази
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        db_path = os.path.join(base_dir, 'config', 'user_schedules.json')
        
        if not os.path.exists(db_path):
            return {}
        
        with open(db_path, 'r', encoding='utf-8') as f:
            database = json.load(f)
        
        # Створюємо mapping: lowercase ім'я → правильне ім'я
        name_map = {}
        for correct_name in database.get('users', {}).keys():
            # Додаємо як є
            name_map[correct_name.lower()] = correct_name
            
            # Додаємо варіант з переставленими словами (Прізвище Ім'я → Ім'я Прізвище)
            words = correct_name.split()
            if len(words) >= 2:
                reversed_name = f"{words[-1]} {' '.join(words[:-1])}"
                name_map[reversed_name.lower()] = correct_name
        
        return name_map
    except Exception:
        return {}


# Глобальний mapping імен (завантажується один раз)
_NAME_MAPPING = load_name_mapping()


def normalize_user_name(yaware_name: str) -> str:
    """
    Нормалізувати ім'я користувача з YaWare до правильного формату.
    
    Args:
        yaware_name: Ім'я з YaWare API
        
    Returns:
        Нормалізоване ім'я (з великої літери, правильний порядок)
    """
    if not yaware_name:
        return yaware_name
    
    # Шукаємо в mapping
    normalized = _NAME_MAPPING.get(yaware_name.lower())
    if normalized:
        return normalized
    
    # Якщо не знайдено - повертаємо як є
    return yaware_name


def seconds_to_hours(seconds: int) -> float:
    """Перетворити секунди в години (округлено до 2 знаків).
    
    ЗАСТАРІЛА! Використовувати seconds_to_time_format() замість цього.
    """
    return round(seconds / 3600, 2)


def seconds_to_time_format(seconds: int) -> str:
    """
    Перетворити секунди у формат ГГ:ХХ (години:хвилини).
    
    Args:
        seconds: Кількість секунд
        
    Returns:
        Рядок формату "8:35" або "0:05"
        
    Examples:
        seconds_to_time_format(30569) -> "8:29"  # 8 годин 29 хвилин
        seconds_to_time_format(300) -> "0:05"     # 5 хвилин
    """
    if not seconds:
        return ""
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    
    return f"{hours}:{minutes:02d}"


def seconds_to_duration(seconds: int) -> float:
    """
    Перетворити секунди у duration (частина доби) для Google Sheets.
    
    Google Sheets зберігає час як частину доби:
    - 1 година = 1/24 = 0.041666...
    - 1 хвилина = 1/1440 = 0.000694...
    - 1 секунда = 1/86400 = 0.000011...
    
    Args:
        seconds: Кількість секунд
        
    Returns:
        Число (частина доби) для Google Sheets
        
    Examples:
        seconds_to_duration(28800) -> 0.333333  # 8 годин
        seconds_to_duration(3600) -> 0.041666   # 1 година
        seconds_to_duration(30569) -> 0.353819  # 8:29
    """
    if not seconds:
        return 0
    
    # 1 доба = 86400 секунд
    return seconds / 86400



def format_weekly_headers() -> List[str]:
    """
    Отримати заголовки для тижневого формату.
    
    Returns:
        Список заголовків
    """
    return [
        "Name",
        "Project",
        "Department",
        "Team",
        "Plan Start",
        "Data",
        "Fact Start",
        "Non Productive",
        "Not Categorized",
        "Prodactive",
        "Total",
        "Screenshots",
        "Notes"
    ]


def format_user_block(user_data: dict, week_days: List[date], row_start: int, location: Optional[str] = None, leave_info: Optional[Dict] = None) -> List[List]:
    """
    Форматує блок даних для одного користувача (8 рядків).
    
    user_data - дані користувача з YaWare
    week_days - список всіх 5 дат тижня (Пн-Пт)
    row_start - початковий рядок для цього користувача
    location - назва локації з PeopleForce (опціонально)
    leave_info - словник {date_str: leave_type} з інформацією про відпустки/лікарняні
    
    Структура:
    - рядок 1: Ім'я користувача (весь рядок - заголовок/розділювач)
    - рядок 2: A="Location", B-M=День 1 (включаючи Project/Department/Team)
    - рядок 3: A=локація, B-M=День 2
    - рядок 4: A="", B-M=День 3
    - рядок 5: A="", B-M=День 4
    - рядок 6: A="", B-M=День 5
    - рядок 7: A-M=Total з формулами
    - рядок 8: порожній розділювач
    """
    rows = []
    
    # Рядок 1: Ім'я користувача (весь рядок - заголовок)
    project = user_data.get("project") or ""
    department = user_data.get("department") or ""
    team = user_data.get("team") or ""
    
    header_row = [
        user_data["full_name"],
        project,
        department,
        team,
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        ""
    ]
    rows.append(header_row)
    
    # Перевіряємо чи це користувач з бази (без даних YaWare)
    is_from_database = user_data.get("from_database", False)
    
    # Отримуємо start_time з user_data (було додано в export_weekly.py)
    plan_start_time = user_data.get("start_time", "")
    
    # Створюємо мапу існуючих даних по датам
    days_map = {}
    for day_data in user_data["days"]:
        day_date_str = day_data["date"]
        if isinstance(day_date_str, str):
            day_date = date.fromisoformat(day_date_str)
        else:
            day_date = day_date_str
        days_map[day_date] = day_data
    
    # Ініціалізуємо змінні для підрахунку загального часу
    total_productive = 0
    total_uncategorized = 0
    total_distracting = 0
    
    # Генеруємо 5 рядків для днів тижня (рядки 2-6)
    for i, week_day in enumerate(week_days):
        date_str = week_day.strftime("%d.%m.%Y")
        # Перевіряємо чи є відсутність на цей день
        leave_on_day = leave_info.get(week_day) if leave_info else None
        # Визначаємо що буде в колонці A
        if i == 0:
            col_a = "Location"
        elif i == 1:
            col_a = location if location else "—"
        else:
            col_a = ""
        # Project/Department/Team завжди як у заголовку
        day_project = project
        day_department = department
        day_team = team
        if week_day in days_map:
            # Є дані за цей день
            day_data = days_map[week_day]
            productive_time = seconds_to_duration(day_data["productive"])
            uncategorized_time = seconds_to_duration(day_data["uncategorized"])
            distracting_time = seconds_to_duration(day_data["distracting"])
            total_time = seconds_to_duration(day_data["total"])
            total_productive += day_data["productive"]
            total_uncategorized += day_data["uncategorized"]
            total_distracting += day_data["distracting"]
            notes = ""
            if leave_on_day:
                leave_type = leave_on_day.get("leave_type", "Відсутність")
                starts = leave_on_day.get("starts_on", "")
                ends = leave_on_day.get("ends_on", "")
                notes = f"{leave_type} ({starts} - {ends})"
            day_row = [
                col_a,
                day_project,
                day_department,
                day_team,
                plan_start_time,
                date_str,
                day_data.get("fact_start_adjusted", day_data.get("time_start", "")),
                distracting_time,
                uncategorized_time,
                productive_time,
                seconds_to_duration(day_data["productive"] + day_data["uncategorized"]),
                "",
                notes
            ]
        else:
            notes = ""
            if leave_on_day:
                leave_type = leave_on_day.get("leave_type", "Відсутність")
                starts = leave_on_day.get("starts_on", "")
                ends = leave_on_day.get("ends_on", "")
                notes = f"{leave_type} ({starts} - {ends})"
            elif is_from_database:
                notes = "Немає даних YaWare"
            day_row = [
                col_a,
                day_project,
                day_department,
                day_team,
                plan_start_time,
                date_str,
                "",
                "",
                "",
                "",
                "",
                "",
                notes
            ]
        rows.append(day_row)
    
    # Рядок Total з формулами SUM (рядок 7)
    # Структура блоку:
    # row_start+0: Ім'я (заголовок)
    # row_start+1: "Location" + День 1
    # row_start+2: локація + День 2
    # row_start+3: День 3
    # row_start+4: День 4
    # row_start+5: День 5
    # row_start+6: Total (поточний рядок)
    
    total_row = [
        "Week total",
        project,
        department,
        team,
        "",
        "",
        "",
        seconds_to_duration(total_distracting),
        seconds_to_duration(total_uncategorized),
        seconds_to_duration(total_productive),
        seconds_to_duration(total_productive + total_uncategorized),
        "",
        ""
    ]
    rows.append(total_row)
    
    # Порожній рядок-розділювач між блоками
    empty_row = ["", "", "", "", "", "", "", "", "", "", "", "", ""]
    rows.append(empty_row)
    
    return rows


def format_all_user_blocks(
    week_data: Dict[str, Dict[str, Any]], 
    week_days: List[date],
    peopleforce_data: Dict[str, Any] = None
) -> List[List[Any]]:
    """
    Форматувати всі блоки користувачів для тижневого експорту.
    
    Args:
        week_data: Дані за тиждень згруповані по користувачам
        week_days: Список всіх 5 дат тижня (Пн-Пт)
        peopleforce_data: Дані з PeopleForce API:
            - locations: Dict[email, location_name]
            - leaves: Dict[email, Dict[date, leave_info]]
        
    Returns:
        Список всіх рядків для Google Sheets (з заголовками)
    """
    all_rows = []
    
    if peopleforce_data is None:
        peopleforce_data = {"locations": {}, "leaves": {}}
    
    locations = peopleforce_data.get("locations", {})
    leaves = peopleforce_data.get("leaves", {})
    
    # Заголовки колонок (рядок 1)
    all_rows.append(format_weekly_headers())
    
    # Нормалізуємо імена користувачів перед сортуванням
    for user_data in week_data.values():
        original_name = user_data.get("full_name", "")
        normalized_name = normalize_user_name(original_name)
        user_data["full_name"] = normalized_name
    
    # Сортуємо користувачів за нормалізованим іменем
    sorted_users = sorted(week_data.values(), key=lambda x: x["full_name"])
    
    # Генеруємо блок для кожного користувача з номерами рядків для формул
    current_row = 2  # Початок після заголовків (1-indexed)
    
    for user_data in sorted_users:
        # Отримуємо email користувача (з YaWare даних)
        user_email = user_data.get("email", "")
        
        # Отримуємо локацію з PeopleForce
        location = locations.get(user_email, "")
        
        # Отримуємо інформацію про відсутності на цей тиждень
        user_leaves = leaves.get(user_email, {})
        
        # Передаємо номер початкового рядка блоку для формул SUM
        user_rows = format_user_block(
            user_data, 
            week_days, 
            row_start=current_row,
            location=location,
            leave_info=user_leaves
        )
        all_rows.extend(user_rows)
        
        # Кожен блок = 8 рядків (ім'я-заголовок + 5 днів + Week total + розділювач)
        current_row += 8
    
    return all_rows
