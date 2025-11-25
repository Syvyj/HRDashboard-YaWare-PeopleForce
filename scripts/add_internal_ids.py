#!/usr/bin/env python3
"""
Додавання internal_id до user_schedules.json (починаючи з 0100)
"""
import json
import sys

def main():
    json_path = '/Users/User-001/Documents/YaWare_Bot/config/user_schedules.json'
    
    print(f"Читання {json_path}...")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    schedules = data.get('users', {})
    print(f"Знайдено {len(schedules)} користувачів")
    
    # Присвоюємо internal_id починаючи з 100
    next_id = 100
    updated = 0
    
    for user_name, info in schedules.items():
        if not isinstance(info, dict):
            continue
        
        if 'internal_id' not in info:
            info['internal_id'] = next_id
            next_id += 1
            updated += 1
    
    print(f"Додано internal_id для {updated} користувачів (100-{next_id-1})")
    
    # Зберігаємо назад
    print(f"Збереження в {json_path}...")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print("✓ Готово!")
    
    # Показуємо користувачів 24/7
    seven_day_ids = {297356, 297357, 297358, 297365, 551929, 297362, 297363, 297364, 356654, 374722, 433837, 406860, 372364}
    print("\nКористувачі з графіком 24/7:")
    for user_name, info in schedules.items():
        if isinstance(info, dict):
            pf_id = info.get('peopleforce_id')
            if pf_id and int(pf_id) in seven_day_ids:
                internal_id = info.get('internal_id')
                print(f"  internal_id={internal_id:04d}, peopleforce_id={pf_id}, email={info.get('email')}, name={info.get('name')}")

if __name__ == '__main__':
    main()
