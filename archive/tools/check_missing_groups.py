#!/usr/bin/env python3
"""Перевірка яких користувачів немає в CSV файлі з трекера."""
import json
import csv
from pathlib import Path

config_dir = Path(__file__).resolve().parent / 'config'
downloads_dir = Path.home() / 'Downloads'

# Завантажуємо user_schedules
user_schedules_file = config_dir / 'user_schedules.json'
with open(user_schedules_file, 'r', encoding='utf-8') as f:
    data = json.load(f)
    users = data.get('users', {})

# Завантажуємо CSV з трекера
csv_files = list(downloads_dir.glob("Активные сотрудники*.csv"))
if not csv_files:
    print("CSV файл не знайдено!")
    exit(1)

csv_file = csv_files[0]
csv_emails = set()

# Спробуємо різні кодування
encodings = ['utf-8', 'windows-1251', 'cp1251', 'latin-1']
reader_data = None

for encoding in encodings:
    try:
        with open(csv_file, 'r', encoding=encoding) as f:
            reader = csv.DictReader(f)
            reader_data = list(reader)
            print(f"✅ Успішно прочитано CSV з кодуванням: {encoding}")
            break
    except UnicodeDecodeError:
        continue

if not reader_data:
    print("❌ Не вдалося прочитати CSV файл")
    exit(1)

for row in reader_data:
    email = row.get('Email', '').strip().lower()
    if email:
        csv_emails.add(email)

print(f"📊 Статистика:")
print(f"   User schedules: {len(users)} користувачів")
print(f"   CSV з трекера: {len(csv_emails)} користувачів")

# Знаходимо користувачів без групи
users_without_group = []
for full_name, user_data in users.items():
    email = user_data.get('email', '').lower()
    
    if not user_data.get('yaware_group'):
        users_without_group.append({
            'name': full_name,
            'email': email,
            'in_csv': email in csv_emails
        })

print(f"\n❌ Користувачі без yaware_group: {len(users_without_group)}")
print("=" * 80)

for i, user in enumerate(users_without_group, 1):
    status = "✓ Є в CSV" if user['in_csv'] else "✗ Немає в CSV"
    print(f"{i}. {user['name']}")
    print(f"   Email: {user['email']}")
    print(f"   {status}")
    print()
