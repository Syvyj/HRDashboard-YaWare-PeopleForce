"""YaWare API v2 клієнт (працює!)"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
import requests
from ..config.settings import settings

logger = logging.getLogger(__name__)


class YaWareV2Client:
    """Клієнт для роботи з YaWare API v2."""
    
    def __init__(self):
        self.base_url = settings.yaware_base_url
        self.access_key = settings.yaware_access_key
        
        if not self.access_key:
            raise ValueError("YAWARE_ACCESS_KEY не настроен в .env")
    
    def _request(self, method: str, params: Dict[str, Any] = None) -> Any:
        """Базовий метод для запитів до API."""
        url = f"{self.base_url}/{method}"
        
        request_params = {"access_key": self.access_key}
        if params:
            request_params.update(params)
        
        logger.debug(f"API request: {method} with params {request_params}")
        
        try:
            response = requests.get(url, params=request_params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {method} - {str(e)}")
            raise
    
    def get_users(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        Отримати список користувачів.
        
        Args:
            active_only: Якщо True, повертає тільки активних користувачів
            
        Returns:
            Список користувачів
        """
        users = self._request("getUsers")
        
        if active_only:
            users = [u for u in users if u.get("is_active") == "1"]
            logger.info(f"Получено {len(users)} активных пользователей")
        else:
            logger.info(f"Получено {len(users)} пользователей (всех)")

        return users
    
    def get_user(self, email: str) -> Dict[str, Any]:
        """
        Отримати дані конкретного користувача.
        
        Args:
            email: Email користувача
            
        Returns:
            Дані користувача
        """
        return self._request("getUser", {"email": email})
    
    def get_employee_worked_hours(
        self,
        employee_id: str,
        date_from: str,
        date_to: str
    ) -> Dict[str, Any]:
        """
        Отримати відпрацьовані години для співробітника.
        
        Args:
            employee_id: ID співробітника
            date_from: Початкова дата (YYYY-MM-DD)
            date_to: Кінцева дата (YYYY-MM-DD)
            
        Returns:
            Дані про відпрацьовані години:
            {
                "totalTime": секунди,
                "productiveTime": секунди,
                "neutralTime": секунди,
                "distractingTime": секунди
            }
        """
        return self._request(
            "getEmployeesWorkedHours",
            {
                "employeeId": employee_id,
                "dateFrom": date_from,
                "dateTo": date_to
            }
        )
    
    def get_summary_by_day(self, date: str) -> List[Dict[str, Any]]:
        """
        Отримати повну статистику за день для всіх користувачів (один запит!).
        
        Args:
            date: Дата (YYYY-MM-DD)
            
        Returns:
            Список з повною статистикою:
            {
                "period": "07 Oct, 2025",
                "user": "Name Surname, email@example.com",
                "group": "Tech",
                "time_start": "09:15",  # ЧАС ПОЧАТКУ!
                "time_end": "18:30",
                "distracting": "1834",  # секунди
                "uncategorized": "899",  # секунди
                "productive": "27836",  # секунди
                "total": "30569",       # секунди
                "user_id": "7637340"
            }
        """
        result = self._request("getSummaryByDay", {"date": date})
        data = result.get("data", [])
        logger.info(f"Получена статистика для {len(data)} пользователей за {date}")
        return data
    
    def get_week_data(self, week_days: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Отримати дані за тиждень (5 днів) згруповані по користувачам.
        
        Args:
            week_days: Список дат у форматі YYYY-MM-DD (зазвичай Пн-Пт)
            
        Returns:
            Dictionary {user_id: {name, group, days: [day1_data, day2_data, ...]}}
        """
        week_data = {}
        
        logger.info(f"Собираем данные за {len(week_days)} дней...")
        
        for day_date in week_days:
            logger.info(f"  Получаем данные за {day_date}...")
            daily_data = self.get_summary_by_day(day_date)
            
            for record in daily_data:
                user_id = record.get("user_id")
                if not user_id:
                    continue
                
                # Ініціалізуємо користувача якщо це перший день
                if user_id not in week_data:
                    # Парсимо ім'я (формат: "Name Surname, email@example.com")
                    user_field = record.get("user", "")
                    if ", " in user_field:
                        full_name = user_field.split(", ")[0]
                        email = user_field.split(", ")[1] if len(user_field.split(", ")) > 1 else ""
                    else:
                        full_name = user_field
                        email = ""
                    
                    week_data[user_id] = {
                        "user_id": user_id,
                        "full_name": full_name,
                        "email": email,
                        "group": record.get("group", ""),
                        "days": []
                    }
                
                # Додаємо дані за день
                week_data[user_id]["days"].append({
                    "date": day_date,
                    "time_start": record.get("time_start", ""),
                    "time_end": record.get("time_end", ""),
                    "productive": int(record.get("productive", 0)),
                    "uncategorized": int(record.get("uncategorized", 0)),
                    "distracting": int(record.get("distracting", 0)),
                    "total": int(record.get("total", 0)),
                })

        logger.info(f"✅ Собрано данные за неделю для {len(week_data)} пользователей")
        return week_data
    
    def get_all_active_users_stats(
        self,
        date_from: str,
        date_to: str
    ) -> List[Dict[str, Any]]:
        """
        ЗАСТАРІЛИЙ МЕТОД: Отримати статистику для всіх активних користувачів.
        
        Використовуйте get_summary_by_day() замість цього - він швидший!
        
        Args:
            date_from: Початкова дата (YYYY-MM-DD)
            date_to: Кінцева дата (YYYY-MM-DD)
            
        Returns:
            Список з даними користувачів + їх статистика
        """
        users = self.get_users(active_only=True)
        results = []
        
        logger.info(f"Собираю статистику для {len(users)} активных пользователей...")
        
        for i, user in enumerate(users, 1):
            user_id = user.get("id")
            if not user_id:
                continue
            
            try:
                stats = self.get_employee_worked_hours(user_id, date_from, date_to)
                
                # Об'єднуємо дані користувача зі статистикою
                result = {
                    "user_id": user_id,
                    "email": user.get("email"),
                    "firstname": user.get("firstname"),
                    "lastname": user.get("lastname"),
                    "group_name": user.get("group_name"),
                    "last_activity": user.get("last_activity"),
                    **stats  # totalTime, productiveTime, neutralTime, distractingTime
                }
                results.append(result)
                
                if i % 10 == 0:
                    logger.info(f"Обработано {i}/{len(users)} пользователей...")

            except Exception as e:
                logger.warning(f"Не удалось получить статистику для {user_id}: {e}")
                continue

        logger.info(f"Успешно получена статистика для {len(results)} пользователей")
        return results
    
    def get_lateness(
        self,
        date_from: str,
        date_to: str,
        employee_id: Optional[str] = None
    ) -> Any:
        """
        Отримати звіт по запізненнях.
        
        Args:
            date_from: Початкова дата (YYYY-MM-DD)
            date_to: Кінцева дата (YYYY-MM-DD)
            employee_id: ID співробітника (опціонально, якщо не вказано - всі)
            
        Returns:
            Дані про запізнення
        """
        params = {
            "dateFrom": date_from,
            "dateTo": date_to
        }
        if employee_id:
            params["employeeId"] = employee_id
        
        return self._request("lateness", params)
    
    def get_worked_at_night(
        self,
        date_from: str,
        date_to: str,
        employee_id: Optional[str] = None
    ) -> Any:
        """
        Отримати звіт по роботі поза робочим графіком.
        
        Args:
            date_from: Початкова дата (YYYY-MM-DD)
            date_to: Кінцева дата (YYYY-MM-DD)
            employee_id: ID співробітника (опціонально, якщо не вказано - всі)
            
        Returns:
            Дані про роботу поза графіком
        """
        params = {
            "dateFrom": date_from,
            "dateTo": date_to
        }
        if employee_id:
            params["employeeId"] = employee_id
        
        return self._request("workedAtNight", params)
    
    def get_left_before(
        self,
        date_from: str,
        date_to: str,
        employee_id: Optional[str] = None
    ) -> Any:
        """
        Отримати звіт про тих, хто пішов раніше.
        
        Args:
            date_from: Початкова дата (YYYY-MM-DD)
            date_to: Кінцева дата (YYYY-MM-DD)
            employee_id: ID співробітника (опціонально, якщо не вказано - всі)
            
        Returns:
            Дані про тих, хто пішов раніше
        """
        params = {
            "dateFrom": date_from,
            "dateTo": date_to
        }
        if employee_id:
            params["employeeId"] = employee_id
        
        return self._request("leftBefore", params)


# Глобальний інстанс клієнта
client = YaWareV2Client()
