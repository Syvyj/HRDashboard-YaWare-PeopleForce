#!/usr/bin/env python3
"""
Повний матчинг Control файлів з user_schedules використовуючи CSV трекера.
Оновлює user_schedules.json додаючи control_manager, department, team.
"""
import csv
import json
from pathlib import Path
from datetime import datetime
from shutil import copy2
from typing import Dict, List, Tuple
from difflib import SequenceMatcher


def normalize_name(name: str) -> str:
    """Нормалізує ім'я для порівняння."""
    return name.lower().strip().replace('\n', ' ')


def similarity(a: str, b: str) -> float:
    """Вирахову схожість між двома строками."""
    return SequenceMatcher(None, a, b).ratio()


def load_yaware_csv(csv_path: str) -> Dict[str, str]:
    """
    Завантажує CSV з трекера: email -> full_name mapping.
    
    Returns:
        dict: {email: full_name}
    """
    mapping = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get('Email', '').strip().lower()
            name = row.get('Имя', '').strip()
            if email and name:
                mapping[email] = name
    return mapping


def match_control_to_csv(
    control_users: List[Dict],
    csv_mapping: Dict[str, str]
) -> Tuple[Dict[str, Dict], List[Dict]]:
    """
    Матчить користувачів з Control файлів до email через CSV трекера.
    
    Returns:
        Tuple: (matched_by_email, unmatched)
    """
    matched = {}
    unmatched = []
    
    for control_user in control_users:
        control_name = normalize_name(control_user['name'])
        best_match_email = None
        best_score = 0.0
        
        # Шукаємо найкраще співпадіння по імені в CSV
        for email, csv_name in csv_mapping.items():
            csv_normalized = normalize_name(csv_name)
            score = similarity(control_name, csv_normalized)
            
            if score > best_score:
                best_score = score
                best_match_email = email
        
        # Якщо схожість > 85%, вважаємо співпадінням
        if best_score > 0.85 and best_match_email:
            matched[best_match_email] = {
                **control_user,
                'matched_csv_name': csv_mapping[best_match_email],
                'match_score': best_score
            }
        else:
            unmatched.append({
                **control_user,
                'best_match_email': best_match_email,
                'best_match_name': csv_mapping.get(best_match_email, '') if best_match_email else None,
                'best_match_score': best_score
            })
    
    return matched, unmatched


