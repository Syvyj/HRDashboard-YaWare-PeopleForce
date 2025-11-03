#!/usr/bin/env python3
"""Фінальний матчинг з manual mapping для складних випадків."""
import json
from pathlib import Path
from datetime import datetime
from shutil import copy2

# Manual mapping Control ім'я → user_schedules ім'я
MANUAL_MAPPING = {
    'Masiuk Veranika': 'Veranika Masiuk',
    'Roman Kazmirchuk': 'Kazmirchuk Roman',
    'Maksym Kondras': 'Kondras Maksym',
    # Ці видалені з бази або мають інші написання які не матчаться
    'Marcinkute Ilona': None,  # видалена
}

config_dir = Path(__file__).resolve().parent / 'config'

print("=" * 80)
print("ФІНАЛЬНЕ ОНОВЛЕННЯ USER_SCHEDULES З MANUAL MAPPING")
print("=" * 80)

# Завантажуємо
with open(config_dir / 'control_managers_parsed.json', 'r', encoding='utf-8') as f:
    control_data = json.load(f)

with open(config_dir / 'user_schedules.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

users = data.get('users', {})

# Backup
backup = config_dir / f'user_schedules.json.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}'
copy2(config_dir / 'user_schedules.json', backup)
print(f"💾 Backup: {backup.name}\n")

# Застосовуємо manual mapping
updated = 0
skipped = 0

for control_name, schedule_name in MANUAL_MAPPING.items():
    if schedule_name is None:
        print(f"⊘  {control_name:30} → ПРОПУЩЕНО (видалений користувач)")
        skipped += 1
        continue
    
    if schedule_name not in users:
        print(f"❌ {control_name:30} → {schedule_name} НЕ ЗНАЙДЕНО")
        continue
    
    # Знаходимо Control дані
    control_entry = None
    for c in control_data['manager_1'] + control_data['manager_2']:
        if c['name'] == control_name:
            control_entry = c
            break
    
    if not control_entry:
        print(f"⚠️  {control_name:30} → немає в Control файлах")
        continue
    
    # Оновлюємо
    users[schedule_name]['control_manager'] = control_entry['control_manager']
    users[schedule_name]['department'] = control_entry['department']
    users[schedule_name]['team'] = control_entry['team']
    updated += 1
    print(f"✅ {control_name:30} → {schedule_name}")

# Зберігаємо
with open(config_dir / 'user_schedules.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\n{'=' * 80}")
print(f"РЕЗУЛЬТАТ:")
print(f"{'=' * 80}")
print(f"✅ Оновлено: {updated}")
print(f"⊘  Пропущено: {skipped}")
print(f"\n✅ Файл збережено!")
print("=" * 80)
