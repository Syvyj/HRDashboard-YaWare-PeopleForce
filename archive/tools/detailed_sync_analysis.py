#!/usr/bin/env python3
"""
Детальний аналіз синхронізації:
1. Беремо 12 людей які є в базі, але немає в PeopleForce
2. Перевіряємо чи є вони в YaWare (за весь час)
3. Виводимо рекомендації
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Додаємо шлях до модулів проекту
sys.path.insert(0, str(Path(__file__).parent))

from tracker_alert.client.yaware_v2_api import YaWareV2Client
from tracker_alert.client.peopleforce_api import PeopleForceClient
from tracker_alert.config.settings import settings

def normalize(name):
    """Нормалізує ім'я для порівняння"""
    if not name:
        return ""
    return name.lower().strip().replace("  ", " ")

def load_database():
    """Завантажує базу user_schedules.json"""
    db_path = Path("config/user_schedules.json")
    with open(db_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['users']

def get_yaware_all_users(client):
    """Отримує всіх користувачів YaWare за останні 30 днів"""
    print("🔍 Перевіряємо YaWare за останні 30 днів...")
    
    all_users = {}
    today = datetime.now()
    
    for i in range(30):
        check_date = today - timedelta(days=i)
        date_str = check_date.strftime('%Y-%m-%d')
        
        try:
            week_data = client.get_week_data([date_str])
            if week_data and 'users' in week_data:
                for user in week_data['users']:
                    name = user.get('name', '').strip()
                    email = user.get('email', '').strip()
                    if name and email:
                        normalized = normalize(name)
                        if normalized not in all_users:
                            all_users[normalized] = {
                                'name': name,
                                'email': email,
                                'last_seen': date_str,
                                'user_id': user.get('id')
                            }
        except Exception as e:
            # Пропускаємо помилки для окремих днів
            continue
    
    print(f"   Знайдено {len(all_users)} унікальних користувачів")
    return all_users

def main():
    print("="*80)
    print("ДЕТАЛЬНИЙ АНАЛІЗ: 12 КОРИСТУВАЧІВ З БАЗИ, ЯКИ НЕ В PEOPLEFORCE")
    print("="*80)
    print()
    
    # Список проблемних користувачів
    missing_in_pf = [
        ("Anton Popovych", "a.popovych@evrius.com"),
        ("Bakumova Kseniya", "k.bakunova@evadav.com"),
        ("Chernov Leonid", "eo_sup@evadav.com"),
        ("Goloven Dmytro", "d.goloven@evrius.com"),
        ("Kryvytska Olena", "o.kryvytska@evrius.com"),
        ("Murygin Nikolai", "nikolai_adv@evadav.com"),
        ("Roshchyn Hlib", "h.roshchyn@evrius.com"),
        ("Sidielnikova Diana", "d.sidielnikova@evrius.com"),
        ("Usenko Roman", "r.usenko@evrius.com"),
        ("Varnavska Yuliia", "y.varnavska@evrius.com"),
        ("Yukhno Leonid", "cmo@evadav.com"),
        ("Zaprudskiy Sergey", "s.zaprudskyi@evrius.com")
    ]
    
    # Завантажуємо базу
    db_users = load_database()
    
    # Отримуємо дані з YaWare
    yaware_client = YaWareV2Client()
    yaware_users = get_yaware_all_users(yaware_client)
    
    # Отримуємо дані з PeopleForce
    print("\n🌍 Перевіряємо PeopleForce...")
    pf_client = PeopleForceClient()
    pf_employees = pf_client.get_employees()
    
    # Створюємо мапу PeopleForce по email
    pf_by_email = {}
    for emp in pf_employees:
        email = emp.get('email', '').strip().lower()
        if email:
            pf_by_email[email] = emp
    
    print(f"   Знайдено {len(pf_employees)} співробітників в PeopleForce")
    print()
    
    # Аналізуємо кожного користувача
    print("="*80)
    print("АНАЛІЗ КОЖНОГО КОРИСТУВАЧА:")
    print("="*80)
    print()
    
    in_yaware = []
    not_in_yaware = []
    alternate_email_in_pf = []
    
    for name, email in missing_in_pf:
        normalized = normalize(name)
        
        print(f"👤 {name}")
        print(f"   Email в базі: {email}")
        
        # Перевіряємо чи є в базі
        if name in db_users:
            db_info = db_users[name]
            print(f"   ✅ Є в нашій базі")
            print(f"      Start time: {db_info.get('start_time')}")
            print(f"      Location: {db_info.get('location')}")
            if 'yaware_group' in db_info:
                print(f"      YaWare Group: {db_info.get('yaware_group')}")
            if 'control_manager' in db_info:
                print(f"      Control Manager: {db_info.get('control_manager')}")
        
        # Перевіряємо YaWare
        if normalized in yaware_users:
            ya_info = yaware_users[normalized]
            print(f"   ✅ Є в YaWare (останній раз: {ya_info['last_seen']})")
            print(f"      YaWare email: {ya_info['email']}")
            in_yaware.append((name, email))
        else:
            print(f"   ❌ НЕ знайдено в YaWare за останні 30 днів")
            not_in_yaware.append((name, email))
        
        # Перевіряємо PeopleForce
        email_lower = email.lower()
        if email_lower in pf_by_email:
            print(f"   ✅ Знайдено в PeopleForce з цим email")
            pf_info = pf_by_email[email_lower]
            print(f"      PF Name: {pf_info.get('first_name')} {pf_info.get('last_name')}")
        else:
            print(f"   ❌ НЕ знайдено в PeopleForce з email {email}")
            
            # Шукаємо альтернативні email
            if '@evrius.com' in email:
                alt_email = email.replace('@evrius.com', '@evadav.com')
            elif '@evadav.com' in email:
                alt_email = email.replace('@evadav.com', '@evrius.com')
            else:
                alt_email = None
            
            if alt_email and alt_email.lower() in pf_by_email:
                print(f"   💡 АЛЕ знайдено альтернативний email в PeopleForce: {alt_email}")
                pf_info = pf_by_email[alt_email.lower()]
                print(f"      PF Name: {pf_info.get('first_name')} {pf_info.get('last_name')}")
                alternate_email_in_pf.append((name, email, alt_email))
        
        print()
    
    # Підсумок
    print("="*80)
    print("ПІДСУМОК ТА РЕКОМЕНДАЦІЇ:")
    print("="*80)
    print()
    
    print(f"✅ Є в YaWare (активні): {len(in_yaware)} осіб")
    if in_yaware:
        for name, email in in_yaware:
            print(f"   - {name} ({email})")
    print()
    
    print(f"❌ НЕ в YaWare за 30 днів: {len(not_in_yaware)} осіб")
    if not_in_yaware:
        print("   🔍 Рекомендація: можливо вони більше не працюють або не користуються YaWare")
        for name, email in not_in_yaware:
            print(f"   - {name} ({email})")
    print()
    
    print(f"💡 Мають альтернативний email в PeopleForce: {len(alternate_email_in_pf)} осіб")
    if alternate_email_in_pf:
        print("   🔧 Рекомендація: синхронізувати email в базі з PeopleForce")
        for name, old_email, new_email in alternate_email_in_pf:
            print(f"   - {name}: {old_email} → {new_email}")
    print()
    
    print("="*80)

if __name__ == "__main__":
    main()
