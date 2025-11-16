#!/usr/bin/env python3
"""Виправлення структури: переносимо Team з direction в team, застосовуємо inheritance."""

import json
from datetime import datetime

def fix_team_structure():
    """Виправити структуру team/direction."""
    
    print("=" * 100)
    print("🔄 ВИПРАВЛЕННЯ СТРУКТУРИ TEAM/DIRECTION")
    print("=" * 100)
    
    # Завантажуємо дані
    print("\n🔄 Завантажуємо user_schedules.json...")
    with open('config/user_schedules.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    users = data.get('users', {})
    print(f"✅ Завантажено {len(users)} користувачів")
    
    # Крок 1: Переносимо "Team" з direction_name в team_name
    print("\n🔄 Крок 1: Переносимо 'Team' з direction в team...")
    moved_count = 0
    
    for user_name, user_data in users.items():
        direction_name = user_data.get('direction_name', '')
        
        # Якщо в direction_name є слово "Team" → це насправді team
        if 'team' in direction_name.lower():
            user_data['team_name'] = direction_name
            user_data['team_id'] = user_data.get('direction_id')
            user_data['direction_name'] = ''
            user_data['direction_id'] = None
            moved_count += 1
            print(f"   ✅ {user_name}: '{direction_name}' → team_name")
    
    print(f"\n📊 Перенесено: {moved_count} користувачів")
    
    # Крок 2: Застосовуємо inheritance для порожніх direction
    print("\n🔄 Крок 2: Застосовуємо inheritance від team_lead...")
    
    # Створюємо індекс
    users_by_fullname = {}
    for user_name, user_data in users.items():
        users_by_fullname[user_name] = user_data
        normalized_name = user_name.replace(' ', '_')
        users_by_fullname[normalized_name] = user_data
    
    inherited_count = 0
    
    for user_name, user_data in users.items():
        # Якщо немає direction (після кроку 1)
        if not user_data.get('direction_name'):
            team_lead_name = user_data.get('team_lead', '').strip()
            
            if not team_lead_name:
                continue
            
            # Шукаємо team_lead
            team_lead_data = None
            search_variants = [
                team_lead_name,
                team_lead_name.replace('_', ' '),
                team_lead_name.replace(' ', '_')
            ]
            
            for variant in search_variants:
                if variant in users_by_fullname:
                    team_lead_data = users_by_fullname[variant]
                    break
            
            # Часткове співпадіння
            if not team_lead_data:
                for other_name in users_by_fullname.keys():
                    if team_lead_name.lower() in other_name.lower() or \
                       other_name.lower() in team_lead_name.lower():
                        team_lead_data = users_by_fullname[other_name]
                        break
            
            if team_lead_data and team_lead_data.get('direction_name'):
                user_data['direction_name'] = team_lead_data['direction_name']
                user_data['direction_id'] = team_lead_data.get('direction_id')
                inherited_count += 1
                print(f"   ✅ {user_name}: direction від {team_lead_name}")
    
    print(f"\n📊 Успадковано: {inherited_count} користувачів")
    
    # Оновлюємо metadata
    data['_metadata']['last_updated'] = str(datetime.now())
    
    # Зберігаємо
    print(f"\n💾 Зберігаємо зміни...")
    with open('config/user_schedules.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 100)
    print("✅ Структура успішно виправлена!")
    print(f"   Team перенесено: {moved_count}")
    print(f"   Direction успадковано: {inherited_count}")
    print("=" * 100)

if __name__ == '__main__':
    fix_team_structure()
