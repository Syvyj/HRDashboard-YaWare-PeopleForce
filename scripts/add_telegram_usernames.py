"""
Скрипт для автоматичного додавання telegram_username всім користувачам.
Генерує username у форматі Прізвище_Ім'я з повного імені.
"""
import json
import sys
from pathlib import Path

# Додаємо кореневу директорію в path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tracker_alert.services.user_manager import load_users, save_users


def generate_telegram_username(full_name: str) -> str:
    """
    Генерує telegram username з повного імені у форматі Прізвище_Ім'я.
    """
    if not full_name:
        return ''
    
    parts = full_name.strip().split()
    if len(parts) < 2:
        return parts[0] if parts else ''
    
    # Беремо перше слово (прізвище) та друге слово (ім'я)
    surname = parts[0]
    first_name = parts[1]
    
    return f"{surname}_{first_name}"


def add_telegram_usernames():
    """Додає telegram_username всім користувачам які його не мають."""
    
    data = load_users()
    users = data.get('users', {})
    
    updated_count = 0
    skipped_count = 0
    
    for name, user_info in users.items():
        # Пропускаємо якщо вже є telegram_username
        if user_info.get('telegram_username'):
            skipped_count += 1
            continue
        
        # Генеруємо username
        telegram_username = generate_telegram_username(name)
        if telegram_username:
            user_info['telegram_username'] = telegram_username
            updated_count += 1
            print(f"✅ {name} -> @{telegram_username}")
        else:
            print(f"⚠️  {name} -> пропущено (не вдалося згенерувати)")
    
    if updated_count > 0:
        if save_users(data):
            print(f"\n✅ Успішно оновлено: {updated_count} користувачів")
            print(f"⏭️  Пропущено (вже є telegram): {skipped_count} користувачів")
        else:
            print("\n❌ Помилка збереження!")
            return False
    else:
        print(f"\nℹ️  Немає користувачів для оновлення")
        print(f"✓  Всі {skipped_count} користувачів вже мають telegram_username")
    
    return True


if __name__ == '__main__':
    print("🚀 Початок додавання telegram usernames...\n")
    success = add_telegram_usernames()
    sys.exit(0 if success else 1)
