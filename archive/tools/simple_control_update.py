#!/usr/bin/env python3
"""Простий матчинг Control файлів з user_schedules напряму по іменах."""
import json
from pathlib import Path
from datetime import datetime
from shutil import copy2
from difflib import SequenceMatcher


def normalize_name(name: str) -> str:
    """Нормалізує ім'я."""
    return name.lower().strip().replace('\n', ' ')


def similarity(a: str, b: str) -> float:
    """Схожість між строками."""
    return SequenceMatcher(None, a, b).ratio()


config_dir = Path(__file__).resolve().parent / 'config'

print("=" * 80)
print("ОНОВЛЕННЯ USER_SCHEDULES З CONTROL ДАНИМИ")
print("=" * 80)

# Завантажуємо parsed control data
with open(config_dir / 'control_managers_parsed.json', 'r', encoding='utf-8') as f:
    control_data = json.load(f)

# Завантажуємо user_schedules
with open(config_dir / 'user_schedules.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

users = data.get('users', {})

print(f"\n📊 Дані:")
print(f"   User schedules: {len(users)}")
print(f"   Control Manager 1: {len(control_data['manager_1'])}")
print(f"   Control Manager 2: {len(control_data['manager_2'])}")

# Створюємо mapping Control користувачів по нормалізованих іменах
all_control = control_data['manager_1'] + control_data['manager_2']
control_by_name = {}

for c in all_control:
    normalized = normalize_name(c['name'])
    control_by_name[normalized] = c

print(f"   Control mapping: {len(control_by_name)} унікальних імен")

# Backup
backup = config_dir / f'user_schedules.json.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}'
copy2(config_dir / 'user_schedules.json', backup)
print(f"\n💾 Backup: {backup.name}")

print(f"\n🔍 Матчинг...\n")

exact = 0
fuzzy = 0
not_found = []

for full_name, user_data in users.items():
    normalized = normalize_name(full_name)
    
    # Точне співпадіння
    if normalized in control_by_name:
        c = control_by_name[normalized]
        user_data['control_manager'] = c['control_manager']
        user_data['department'] = c['department']
        user_data['team'] = c['team']
        exact += 1
    else:
        # Fuzzy match
        best = None
        best_score = 0.0
        
        for cname, cdata in control_by_name.items():
            score = similarity(normalized, cname)
            if score > best_score:
                best_score = score
                best = (cname, cdata)
        
        if best_score > 0.85:
            user_data['control_manager'] = best[1]['control_manager']
            user_data['department'] = best[1]['department']
            user_data['team'] = best[1]['team']
            fuzzy += 1
            print(f"   ≈ {full_name} → {best[1]['name']} ({best_score:.1%})")
        else:
            not_found.append((full_name, best[1]['name'] if best else None, best_score))

# Зберігаємо
with open(config_dir / 'user_schedules.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\n" + "=" * 80)
print("РЕЗУЛЬТАТ:")
print("=" * 80)
print(f"✅ Точних: {exact}")
print(f"≈ Fuzzy (>85%): {fuzzy}")
print(f"❌ Не знайдено: {len(not_found)}")
print(f"\n📊 Покриття: {exact + fuzzy}/{len(users)} ({(exact + fuzzy)/len(users)*100:.1f}%)")

if not_found:
    print(f"\n❌ Не змачені користувачі:")
    for name, best_match, score in not_found[:10]:
        print(f"   {name}")
        if best_match:
            print(f"      Найкраще: {best_match} ({score:.1%})")

print(f"\n✅ Готово!")
print("=" * 80)
