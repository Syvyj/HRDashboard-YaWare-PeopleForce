#!/usr/bin/env python3
"""Матчинг імен з Control файлів до email адрес з user_schedules.json."""
import json
from pathlib import Path
from typing import Dict, List, Tuple
from difflib import SequenceMatcher


def normalize_name(name: str) -> str:
    """Нормалізує ім'я для порівняння."""
    return name.lower().strip().replace('\n', ' ')


def similarity(a: str, b: str) -> float:
    """Вирахову схожість між двома строками."""
    return SequenceMatcher(None, a, b).ratio()


def match_names_to_emails(
    control_users: List[Dict],
    user_schedules: Dict
) -> Tuple[Dict[str, Dict], List[Dict]]:
    """
    Матчить імена з Control файлів до email з user_schedules.
    
    Args:
        control_users: Список користувачів з Control файлів
        user_schedules: Словник з user_schedules.json
        
    Returns:
        Tuple: (matched_users, unmatched_users)
            - matched_users: {email: control_data}
            - unmatched_users: [{control_data}]
    """
    matched = {}
    unmatched = []
    
    # Створюємо список з email та full name з user_schedules
    schedule_users = []
    for full_name, data in user_schedules.items():
        email = data.get('email', '')
        if email:
            schedule_users.append({
                'email': email,
                'full_name': full_name,
                'normalized': normalize_name(full_name)
            })
    
    # Для кожного користувача з Control файлу шукаємо найкраще співпадіння
    for control_user in control_users:
        control_name = control_user['name']
        control_normalized = normalize_name(control_name)
        
        best_match = None
        best_score = 0.0
        
        for schedule_user in schedule_users:
            score = similarity(control_normalized, schedule_user['normalized'])
            
            if score > best_score:
                best_score = score
                best_match = schedule_user
        
        # Якщо схожість > 80%, вважаємо що це той самий користувач
        if best_score > 0.8 and best_match:
            matched[best_match['email']] = {
                **control_user,
                'matched_full_name': best_match['full_name'],
                'match_score': best_score
            }
        else:
            unmatched.append({
                **control_user,
                'best_match_name': best_match['full_name'] if best_match else None,
                'best_match_score': best_score
            })
    
    return matched, unmatched


def main():
    """Головна функція для матчингу."""
    config_dir = Path(__file__).resolve().parents[2] / 'config'
    
    print("=" * 80)
    print("МАТЧИНГ ІМЕН З EMAIL")
    print("=" * 80)
    
    # Завантажуємо parsed control data
    control_parsed_file = config_dir / 'control_managers_parsed.json'
    with open(control_parsed_file, 'r', encoding='utf-8') as f:
        control_data = json.load(f)
    
    # Завантажуємо user_schedules
    user_schedules_file = config_dir / 'user_schedules.json'
    with open(user_schedules_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        # Витягуємо users з правильного місця
        user_schedules = data.get('users', {})
    
    print(f"\n📊 Статистика:")
    print(f"   User schedules: {len(user_schedules)} користувачів")
    print(f"   Control Manager 1: {len(control_data['manager_1'])} користувачів")
    print(f"   Control Manager 2: {len(control_data['manager_2'])} користувачів")
    
    # Об'єднуємо всіх користувачів з обох Control файлів
    all_control_users = control_data['manager_1'] + control_data['manager_2']
    
    # Матчимо
    print(f"\n🔍 Пошук співпадінь...")
    matched, unmatched = match_names_to_emails(all_control_users, user_schedules)
    
    print(f"\n✅ Результати:")
    print(f"   Знайдено співпадінь: {len(matched)}")
    print(f"   Не знайдено: {len(unmatched)}")
    
    # Показуємо перші 10 співпадінь
    print(f"\n📋 Перші 10 співпадінь:")
    for i, (email, data) in enumerate(list(matched.items())[:10], 1):
        print(f"   {i}. {data['name']} → {email}")
        print(f"      Match score: {data['match_score']:.2%}")
        print(f"      Department: {data['department']}, Team: {data['team']}")
        print(f"      Control Manager: {data['control_manager']}")
    
    # Показуємо користувачів без співпадінь
    if unmatched:
        print(f"\n❌ Користувачі без співпадінь:")
        for i, user in enumerate(unmatched, 1):
            print(f"   {i}. {user['name']} (Department: {user['department']})")
            if user.get('best_match_name'):
                print(f"      Найкраще співпадіння: {user['best_match_name']} ({user['best_match_score']:.2%})")
    
    # Зберігаємо результат
    output_file = config_dir / 'control_managers_matched.json'
    output_data = {
        'matched': matched,
        'unmatched': unmatched,
        'stats': {
            'total_control_users': len(all_control_users),
            'matched': len(matched),
            'unmatched': len(unmatched)
        }
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Результат збережено в {output_file}")
    print("=" * 80)


if __name__ == "__main__":
    main()
