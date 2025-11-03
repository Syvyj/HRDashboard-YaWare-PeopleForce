"""
Модуль для керування користувачами через адміністратора бота.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)

USER_SCHEDULES_FILE = Path(__file__).parent.parent.parent / "config" / "user_schedules.json"
BACKUP_FILE = USER_SCHEDULES_FILE.with_suffix('.json.backup')


def load_users() -> Dict:
    """Завантажити базу користувачів."""
    try:
        with open(USER_SCHEDULES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Помилка завантаження користувачів: {e}")
        return {"_metadata": {}, "users": {}}


def save_users(data: Dict) -> bool:
    """Зберегти базу користувачів з резервною копією."""
    try:
        # Створити бекап
        if USER_SCHEDULES_FILE.exists():
            with open(USER_SCHEDULES_FILE, 'r', encoding='utf-8') as f:
                backup_data = f.read()
            with open(BACKUP_FILE, 'w', encoding='utf-8') as f:
                f.write(backup_data)
        
        # Оновити метадані
        if "_metadata" not in data:
            data["_metadata"] = {}
        data["_metadata"]["last_updated"] = datetime.now().isoformat()
        
        # Зберегти
        with open(USER_SCHEDULES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✅ База користувачів збережена")
        return True
    except Exception as e:
        logger.error(f"Помилка збереження користувачів: {e}")
        return False


def add_user(name: str, email: str, user_id: str, location: str, start_time: str) -> tuple[bool, str]:
    """
    Додати нового користувача.
    
    Returns:
        (success: bool, message: str)
    """
    try:
        data = load_users()
        
        # Перевірка чи існує
        if name in data["users"]:
            return False, f"❌ Пользователь '{name}' уже существует в базе"
        
        # Перевірка email
        for existing_name, user_data in data["users"].items():
            if user_data.get("email") == email:
                return False, f"❌ Email '{email}' уже используется пользователем '{existing_name}'"
        
        # Додати
        data["users"][name] = {
            "start_time": start_time,
            "location": location,
            "user_id": user_id,
            "email": email
        }
        
        if save_users(data):
            logger.info(f"✅ Додано користувача: {name} ({email})")
            return True, f"✅ Пользователь '{name}' успешно добавлен!"
        else:
            return False, "❌ Ошибка сохранения базы данных"
            
    except Exception as e:
        logger.error(f"Помилка додавання користувача: {e}")
        return False, f"❌ Ошибка: {str(e)}"


def delete_user(name: str) -> tuple[bool, str]:
    """
    Видалити користувача.
    
    Returns:
        (success: bool, message: str)
    """
    try:
        data = load_users()
        
        if name not in data["users"]:
            return False, f"❌ Пользователь '{name}' не найден в базе"
        
        user_info = data["users"][name]
        del data["users"][name]
        
        if save_users(data):
            logger.info(f"🗑️ Видалено користувача: {name}")
            return True, f"✅ Пользователь '{name}' ({user_info.get('email', 'N/A')}) успешно удален!"
        else:
            return False, "❌ Ошибка сохранения базы данных"
            
    except Exception as e:
        logger.error(f"Помилка видалення користувача: {e}")
        return False, f"❌ Ошибка: {str(e)}"


def update_user(name: str, field: str, value: str) -> tuple[bool, str]:
    """
    Оновити дані користувача.
    
    Args:
        name: Ім'я користувача
        field: Поле для оновлення (email, user_id, location, start_time)
        value: Нове значення
    
    Returns:
        (success: bool, message: str)
    """
    try:
        data = load_users()
        
        if name not in data["users"]:
            return False, f"❌ Пользователь '{name}' не найден в базе"
        
        valid_fields = ["email", "user_id", "location", "start_time"]
        if field not in valid_fields:
            return False, f"❌ Неверное поле. Доступны: {', '.join(valid_fields)}"
        
        # Якщо міняємо email - перевіряємо унікальність
        if field == "email":
            for existing_name, user_data in data["users"].items():
                if existing_name != name and user_data.get("email") == value:
                    return False, f"❌ Email '{value}' уже используется пользователем '{existing_name}'"
        
        old_value = data["users"][name].get(field, "N/A")
        data["users"][name][field] = value
        
        if save_users(data):
            logger.info(f"✏️ Оновлено {field} для {name}: {old_value} → {value}")
            
            field_names = {
                "email": "Email",
                "user_id": "ID",
                "location": "Локация",
                "start_time": "Время начала"
            }
            
            return True, f"✅ {field_names[field]} обновлено!\n\nПользователь: {name}\nСтарое значение: {old_value}\nНовое значение: {value}"
        else:
            return False, "❌ Ошибка сохранения базы данных"
            
    except Exception as e:
        logger.error(f"Помилка оновлення користувача: {e}")
        return False, f"❌ Ошибка: {str(e)}"


def get_user_info(name: str) -> Optional[Dict]:
    """Отримати інформацію про користувача."""
    data = load_users()
    return data["users"].get(name)


def search_users(query: str) -> List[str]:
    """
    Пошук користувачів за іменем.
    
    Returns:
        Список імен користувачів
    """
    data = load_users()
    query_lower = query.lower()
    
    matches = []
    for name in data["users"].keys():
        if query_lower in name.lower():
            matches.append(name)
    
    return sorted(matches)


def get_all_users() -> List[str]:
    """Отримати список всіх користувачів."""
    data = load_users()
    return sorted(data["users"].keys())
