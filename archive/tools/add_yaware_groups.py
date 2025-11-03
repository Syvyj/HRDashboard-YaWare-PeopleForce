#!/usr/bin/env python3
"""Додає інформацію про YaWare групи до user_schedules.json з Excel файлу трекера."""
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from shutil import copy2
from typing import Dict


def normalize_name(name: str) -> str:
    """Нормалізує ім'я для порівняння."""
    return name.lower().strip().replace('\n', ' ')


def load_yaware_excel(excel_path: Path) -> tuple[Dict[str, str], Dict[str, str]]:
    """
    Завантажує Excel файл з YaWare груп користувачів.
    
    Returns:
        Tuple: (email_to_group, name_to_group)
    """
    email_groups = {}
    name_groups = {}
    
    df = pd.read_excel(excel_path)
    
    for _, row in df.iterrows():
        email = str(row.get('Email', '')).strip().lower()
        name = str(row.get('Имя', '')).strip()
        group = str(row.get('Группа', '')).strip()
        
        # Додаємо по email якщо є
        if email and group and email != 'nan':
            email_groups[email] = group
        
        # Додаємо по імені завжди
        if name and group and name != 'nan':
            normalized_name = normalize_name(name)
            name_groups[normalized_name] = group
    
    return email_groups, name_groups


def update_user_schedules_with_groups(user_schedules_path: str, yaware_groups: dict) -> dict:
    """
    Оновлює user_schedules.json додаючи yaware_group поле.
    
    Returns:
        dict: Статистика оновлення
    """
    # Завантажуємо user_schedules
    with open(user_schedules_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    users = data.get('users', {})
    
    # Статистика
    stats = {
        'total_users': len(users),
        'matched': 0,
        'unmatched': 0,
        'already_had_group': 0
    }
    
    # Оновлюємо групи
    for full_name, user_data in users.items():
        email = user_data.get('email', '').strip().lower()
        
        if email in yaware_groups:
            # Перевіряємо чи вже є група
            if 'yaware_group' in user_data:
                stats['already_had_group'] += 1
            
            user_data['yaware_group'] = yaware_groups[email]
            stats['matched'] += 1
        else:
            stats['unmatched'] += 1
    
    # Оновлюємо metadata
    if '_metadata' not in data:
        data['_metadata'] = {}
    
    data['_metadata']['last_updated'] = datetime.now().isoformat()
    data['_metadata']['yaware_groups_added'] = datetime.now().isoformat()
    
    # Зберігаємо оновлений файл
    with open(user_schedules_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return stats


def main():
    """Головна функція."""
    config_dir = Path(__file__).resolve().parents[2] / 'config'
    
    print("=" * 80)
    print("ДОДАВАННЯ YAWARE ГРУП ДО USER_SCHEDULES")
    print("=" * 80)
    
    # Використовуємо Excel файл з config
    excel_file = config_dir / 'Active_Users.xlsx'
    if not excel_file.exists():
        print(f"\n❌ Excel файл не знайдено: {excel_file}")
        return
    
    print(f"\n📄 Використовуємо Excel: {excel_file.name}")
    
    # Завантажуємо групи з Excel
    print(f"\n🔍 Читаємо групи з Excel...")
    yaware_groups = load_yaware_excel(excel_file)
    print(f"   ✅ Знайдено {len(yaware_groups)} користувачів з групами")
    
    # Показуємо приклади груп
    print(f"\n📋 Приклади груп з Excel:")
    for i, (email, group) in enumerate(list(yaware_groups.items())[:10], 1):
        print(f"   {i}. {email} → {group}")
    
    # Створюємо backup
    user_schedules_file = config_dir / 'user_schedules.json'
    backup_file = config_dir / f'user_schedules.json.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    
    print(f"\n💾 Створюємо backup: {backup_file.name}")
    copy2(user_schedules_file, backup_file)
    
    # Оновлюємо user_schedules
    print(f"\n🔄 Оновлюємо user_schedules.json...")
    stats = update_user_schedules_with_groups(str(user_schedules_file), yaware_groups)
    
    # Виводимо статистику
    print(f"\n" + "=" * 80)
    print("СТАТИСТИКА:")
    print("=" * 80)
    print(f"Всього користувачів в user_schedules: {stats['total_users']}")
    print(f"Знайдено співпадінь (додано групи): {stats['matched']}")
    print(f"Не знайдено в CSV: {stats['unmatched']}")
    print(f"Вже мали групу: {stats['already_had_group']}")
    
    print(f"\n✅ user_schedules.json успішно оновлено!")
    print(f"💾 Backup збережено в: {backup_file.name}")
    print("=" * 80)


if __name__ == "__main__":
    main()
