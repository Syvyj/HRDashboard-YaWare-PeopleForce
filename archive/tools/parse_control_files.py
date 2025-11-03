#!/usr/bin/env python3
"""Парсер Control Excel файлів для витягування інформації про департаменти та команди."""
import pandas as pd
import json
from pathlib import Path
from typing import List, Dict, Any


def parse_control_excel(filepath: str, control_manager_id: int) -> List[Dict[str, Any]]:
    """
    Парсить Control Excel файл та витягує інформацію про користувачів.
    
    Кожен користувач займає 8 рядків:
    1. Department | Team | Name | "Plan Start"
    2. (empty) | (empty) | (empty) | HH:MM:SS (час)
    3. (empty)
    4. (empty) | (empty) | (empty) | "Country" або "Location"
    5. (empty) | (empty) | (empty) | Країна/місто
    6-8. (empty)
    
    Args:
        filepath: Шлях до Excel файлу
        control_manager_id: ID контроль-менеджера (1 або 2)
        
    Returns:
        Список словників з інформацією про користувачів
    """
    df = pd.read_excel(filepath)
    users = []
    
    # Запам'ятовуємо останній Department (він вказується один раз для групи)
    current_department = None
    
    # Читаємо по 8 рядків за раз
    i = 0
    while i < len(df):
        row = df.iloc[i]
        
        # Перевіряємо чи це початок нового користувача
        # (Department не NaN або Team не NaN або Name не NaN)
        department = row.iloc[0] if pd.notna(row.iloc[0]) else None
        team = row.iloc[1] if pd.notna(row.iloc[1]) else None
        name = row.iloc[2] if pd.notna(row.iloc[2]) else None
        
        # Оновлюємо поточний Department якщо знайдено новий
        if department:
            current_department = department
        # Оновлюємо поточний Department якщо знайдено новий
        if department:
            current_department = department
        
        # Якщо знайшли ім'я користувача
        if name and pd.notna(name):
            user_data = {
                'control_manager': control_manager_id,
                'department': current_department,  # Використовуємо збережений Department
                'team': team,
                'name': str(name).strip().replace('\n', ' '),
                'plan_start': None,
                'location': None
            }
            
            # Наступний рядок містить Plan Start час
            if i + 1 < len(df):
                time_row = df.iloc[i + 1]
                time_val = time_row.iloc[3] if len(time_row) > 3 else None
                if pd.notna(time_val):
                    # Перетворюємо на строку HH:MM
                    if isinstance(time_val, str):
                        user_data['plan_start'] = time_val.strip()
                    else:
                        # Якщо це datetime, витягуємо час
                        try:
                            user_data['plan_start'] = str(time_val).split()[1][:5] if ' ' in str(time_val) else str(time_val)[:5]
                        except:
                            user_data['plan_start'] = str(time_val)
            
            # Рядок +4 містить Location
            if i + 4 < len(df):
                location_row = df.iloc[i + 4]
                location_val = location_row.iloc[3] if len(location_row) > 3 else None
                if pd.notna(location_val):
                    user_data['location'] = str(location_val).strip()
            
            users.append(user_data)
            
            # Переходимо до наступного блоку (+ 8 рядків)
            i += 8
        else:
            # Якщо не знайшли ім'я, переходимо на наступний рядок
            i += 1
    
    return users


def main():
    """Парсить обидва Control файли та виводить результат."""
    config_dir = Path(__file__).resolve().parents[2] / 'config'
    
    print("=" * 80)
    print("ПАРСИНГ CONTROL FILES")
    print("=" * 80)
    
    # Парсимо Control_1
    control_1_path = config_dir / 'Control_1.xlsx'
    if control_1_path.exists():
        print(f"\n📄 Парсинг {control_1_path.name}...")
        users_1 = parse_control_excel(str(control_1_path), control_manager_id=1)
        print(f"   Знайдено {len(users_1)} користувачів")
        
        # Показуємо перших 5
        print("\n   Перші 5 користувачів:")
        for i, user in enumerate(users_1[:5], 1):
            print(f"   {i}. {user['name']}")
            print(f"      Department: {user['department']}")
            print(f"      Team: {user['team']}")
            print(f"      Plan Start: {user['plan_start']}")
            print(f"      Location: {user['location']}")
    else:
        print(f"\n❌ Файл {control_1_path} не знайдено")
        users_1 = []
    
    # Парсимо Control_2
    control_2_path = config_dir / 'Control_2.xlsx'
    if control_2_path.exists():
        print(f"\n📄 Парсинг {control_2_path.name}...")
        users_2 = parse_control_excel(str(control_2_path), control_manager_id=2)
        print(f"   Знайдено {len(users_2)} користувачів")
        
        # Показуємо перших 5
        print("\n   Перші 5 користувачів:")
        for i, user in enumerate(users_2[:5], 1):
            print(f"   {i}. {user['name']}")
            print(f"      Department: {user['department']}")
            print(f"      Team: {user['team']}")
            print(f"      Plan Start: {user['plan_start']}")
            print(f"      Location: {user['location']}")
    else:
        print(f"\n❌ Файл {control_2_path} не знайдено")
        users_2 = []
    
    # Статистика
    print("\n" + "=" * 80)
    print("СТАТИСТИКА:")
    print("=" * 80)
    print(f"Control Manager 1: {len(users_1)} користувачів")
    print(f"Control Manager 2: {len(users_2)} користувачів")
    print(f"Всього: {len(users_1) + len(users_2)} користувачів")
    
    # Зберігаємо результат у JSON для подальшого використання
    output_file = config_dir / 'control_managers_parsed.json'
    all_users = {
        'manager_1': users_1,
        'manager_2': users_2
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_users, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ Результат збережено в {output_file}")
    print("=" * 80)


if __name__ == "__main__":
    main()
