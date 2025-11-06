"""Утилиты для работы с неделями."""
from datetime import date, timedelta
from typing import Tuple


def get_week_number(target_date: date) -> int:
    """
    Получить номер недели в году (ISO week number).
    
    Args:
        target_date: Дата
        
    Returns:
        Номер недели (1-53)
    """
    return target_date.isocalendar()[1]


def get_week_range(target_date: date) -> Tuple[date, date]:
    """
    Получить диапазон недели (Monday - Friday) для заданной даты.
    
    Args:
        target_date: Будь-яка дата в тижні
        
    Returns:
        Tuple (monday, friday)
    """
    # Знаходимо понеділок цього тижня
    # weekday(): Monday=0, Sunday=6
    days_since_monday = target_date.weekday()
    monday = target_date - timedelta(days=days_since_monday)
    
    # П'ятниця = понеділок + 4 дні
    friday = monday + timedelta(days=4)
    
    return monday, friday


def get_week_days(target_date: date, exclude_today: bool = True) -> list[date]:
    """
    Отримати всі робочі дні тижня (Пн-Пт) для заданої дати.
    
    Args:
        target_date: Будь-яка дата в тижні
        exclude_today: Чи виключати сьогоднішню дату (якщо робочий день ще не завершено)
        
    Returns:
        Список дат [Monday, Tuesday, Wednesday, Thursday, Friday], без сьогодні якщо exclude_today=True
    """
    monday, _ = get_week_range(target_date)
    all_days = [monday + timedelta(days=i) for i in range(5)]
    
    # Виключаємо сьогоднішню дату, якщо вона є в списку
    if exclude_today:
        today = date.today()
        all_days = [day for day in all_days if day < today]
    
    return all_days


def get_week_sheet_name(target_date: date) -> str:
    """
    Сформувати назву аркушу для тижня.
    
    Args:
        target_date: Будь-яка дата в тижні
        
    Returns:
        Назва аркушу типу "Week 41 (07-13 Oct 2025)"
    """
    monday, friday = get_week_range(target_date)
    week_num = get_week_number(target_date)
    
    # Формат: "Week 41 (07-13 Oct 2025)"
    # Якщо місяці різні, показуємо обидва
    if monday.month == friday.month:
        date_range = f"{monday.strftime('%d')}-{friday.strftime('%d %b %Y')}"
    else:
        date_range = f"{monday.strftime('%d %b')}-{friday.strftime('%d %b %Y')}"
    
    return f"Week {week_num} ({date_range})"


def get_year_and_week(target_date: date) -> Tuple[int, int]:
    """
    Отримати рік та номер тижня.
    
    Args:
        target_date: Дата
        
    Returns:
        Tuple (year, week_number)
    """
    iso_calendar = target_date.isocalendar()
    return iso_calendar[0], iso_calendar[1]
