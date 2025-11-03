#!/usr/bin/env python3
"""Фікс скорочених імен в control_managers_parsed.json."""
import json
from pathlib import Path

# Mapping скорочені → повні
SHORT_TO_FULL = {
    'v.dupenko': 'Dupenko Valeria',
    'd.galeev': 'Galeev Daniel',
    'n.murygin': 'Murygin Nikolai',
    'r.tenditnik': 'Tenditnik Roman',
    'm.vykhodtseva': 'Vykhodtseva Mariia',
    'm.sarkisov': 'Sarkisov Moses',
    'd.likhobaba': 'Likhobaba Daniil',
    's.masalov': 'Masalov Semyon',
    'd.kolos': 'Danyl Kolos',  # в базі ім'я-прізвище навпаки
    'a.dobrorodnia': 'Alina Dobrorodnia',  # в базі ім'я-прізвище навпаки
    'v.sapov': 'Sapov Viacheslav',
    'a.pryimak': 'Pryimak Artur',
}

config_dir = Path(__file__).resolve().parent / 'config'

with open(config_dir / 'control_managers_parsed.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("=" * 80)
print("ЗАМІНА СКОРОЧЕНИХ ІМЕН НА ПОВНІ")
print("=" * 80)

fixed = 0
not_found_names = []

for manager_key in ['manager_1', 'manager_2']:
    for entry in data[manager_key]:
        short_name = entry['name']
        if short_name in SHORT_TO_FULL:
            full_name = SHORT_TO_FULL[short_name]
            entry['name'] = full_name
            fixed += 1
            print(f"✅ {short_name:20} → {full_name}")
        elif '.' in short_name:
            not_found_names.append(short_name)

# Зберігаємо
with open(config_dir / 'control_managers_parsed.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"\n📊 Результат:")
print(f"   Замінено: {fixed}")
print(f"   Не знайдено mapping: {len(not_found_names)}")

if not_found_names:
    print(f"\n❌ Імена без mapping (потребують ручного додавання):")
    for name in not_found_names:
        print(f"   {name}")

print(f"\n✅ Файл збережено: control_managers_parsed.json")
print("=" * 80)
