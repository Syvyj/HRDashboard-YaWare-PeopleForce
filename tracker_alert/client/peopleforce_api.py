"""Клієнт для PeopleForce API."""
from __future__ import annotations
import logging
import time
from typing import Dict, List, Optional, Any
from datetime import date, datetime
import requests

from tracker_alert.config.settings import settings

logger = logging.getLogger(__name__)


class PeopleForceClient:
    """Клієнт для роботи з PeopleForce API."""
    
    def __init__(self):
        self.base_url = settings.peopleforce_base_url
        self.headers = {
            "X-API-KEY": settings.peopleforce_api_key,
            "Content-Type": "application/json"
        }
        # Кешування даних для зменшення кількості запитів
        self._employees_cache: Optional[List[Dict[str, Any]]] = None
        self._leaves_cache: Optional[List[Dict[str, Any]]] = None
        self._cache_timestamp: Optional[float] = None
    
    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Виконати GET запит до API.
        
        Args:
            endpoint: Endpoint (наприклад, '/employees')
            params: Query параметри
            
        Returns:
            Відповідь API у вигляді словника
        """
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Помилка запиту до PeopleForce API: {e}")
            raise
    
    def get_employees(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Отримати список всіх співробітників.
        
        Args:
            force_refresh: Примусово оновити кеш
            
        Returns:
            Список співробітників з їх даними
        """
        # Використовуємо кеш якщо він є і не застарів (5 хвилин)
        import time
        if not force_refresh and self._employees_cache is not None:
            if self._cache_timestamp and (time.time() - self._cache_timestamp) < 300:
                logger.debug("Використовуємо кешовані дані співробітників")
                return self._employees_cache
        
        logger.info("Получаю список сотрудников из PeopleForce...")
        
        # Отримуємо всіх співробітників з пагінацією
        all_employees = []
        page = 1
        max_pages = 50  # Обмеження для безпеки
        
        while page <= max_pages:
            data = self._get("/employees", params={'page': page, 'per_page': 100})
            employees = data.get("data", [])
            
            if not employees:
                break
            
            all_employees.extend(employees)
            page += 1
        
        logger.info(f"Отримано {len(all_employees)} співробітників з усіх сторінок")
        
        # Зберігаємо в кеш
        self._employees_cache = all_employees
        self._cache_timestamp = time.time()
        
        return all_employees
    
    def get_employee_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Знайти співробітника по email.
        
        Args:
            email: Email співробітника
            
        Returns:
            Дані співробітника або None якщо не знайдено
        """
        employees = self.get_employees()
        
        for emp in employees:
            if emp.get("email", "").lower() == email.lower():
                return emp
        
        return None
    
    def get_employee_location(self, email: str) -> Optional[str]:
        """Отримати локацію співробітника.
        
        Args:
            email: Email співробітника
            
        Returns:
            Назва локації або None
        """
        employee = self.get_employee_by_email(email)
        
        if employee and "location" in employee and employee["location"]:
            return employee["location"].get("name")
        
        return None
    
    def get_leave_requests(self, start_date: Optional[date] = None, end_date: Optional[date] = None) -> List[Dict[str, Any]]:
        """Отримати список відпусток/відсутностей.
        
        Args:
            start_date: Початкова дата для фільтрації (опціонально)
            end_date: Кінцева дата для фільтрації (опціонально)
            
        Returns:
            Список відпусток
        """
        logger.info("Получаю список отпусков из PeopleForce...")
        
        # Отримуємо всі відпустки з пагінацією
        all_leaves = []
        page = 1
        max_pages = 50  # Обмеження для безпеки
        
        while page <= max_pages:
            data = self._get("/leave_requests", params={'page': page, 'per_page': 100})
            leaves = data.get("data", [])
            
            if not leaves:
                break
            
            all_leaves.extend(leaves)
            page += 1
        
        logger.info(f"Отримано {len(all_leaves)} записів відпусток з усіх сторінок")
        
        # Фільтруємо тільки затверджені
        approved_leaves = [l for l in all_leaves if l.get("state") == "approved"]
        
        # Фільтруємо по датах якщо вказано
        if start_date or end_date:
            filtered = []
            for leave in approved_leaves:
                leave_start = datetime.fromisoformat(leave["starts_on"]).date()
                leave_end = datetime.fromisoformat(leave["ends_on"]).date()
                
                # Перевіряємо чи є перетин з вказаним періодом
                if start_date and end_date:
                    if leave_end >= start_date and leave_start <= end_date:
                        filtered.append(leave)
                elif start_date:
                    if leave_end >= start_date:
                        filtered.append(leave)
                elif end_date:
                    if leave_start <= end_date:
                        filtered.append(leave)
            
            approved_leaves = filtered
        
        logger.info(f"Получено {len(approved_leaves)} утвержденных отпусков")
        return approved_leaves
    
    def get_employee_leave_on_date(self, email: str, check_date: date) -> Optional[Dict[str, Any]]:
        """Перевірити чи співробітник у відпустці/відсутній на конкретну дату.
        
        Args:
            email: Email співробітника
            check_date: Дата для перевірки
            
        Returns:
            Дані про відпустку/відсутність або None
        """
        leaves = self.get_leave_requests(start_date=check_date, end_date=check_date)
        
        for leave in leaves:
            # Перевіряємо email співробітника
            if leave.get("employee", {}).get("email", "").lower() == email.lower():
                leave_start = datetime.fromisoformat(leave["starts_on"]).date()
                leave_end = datetime.fromisoformat(leave["ends_on"]).date()
                
                # Перевіряємо чи дата входить в період відсутності
                if leave_start <= check_date <= leave_end:
                    return leave
        
        return None
    
    def get_leave_type_category(self, leave_type: str) -> str:
        """Визначити категорію відсутності.
        
        Args:
            leave_type: Тип відпустки (Отпуск, Больничный, тощо)
            
        Returns:
            "vacation" - відпустка (зелений)
            "sick" - лікарняний (червоний)
            "other" - інше (червоний)
        """
        leave_type_lower = leave_type.lower()
        
        # Відпустка (зелений колір)
        if any(word in leave_type_lower for word in ["отпуск", "vacation", "holiday"]):
            return "vacation"
        
        # Лікарняний (червоний колір)
        if any(word in leave_type_lower for word in ["больничный", "sick", "medical"]):
            return "sick"
        
        # Всі інші (червоний колір)
        return "other"
    
    def format_location_display(self, location_name: Optional[str]) -> str:
        """Форматувати назву локації для відображення.
        
        Args:
            location_name: Назва локації з API
            
        Returns:
            Відформатована назва
        """
        if not location_name:
            return "Location: Unknown"
        
        # Маппінг локацій
        location_map = {
            "Remote Ukraine": "Remote Ukraine 🇺🇦",
            "Prague office": "Prague office 🇨🇿",
            "Warsaw office": "Warsaw office 🇵🇱",
            "Remote other countries": "Remote other countries 🌍"
        }
        
        formatted = location_map.get(location_name, location_name)
        return f"Location: {formatted}"


# Глобальний інстанс
_client: Optional[PeopleForceClient] = None


def get_peopleforce_client() -> PeopleForceClient:
    """Отримати глобальний інстанс PeopleForce клієнта."""
    global _client
    
    if _client is None:
        _client = PeopleForceClient()
    
    return _client
