#!/usr/bin/env python3
"""
Скрипт для очищення telegram username від HTML тегів у user_schedules.json
"""
import sys
import re
from pathlib import Path

# Додаємо кореневу директорію в path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tracker_alert.services.user_manager import load_users, save_users


def clean_telegram_username(value: str) -> str:
    """Очищує telegram username від HTML тегів та зайвих символів."""
    if not value:
        return ""
    
    # Видаляємо HTML теги
    value = re.sub(r'<[^>]+>', '', value)
    # Видаляємо зайві пробіли
    value = value.strip()
    # Видаляємо @ якщо є на початку
    value = value.lstrip('@')
    
    return value


def main():
    """Очищення telegram usernames."""
    print("=" * 80)
    print("ОЧИЩЕННЯ TELEGRAM USERNAMES ВІД HTML ТЕГІВ")
    print("=" * 80)
    print()
    
    # Завантажуємо дані
    data = load_users()
    users = data.get("users", {})
    
    if not users:
        print("❌ Не знайдено користувачів")
        return 1
    
    print(f"Знайдено {len(users)} користувачів\n")
    
    updated_count = 0
    cleaned_users = []
    
    for name, info in users.items():
        if not isinstance(info, dict):
            continue
        
        # Очищаємо telegram_username
        telegram = info.get("telegram_username", "")
        if telegram:
            cleaned = clean_telegram_username(telegram)
            if cleaned != telegram:
                info["telegram_username"] = cleaned
                updated_count += 1
                cleaned_users.append(f"{name}: '{telegram}' -> '{cleaned}'")
        
        # Очищаємо manager_telegram
        manager_tg = info.get("manager_telegram", "")
        if manager_tg:
            cleaned = clean_telegram_username(manager_tg)
            if cleaned != manager_tg:
                info["manager_telegram"] = cleaned
                updated_count += 1
                cleaned_users.append(f"{name} (manager): '{manager_tg}' -> '{cleaned}'")
    
    if updated_count > 0:
        print(f"Очищено {updated_count} записів:\n")
        for item in cleaned_users[:20]:  # Показуємо перші 20
            print(f"  - {item}")
        
        if len(cleaned_users) > 20:
            print(f"\n  ... та ще {len(cleaned_users) - 20} записів")
        
        # Зберігаємо
        if save_users(data):
            print(f"\n✅ Дані успішно збережено!")
        else:
            print(f"\n❌ Помилка при збереженні")
            return 1
    else:
        print("✅ Всі дані вже чисті, нічого оновлювати не потрібно")
    
    print("\n" + "=" * 80)
    return 0


if __name__ == '__main__':
    sys.exit(main())