def update_user_schedules_with_control_data(
    user_schedules_path: str,
    matched_data: Dict[str, Dict]
) -> Dict:
    """
    Оновлює user_schedules.json додаючи control_manager, department, team.
    
    Returns:
        dict: Статистика оновлення
    """
    # Завантажуємо user_schedules
    with open(user_schedules_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    users = data.get('users', {})
    
    # Статистика
    stats = {
        'total_in_schedules': len(users),
        'updated': 0,
        'not_found': 0
    }
    
    # Оновлюємо дані для змачених користувачів
    for full_name, user_data in users.items():
        email = user_data.get('email', '').strip().lower()
        
        if email in matched_data:
            control_info = matched_data[email]
            
            # Додаємо нові поля
            user_data['control_manager'] = control_info['control_manager']
            user_data['department'] = control_info['department']
            user_data['team'] = control_info['team']
            
            stats['updated'] += 1
        else:
            stats['not_found'] += 1
    
    # Оновлюємо metadata
    if '_metadata' not in data:
        data['_metadata'] = {}
    
    data['_metadata']['last_updated'] = datetime.now().isoformat()
    data['_metadata']['control_data_added'] = datetime.now().isoformat()
    data['_metadata']['control_users_matched'] = stats['updated']
    
    # Зберігаємо
    with open(user_schedules_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return stats


def main():
    """Головна функція."""
    config_dir = Path(__file__).resolve().parents[2] / 'config'
    downloads_dir = Path.home() / 'Downloads'
    
    print("=" * 80)
    print("ПОВНИЙ МАТЧИНГ CONTROL ФАЙЛІВ")
    print("=" * 80)
    
    # 1. Завантажуємо parsed control data
    control_parsed_file = config_dir / 'control_managers_parsed.json'
    with open(control_parsed_file, 'r', encoding='utf-8') as f:
        control_data = json.load(f)
    
    all_control_users = control_data['manager_1'] + control_data['manager_2']
    print(f"\n📊 Control файли:")
    print(f"   Manager 1: {len(control_data['manager_1'])} користувачів")
    print(f"   Manager 2: {len(control_data['manager_2'])} користувачів")
    print(f"   Всього: {len(all_control_users)} користувачів")
    
    # 2. Завантажуємо CSV трекера
    csv_file = downloads_dir / "Активные сотрудники - Vladislav  Korobiy (1 окт. 2025г).xlsx - Sheet1.csv"
    
    if not csv_file.exists():
        print(f"\n❌ CSV файл не знайдено: {csv_file}")
        return
    
    print(f"\n📄 Завантажуємо CSV трекера: {csv_file.name}")
    csv_mapping = load_yaware_csv(str(csv_file))
    print(f"   ✅ Знайдено {len(csv_mapping)} записів")
    
    # 3. Матчимо Control користувачів через CSV
    print(f"\n🔍 Пошук співпадінь через CSV трекера...")
    matched, unmatched = match_control_to_csv(all_control_users, csv_mapping)
    
    print(f"\n✅ Результати матчингу:")
    print(f"   Знайдено: {len(matched)} користувачів")
    print(f"   Не знайдено: {len(unmatched)} користувачів")
    
    # Показуємо перші 10
    print(f"\n📋 Перші 10 співпадінь:")
    for i, (email, data) in enumerate(list(matched.items())[:10], 1):
        print(f"   {i}. {data['name']} → {email}")
        print(f"      CSV name: {data['matched_csv_name']}")
        print(f"      Score: {data['match_score']:.2%}")
        print(f"      Dept: {data['department']}, Team: {data['team']}, CM: {data['control_manager']}")
    
    # Показуємо не знайдені
    if unmatched:
        print(f"\n❌ Не знайдені користувачі ({len(unmatched)}):")
        for i, user in enumerate(unmatched, 1):
            print(f"   {i}. {user['name']} (Dept: {user['department']})")
            if user.get('best_match_name'):
                print(f"      Найкраще: {user['best_match_name']} ({user['best_match_score']:.2%})")
    
    # 4. Створюємо backup і оновлюємо user_schedules
    user_schedules_file = config_dir / 'user_schedules.json'
    backup_file = config_dir / f'user_schedules.json.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    
    print(f"\n💾 Створюємо backup: {backup_file.name}")
    copy2(user_schedules_file, backup_file)
    
    print(f"\n🔄 Оновлюємо user_schedules.json...")
    stats = update_user_schedules_with_control_data(str(user_schedules_file), matched)
    
    # Фінальна статистика
    print(f"\n" + "=" * 80)
    print("ФІНАЛЬНА СТАТИСТИКА:")
    print("=" * 80)
    print(f"Всього в user_schedules: {stats['total_in_schedules']}")
    print(f"Оновлено (додано control_manager, dept, team): {stats['updated']}")
    print(f"Без Control даних: {stats['not_found']}")
    
    # Зберігаємо фінальний mapping для review
    output_file = config_dir / 'control_managers_matched.json'
    output_data = {
        'matched': {email: data for email, data in matched.items()},
        'unmatched': unmatched,
        'stats': {
            'total_control_users': len(all_control_users),
            'matched': len(matched),
            'unmatched': len(unmatched),
            'user_schedules_updated': stats['updated']
        }
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Готово!")
    print(f"📄 Mapping збережено в: {output_file.name}")
    print(f"💾 Backup: {backup_file.name}")
    print("=" * 80)


if __name__ == "__main__":
    main()
