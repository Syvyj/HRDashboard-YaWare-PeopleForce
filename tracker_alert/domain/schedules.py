"""Модуль для визначення графіків роботи співробітників"""
from __future__ import annotations
import json
import logging
from datetime import datetime, time
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


class WorkScheduleManager:
    """Менеджер графіків роботи співробітників."""
    
    def __init__(self, config_path: str = None):
        """
        Ініціалізація менеджера графіків.
        
        Args:
            config_path: Шлях до файлу конфігурації (JSON)
        """
        if config_path is None:
            # Використовуємо дефолтний шлях (корінь проекту / config)
            config_path = Path(__file__).parent.parent.parent / "config" / "work_schedules.json"
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Завантажити конфігурацію з файлу."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Конфігураційний файл не знайдено: {self.config_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Помилка парсингу JSON: {e}")
            raise
    
    def get_schedule_for_user(
        self, 
        email: str,
        location: Optional[str] = None,
        department: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Отримати графік роботи для користувача.
        
        Пріоритет:
        1. Індивідуальні налаштування (email_overrides)
        2. Налаштування відділу (department_overrides)
        3. Налаштування за локацією (location_mapping)
        4. Дефолтний графік
        
        Args:
            email: Email користувача
            location: Локація з PeopleForce
            department: Відділ з YaWare/PeopleForce
            
        Returns:
            Словник з графіком роботи
        """
        schedule_id = None
        source = "default"
        
        # 1. Перевіряємо індивідуальні налаштування
        email_overrides = self.config.get("email_overrides", {})
        if email in email_overrides:
            schedule_id = email_overrides[email]
            source = f"email override ({email})"
            logger.debug(f"Графік для {email}: {schedule_id} (індивідуальне налаштування)")
        
        # 2. Перевіряємо налаштування відділу
        if schedule_id is None and department:
            dept_overrides = self.config.get("department_overrides", {})
            if department in dept_overrides:
                schedule_id = dept_overrides[department]
                source = f"department override ({department})"
                logger.debug(f"Графік для {email}: {schedule_id} (відділ {department})")
        
        # 3. Визначаємо за локацією
        if schedule_id is None and location:
            location_mapping = self.config.get("location_mapping", {})
            schedule_id = location_mapping.get(location)
            if schedule_id:
                source = f"location ({location})"
                logger.debug(f"Графік для {email}: {schedule_id} (локація {location})")
        
        # 4. Дефолтний графік
        if schedule_id is None:
            schedule_id = self.config.get("default_schedule", "remote_ukraine")
            source = "default"
            logger.debug(f"Графік для {email}: {schedule_id} (дефолтний)")
        
        # Отримуємо деталі графіку
        schedules = self.config.get("schedules", {})
        schedule = schedules.get(schedule_id)
        
        if schedule is None:
            logger.warning(f"Графік {schedule_id} не знайдено, використовуємо default")
            schedule_id = self.config.get("default_schedule", "remote_ukraine")
            schedule = schedules.get(schedule_id, {})
        
        return {
            "schedule_id": schedule_id,
            "source": source,
            **schedule
        }
    
    def is_late(
        self,
        actual_start: str,
        email: str,
        location: Optional[str] = None,
        department: Optional[str] = None
    ) -> tuple[bool, int]:
        """
        Перевірити чи користувач запізнився.
        
        Args:
            actual_start: Фактичний час початку (формат "HH:MM")
            email: Email користувача
            location: Локація користувача
            department: Відділ користувача
            
        Returns:
            Tuple (is_late: bool, minutes_late: int)
        """
        schedule = self.get_schedule_for_user(email, location, department)
        
        # Якщо графік без контролю (24/7)
        if schedule.get("start_time") is None:
            return False, 0
        
        try:
            # Парсимо часи
            expected_start = datetime.strptime(schedule["start_time"], "%H:%M").time()
            actual = datetime.strptime(actual_start, "%H:%M").time()
            
            # Рахуємо різницю в хвилинах
            expected_minutes = expected_start.hour * 60 + expected_start.minute
            actual_minutes = actual.hour * 60 + actual.minute
            
            diff_minutes = actual_minutes - expected_minutes
            
            # Враховуємо поріг запізнення
            threshold = schedule.get("lateness_threshold_minutes", 15)
            
            is_late = diff_minutes > threshold
            
            return is_late, max(0, diff_minutes)
            
        except ValueError as e:
            logger.error(f"Помилка парсингу часу: {e}")
            return False, 0
    
    def left_early(
        self,
        actual_end: str,
        email: str,
        location: Optional[str] = None,
        department: Optional[str] = None
    ) -> tuple[bool, int]:
        """
        Перевірити чи користувач пішов раніше.
        
        Args:
            actual_end: Фактичний час завершення (формат "HH:MM")
            email: Email користувача
            location: Локація користувача
            department: Відділ користувача
            
        Returns:
            Tuple (left_early: bool, minutes_early: int)
        """
        schedule = self.get_schedule_for_user(email, location, department)
        
        # Якщо графік без контролю (24/7)
        if schedule.get("end_time") is None:
            return False, 0
        
        try:
            # Парсимо часи
            expected_end = datetime.strptime(schedule["end_time"], "%H:%M").time()
            actual = datetime.strptime(actual_end, "%H:%M").time()
            
            # Рахуємо різницю в хвилинах
            expected_minutes = expected_end.hour * 60 + expected_end.minute
            actual_minutes = actual.hour * 60 + actual.minute
            
            diff_minutes = expected_minutes - actual_minutes
            
            # Враховуємо поріг раннього завершення
            threshold = schedule.get("early_leave_threshold_minutes", 30)
            
            left_early = diff_minutes > threshold
            
            return left_early, max(0, diff_minutes)
            
        except ValueError as e:
            logger.error(f"Помилка парсингу часу: {e}")
            return False, 0
    
    def get_all_schedules(self) -> Dict[str, Dict[str, Any]]:
        """Отримати всі доступні графіки."""
        return self.config.get("schedules", {})
    
    def format_schedule_info(
        self,
        email: str,
        location: Optional[str] = None,
        department: Optional[str] = None
    ) -> str:
        """
        Відформатувати інформацію про графік у читабельний текст.
        
        Args:
            email: Email користувача
            location: Локація користувача
            department: Відділ користувача
            
        Returns:
            Текстове представлення графіку
        """
        schedule = self.get_schedule_for_user(email, location, department)
        
        if schedule.get("start_time") is None:
            return f"📅 {schedule.get('name', 'Unknown')} (24/7, без контролю часу)"
        
        return (
            f"📅 {schedule.get('name', 'Unknown')}\n"
            f"   🕐 Початок: {schedule.get('start_time')}\n"
            f"   🕔 Завершення: {schedule.get('end_time')}\n"
            f"   ⏱️ Поріг запізнення: {schedule.get('lateness_threshold_minutes')} хв\n"
            f"   🔍 Визначено: {schedule.get('source', 'unknown')}"
        )


# Глобальний інстанс менеджера
schedule_manager = WorkScheduleManager()
