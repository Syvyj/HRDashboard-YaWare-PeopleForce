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
    
    def _request(self, method: str, params: dict | None = None) -> Any:
        """Базовый метод для запросов к API."""
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
    
    def get_users(self, active_only: bool = False) -> list[dict]:
        """
        Получить список пользователей.
        
        Args:
            active_only: Если True, возвращает только активных пользователей
            
        Returns:
            Список пользователей
        """
        users = self._request("getUsers")
        
        if active_only:
            users = [u for u in users if u.get("is_active") == "1"]
            logger.info(f"Получено {len(users)} активных пользователей")
        else:
            logger.info(f"Получено {len(users)} пользователей (всех)")

        return users
    
    def get_user(self, email: str) -> dict | None:
        """
        Получить данные конкретного пользователя.
        
        Args:
            email: Email пользователя
            
        Returns:
            Данные пользователя
        """
        return self._request("getUser", {"email": email})
    
    def get_worked_hours(self, email: str, date_from: str, date_to: str) -> dict:
        """
        Получить отработанные часы для сотрудника.
        
        Args:
            email: Email сотрудника
            date_from: Начальная дата (YYYY-MM-DD)
            date_to: Конечная дата (YYYY-MM-DD)
            
        Returns:
            Данные об отработанных часах
        """
        return self._request("getWorkedHours", {
            "email": email,
            "dateFrom": date_from,
            "dateTo": date_to
        })
    
    def get_summary_by_day(self, date: str) -> list[dict]:
        """
        Получить полную статистику за день для всех пользователей (один запрос).
        
        Args:
            date: Дата (YYYY-MM-DD)
            
        Returns:
            Список с полной статистикой:
            {
                "period": "07 Oct, 2025",
                "user": "Name Surname, email@example.com",
                "group": "Tech",
                "time_start": "09:15",
                "time_end": "18:30",
                "distracting": "1834",
                "uncategorized": "899",
                "productive": "27836",
                "total": "30569",
                "user_id": "7637340"
            }
        """
        result = self._request("getSummaryByDay", {"date": date})
        data = result.get("data", [])
        logger.info(f"Получена статистика для {len(data)} пользователей за {date}")
        return data

    def get_schedules(self) -> list[dict]:
        """
        Попробовать получить рабочие расписания пользователей.
        
        Returns:
            Сырые данные от YaWare (структура может отличаться, поэтому парсим на стороне вызова).
        """
        try:
            return self._request("getSchedules")
        except Exception as exc:
            logger.warning("YaWare getSchedules не доступен: %s", exc)
            return None
    
    def get_week_data(self, week_days: list) -> dict:
        """
        Получить данные за неделю (5 дней) сгруппированные по пользователям.
        
        Args:
            week_days: Список дат (date objects) для получения
            
        Returns:
            {email: {user_info, days: [{date, stats}]}}
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
                
                # Инициализируем пользователя если это первый день
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
                
                # Добавляем данные за день
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
    
    def get_all_employees_stats(self, date_from: str, date_to: str) -> list[dict]:
        """
        УСТАРЕВШИЙ МЕТОД: Получить статистику для всех активных пользователей.
        Используйте get_summary_by_day() вместо этого!
        
        Args:
            date_from: Начальная дата (YYYY-MM-DD)
            date_to: Конечная дата (YYYY-MM-DD)
            
        Returns:
            Список с данными пользователей + их статистика
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
                
                # Объединяем данные пользователя со статистикой
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
    
    def get_lateness_report(self, date_from: str, date_to: str) -> dict:
        """
        Получить отчет по опозданиям.
        
        Args:
            date_from: Начальная дата (YYYY-MM-DD)
            date_to: Конечная дата (YYYY-MM-DD)
            
        Returns:
            Данные об опозданиях
        """
        params = {
            "dateFrom": date_from,
            "dateTo": date_to
        }
        
        return self._request("lateness", params)
    
    def get_out_of_schedule_report(self, date_from: str, date_to: str) -> dict:
        """
        Получить отчет по работе вне рабочего графика.
        
        Args:
            date_from: Начальная дата (YYYY-MM-DD)
            date_to: Конечная дата (YYYY-MM-DD)
            
        Returns:
            Данные о работе вне графика
        """
        params = {
            "dateFrom": date_from,
            "dateTo": date_to
        }
        
        return self._request("workedAtNight", params)
    
    def get_early_leave_report(self, date_from: str, date_to: str) -> dict:
        """
        Получить отчет о тех, кто ушел раньше.
        
        Args:
            date_from: Начальная дата (YYYY-MM-DD)
            date_to: Конечная дата (YYYY-MM-DD)
            
        Returns:
            Данные о тех, кто ушел раньше
        """
        params = {
            "dateFrom": date_from,
            "dateTo": date_to
        }
        
        return self._request("leftBefore", params)


# Глобальній інстанс клієнта
client = YaWareV2Client()
