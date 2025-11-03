#!/usr/bin/env python3
"""Додає групи для 12 користувачів які є в Active_Users.xlsx але без email."""
import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from shutil import copy2

# 12 користувачів без груп
missing_users = [
    "Chernov Leonid",
    "Dmytrenko Anna",
    "Hryvtsova Anastasiia",
    "Lukashov Vasyl",
    "Pryimak Artur",
    "Shinkus Aleksandr",
    "Smirnov Sergey",
    "Torianyk Haiana",
    "Vcherashniaya Aliaksandra",
    "Yekhlakov Viktor",
    "Zhara Lilia",
    "Postoi Anton"
]

def normalize_name(name: str) -> str:
    """Нормалізує ім'я для порівняння."""
    return name.lower().strip()

config_dir = Path(__file__).resolve().parent / 'config'

print("=" * 80)
print("ДОДАВАННЯ ГРУП ДЛЯ 12 КОРИСТУВАЧІВ")
print("=" * 80)

# Завантажуємо Active_Users.xlsx
excel_file = config_dir / 'Active_Users.xlsx'
df = pd.read_excel(excel_file)

print(f"\n📄 Читаємо {excel_file.name}")
print(f"   Рядків: {len(df)}")

# Створюємо mapping по іменах
name_to_group = {}
for _, row in df.iterrows():
    name = str(row.get('Имя', '')).strip()
    group = str(row.get('Группа', '')).strip()
    if name and group and name != 'nan' and group != 'nan':
        name_to_group[normalize_name(name)] = group

print(f"\n🔍 Шукаємо групи для 12 користувачів...")

# Завантажуємо user_schedules
user_schedules_file = config_dir / 'user_schedules.json'
with open(user_schedules_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

users = data.get('users', {})

# Створюємо backup
backup_file = config_dir / f'user_schedules.json.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}'
copy2(user_schedules_file, backup_file)
print(f"\n💾 Backup: {backup_file.name}")

# Оновлюємо 12 користувачів
updated = 0
not_found = []

for full_name, user_data in users.items():
    # Перевіряємо чи це один з 12
    if full_name in missing_users:
        normalized = normalize_name(full_name)
        
        if normalized in name_to_group:
            group = name_to_group[normalized]
            user_data['yaware_group'] = group
            updated += 1
            print(f"\n✅ {full_name}")
            print(f"   Email: {user_data.get('email')}")
            print(f"   Group: {group}")
        else:
            not_found.append(full_name)
            print(f"\n❌ {full_name} - не знайдено в Active_Users.xlsx")

# Зберігаємо оновлений файл
with open(user_schedules_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\n" + "=" * 80)
print("РЕЗУЛЬТАТ:")
print("=" * 80)
print(f"Оновлено: {updated}")
print(f"Не знайдено: {len(not_found)}")
if not_found:
    print(f"Список не знайдених: {', '.join(not_found)}")
print(f"\n✅ user_schedules.json оновлено!")
print("=" * 80)
