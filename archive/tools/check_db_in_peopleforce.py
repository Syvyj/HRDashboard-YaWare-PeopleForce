#!/usr/bin/env python3
"""
Перевірка: чи всі користувачі з нашої бази є в PeopleForce
"""

import json
import sys
from pathlib import Path

# Додаємо шлях до модулів проекту
sys.path.insert(0, str(Path(__file__).parent))

from tracker_alert.client.peopleforce_api import PeopleForceClient

def load_database():
    """Завантажує базу user_schedules.json"""
    db_path = Path("config/user_schedules.json")
    with open(db_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['users']

def main():
    print("="*80)
    print("ПЕРЕВІРКА: ЧИ ВСІ КОРИСТУВАЧІ З БАЗИ Є В PEOPLEFORCE")
    print("="*80)
    print()
    
    # Завантажуємо базу
    print("📚 Завантажуємо базу user_schedules.json...")
    db_users = load_database()
    print(f"   Знайдено {len(db_users)} користувачів")
    print()
    
    # Отримуємо дані з PeopleForce
    print("🌍 Отримуємо дані з PeopleForce...")
    pf_client = PeopleForceClient()
    pf_employees = pf_client.get_employees()
    print(f"   Знайдено {len(pf_employees)} співробітників")
    print()
    
    # Створюємо мапу PeopleForce по email (нормалізований)
    pf_by_email = {}
    for emp in pf_employees:
        email = emp.get('email', '').strip().lower()
        if email:
            pf_by_email[email] = {
                'first_name': emp.get('first_name', ''),
                'last_name': emp.get('last_name', ''),
                'full_name': f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip(),
                'status': emp.get('status', ''),
                'position': emp.get('position', ''),
            }
    
    # Перевіряємо кожного користувача з бази
    print("="*80)
    print("АНАЛІЗ:")
    print("="*80)
    print()
    
    found_in_pf = []
    not_found_in_pf = []
    alternative_email_found = []
    
    for name, user_data in db_users.items():
        email = user_data.get('email', '').strip().lower()
        
        if not email:
            print(f"⚠️  {name} - немає email в базі!")
            continue
        
        # Перевіряємо основний email
        if email in pf_by_email:
            found_in_pf.append((name, email, pf_by_email[email]))
        else:
            # Шукаємо альтернативний email (@evrius.com <-> @evadav.com)
            if '@evrius.com' in email:
                alt_email = email.replace('@evrius.com', '@evadav.com')
            elif '@evadav.com' in email:
                alt_email = email.replace('@evadav.com', '@evrius.com')
            else:
                alt_email = None
            
            if alt_email and alt_email in pf_by_email:
                alternative_email_found.append((name, email, alt_email, pf_by_email[alt_email]))
            else:
                not_found_in_pf.append((name, email, user_data))
    
    # Виводимо результати
    print(f"✅ Знайдено в PeopleForce з основним email: {len(found_in_pf)} осіб")
    print()
    
    if alternative_email_found:
        print(f"💡 Знайдено з альтернативним email: {len(alternative_email_found)} осіб")
        print("   (потрібно синхронізувати email)")
        print()
        for name, db_email, pf_email, pf_info in alternative_email_found:
            print(f"   {name}")
            print(f"      В базі:       {db_email}")
            print(f"      В PeopleForce: {pf_email}")
            print(f"      PF ім'я:      {pf_info['full_name']}")
            print(f"      Позиція:      {pf_info['position']}")
            print()
    
    if not_found_in_pf:
        print(f"❌ НЕ знайдено в PeopleForce: {len(not_found_in_pf)} осіб")
        print()
        for name, email, user_data in not_found_in_pf:
            print(f"   {name}")
            print(f"      Email: {email}")
            print(f"      Start time: {user_data.get('start_time')}")
            print(f"      Location: {user_data.get('location')}")
            if 'yaware_group' in user_data:
                print(f"      YaWare Group: {user_data.get('yaware_group')}")
            if 'control_manager' in user_data:
                print(f"      Control Manager: {user_data.get('control_manager')}")
            if 'department' in user_data:
                print(f"      Department: {user_data.get('department')}")
            print()
    
    # Підсумок
    print("="*80)
    print("ПІДСУМОК:")
    print("="*80)
    total_in_db = len(db_users)
    total_found = len(found_in_pf) + len(alternative_email_found)
    
    print(f"Всього в базі:           {total_in_db}")
    print(f"Знайдено в PF:           {total_found} ({total_found*100//total_in_db}%)")
    print(f"  - з основним email:    {len(found_in_pf)}")
    print(f"  - з альтернативним:    {len(alternative_email_found)}")
    print(f"НЕ знайдено в PF:        {len(not_found_in_pf)}")
    print()
    
    if len(not_found_in_pf) > 0:
        print("🔍 РЕКОМЕНДАЦІЇ для користувачів, яких немає в PeopleForce:")
        print("   1. Перевірте чи вони ще працюють в компанії")
        print("   2. Можливо це контрактори/фрілансери без PeopleForce акаунту")
        print("   3. Можливо помилка в email адресі")
        print()
    
    if len(alternative_email_found) > 0:
        print("🔧 РЕКОМЕНДАЦІЇ для альтернативних email:")
        print("   Синхронізувати email в базі з PeopleForce для уніфікації")
        print()
    
    print("="*80)

if __name__ == "__main__":
    main()
