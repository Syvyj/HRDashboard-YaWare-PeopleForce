#!/usr/bin/env python3
"""Застосування inheritance логіки від team_lead для відсутніх полів."""

import json
from datetime import datetime

def apply_inheritance():
    """Застосувати inheritance логіку від team_lead."""
    
    print("=" * 100)
    print("🔄 ЗАСТОСУВАННЯ INHERITANCE ЛОГІКИ")
    print("=" * 100)
    
    # Завантажуємо поточні дані
    print("\n🔄 Завантажуємо user_schedules.json...")
    with open('config/user_schedules.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    users = data.get('users', {})
    print(f"✅ Завантажено {len(users)} користувачів")
    
    # Створюємо індекс для швидкого пошуку team_lead за іменем
    print("\n🔄 Будуємо індекс користувачів...")
    users_by_fullname = {}
    for user_name, user_data in users.items():
        users_by_fullname[user_name] = user_data
        # Також додаємо варіанти з підкресленням
        normalized_name = user_name.replace(' ', '_')
        users_by_fullname[normalized_name] = user_data
    
    print(f"✅ Індекс побудовано: {len(users_by_fullname)} записів")
    
    # Застосовуємо inheritance
    print("\n🔄 Застосовуємо inheritance від team_lead...")
    updated_count = 0
    no_teamlead_count = 0
    
    for user_name, user_data in users.items():
        # Перевіряємо структуру:
        # 1. division_name - має бути завжди (не перевіряємо)
        # 2. direction_name/unit_name - один з них обов'язковий
        # 3. team_name - опціонально
        
        has_direction = bool(user_data.get('direction_name'))
        has_unit = bool(user_data.get('unit_name'))
        has_team = bool(user_data.get('team_name'))
        
        needs_inheritance = False
        
        # Якщо немає ні direction, ні unit → потрібен inheritance
        if not has_direction and not has_unit:
            needs_inheritance = True
        
        # Якщо немає team → також inheritance
        if not has_team:
            needs_inheritance = True
        
        if needs_inheritance:
            team_lead_name = user_data.get('team_lead', '').strip()
            
            if not team_lead_name:
                no_teamlead_count += 1
                continue
            
            # Шукаємо team_lead в індексі
            team_lead_data = None
            
            # Пробуємо різні варіанти імені
            search_variants = [
                team_lead_name,
                team_lead_name.replace('_', ' '),
                team_lead_name.replace(' ', '_')
            ]
            
            for variant in search_variants:
                if variant in users_by_fullname:
                    team_lead_data = users_by_fullname[variant]
                    break
            
            # Якщо не знайшли точний збіг, шукаємо часткове співпадіння
            if not team_lead_data:
                for other_name in users_by_fullname.keys():
                    if team_lead_name.lower() in other_name.lower() or \
                       other_name.lower() in team_lead_name.lower():
                        team_lead_data = users_by_fullname[other_name]
                        break
            
            if team_lead_data:
                changed = False
                
                # Якщо немає direction/unit, беремо від team_lead
                if not has_direction and not has_unit:
                    if team_lead_data.get('direction_name'):
                        user_data['direction_name'] = team_lead_data['direction_name']
                        user_data['direction_id'] = team_lead_data.get('direction_id')
                        changed = True
                    elif team_lead_data.get('unit_name'):
                        user_data['unit_name'] = team_lead_data['unit_name']
                        user_data['unit_id'] = team_lead_data.get('unit_id')
                        changed = True
                
                # Якщо немає team, беремо від team_lead
                if not has_team and team_lead_data.get('team_name'):
                    user_data['team_name'] = team_lead_data['team_name']
                    user_data['team_id'] = team_lead_data.get('team_id')
                    changed = True
                
                if changed:
                    updated_count += 1
                    print(f"   ✅ {user_name}: успадкував дані від {team_lead_name}")
            else:
                print(f"   ⚠️  {user_name}: team_lead '{team_lead_name}' не знайдено")
    
    # Оновлюємо metadata
    data['_metadata']['last_updated'] = str(datetime.now())
    
    # Зберігаємо
    print(f"\n💾 Зберігаємо зміни...")
    with open('config/user_schedules.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 100)
    print("✅ Inheritance успішно застосовано!")
    print(f"   Користувачів оновлено: {updated_count}")
    print(f"   Користувачів без team_lead: {no_teamlead_count}")
    print(f"   Всього користувачів: {len(users)}")
    print("=" * 100)

if __name__ == '__main__':
    apply_inheritance()
