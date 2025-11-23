#!/usr/bin/env python3
"""
Скрипт для одноразового автопризначення control_manager всім користувачам
на основі їх division_name.

Логіка:
- Agency → control_manager = 1
- Apps, Adnetwork, Consulting → control_manager = 2
- Інші → control_manager = 2

Користувачі з ручним override (manual_overrides.control_manager) пропускаються.
"""

import sys
from pathlib import Path

# Додаємо батьківську директорію в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker_alert.services import user_manager as schedule_user_manager
from tracker_alert.services.schedule_utils import has_manual_override
from tracker_alert.services.control_manager import auto_assign_control_manager


def main():
    """Головна функція для автопризначення control_manager."""
    print("🚀 Починаємо автопризначення control_manager...")
    
    # Завантажуємо користувачів
    data = schedule_user_manager.load_users()
    users = data.get("users", {}) if isinstance(data, dict) else {}
    
    if not users:
        print("❌ Не знайдено користувачів у user_schedules.json")
        return
    
    updated_count = 0
    skipped_manual = 0
    skipped_no_division = 0
    unchanged = 0
    
    print(f"📊 Всього користувачів: {len(users)}")
    print()
    
    for name, info in users.items():
        if not isinstance(info, dict):
            continue
        
        # Пропускаємо якщо є ручний override
        if has_manual_override(info, 'control_manager'):
            skipped_manual += 1
            print(f"⏭️  {name}: пропущено (є ручний override)")
            continue
        
        # Отримуємо division_name
        division_name = info.get('division_name', '')
        if not division_name:
            skipped_no_division += 1
            print(f"⚠️  {name}: пропущено (немає division_name)")
            continue
        
        # Визначаємо автоматичний control_manager
        auto_manager = auto_assign_control_manager(division_name)
        current_manager = info.get('control_manager')
        
        if current_manager == auto_manager:
            unchanged += 1
            print(f"✓ {name}: вже призначено {auto_manager} (division: {division_name})")
            continue
        
        # Оновлюємо
        info['control_manager'] = auto_manager
        updated_count += 1
        print(f"✅ {name}: {current_manager} → {auto_manager} (division: {division_name})")
    
    print()
    print("=" * 70)
    print(f"📈 Результати:")
    print(f"  Оновлено: {updated_count}")
    print(f"  Без змін: {unchanged}")
    print(f"  Пропущено (ручний override): {skipped_manual}")
    print(f"  Пропущено (немає division): {skipped_no_division}")
    print("=" * 70)
    
    if updated_count > 0:
        confirm = input("\n💾 Зберегти зміни? (yes/no): ").strip().lower()
        if confirm in ('yes', 'y', 'так', 'т'):
            if schedule_user_manager.save_users(data):
                print("✅ Зміни збережено успішно!")
            else:
                print("❌ Помилка при збереженні!")
                sys.exit(1)
        else:
            print("❌ Зміни не збережено (скасовано користувачем)")
    else:
        print("\nℹ️  Немає змін для збереження")


if __name__ == "__main__":
    main()
