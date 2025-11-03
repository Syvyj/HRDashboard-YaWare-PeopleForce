#!/usr/bin/env python3
"""Звірка користувачів між базою, YaWare та PeopleForce."""
import json
import re
from pathlib import Path
from tracker_alert.client.yaware_v2_api import client
from tracker_alert.client.peopleforce_api import get_peopleforce_client
from datetime import date


def normalize(name):
    """Нормалізація імені."""
    return re.sub(r'\s+', ' ', name.lower().strip())


def main():
    print("=" * 80)
    print("ЗВІРКА КОРИСТУВАЧІВ МІЖ БАЗОЮ, YAWARE ТА PEOPLEFORCE")
    print("=" * 80)
    
    # 1. Завантажуємо нашу базу
    config_dir = Path(__file__).resolve().parent / 'config'
    with open(config_dir / 'user_schedules.json', 'r', encoding='utf-8') as f:
        database = json.load(f)
    
    our_users = database.get('users', {})
    print(f"\n📚 Наша база: {len(our_users)} користувачів")
    
    # Створюємо мапи
    our_by_email = {data.get('email', '').lower(): name for name, data in our_users.items() if data.get('email')}
    our_by_name = {normalize(name): name for name in our_users.keys()}
    
    print(f"   - З email: {len(our_by_email)}")
    print(f"   - Без email: {len(our_users) - len(our_by_email)}")
    
    # 2. Отримуємо з YaWare (за вчора)
    print(f"\n🔍 Отримуємо дані з YaWare...")
    yesterday = date.today().replace(day=date.today().day - 1)
    try:
        yaware_data = client.get_week_data([yesterday.isoformat()])
        print(f"✅ YaWare: {len(yaware_data)} користувачів")
        
        yaware_users = {}
        for key, data in yaware_data.items():
            full_name = data.get('full_name', '')
            email = data.get('email', '').lower()
            yaware_users[email] = full_name
        
    except Exception as e:
        print(f"❌ Помилка YaWare API: {e}")
        yaware_users = {}
    
    # 3. Отримуємо з PeopleForce
    print(f"\n🌍 Отримуємо дані з PeopleForce...")
    try:
        pf_client = get_peopleforce_client()
        pf_employees = pf_client.get_employees()
        print(f"✅ PeopleForce: {len(pf_employees)} співробітників")
        
        pf_users = {}
        for emp in pf_employees:
            email = emp.get('email', '').lower()
            name = emp.get('name', '')
            pf_users[email] = name
        
    except Exception as e:
        print(f"❌ Помилка PeopleForce API: {e}")
        pf_users = {}
    
    # Аналіз
    print("\n" + "=" * 80)
    print("АНАЛІЗ РОЗБІЖНОСТЕЙ")
    print("=" * 80)
    
    # Хто є в нашій базі, але НЕ в YaWare
    print(f"\n❌ В БАЗІ, АЛЕ НЕ В YAWARE:")
    missing_in_yaware = []
    for email, name in our_by_email.items():
        if email not in yaware_users:
            missing_in_yaware.append((name, email))
    
    if missing_in_yaware:
        for name, email in sorted(missing_in_yaware):
            print(f"   {name:40} ({email})")
    else:
        print("   ✅ Всі є в YaWare")
    print(f"   Всього: {len(missing_in_yaware)}")
    
    # Хто є в YaWare, але НЕ в нашій базі
    print(f"\n➕ В YAWARE, АЛЕ НЕ В БАЗІ:")
    missing_in_our_base = []
    for email, name in yaware_users.items():
        if email and email not in our_by_email:
            # Перевіримо по імені
            norm_name = normalize(name)
            if norm_name not in our_by_name:
                # Перевіримо reversed
                words = name.split()
                if len(words) == 2:
                    reversed_name = f"{words[1]} {words[0]}"
                    if normalize(reversed_name) not in our_by_name:
                        missing_in_our_base.append((name, email))
                else:
                    missing_in_our_base.append((name, email))
    
    if missing_in_our_base:
        for name, email in sorted(missing_in_our_base):
            print(f"   {name:40} ({email})")
    else:
        print("   ✅ Всіх є в базі")
    print(f"   Всього: {len(missing_in_our_base)}")
    
    # Хто є в нашій базі, але НЕ в PeopleForce
    print(f"\n❌ В БАЗІ, АЛЕ НЕ В PEOPLEFORCE:")
    missing_in_pf = []
    for email, name in our_by_email.items():
        if email not in pf_users:
            missing_in_pf.append((name, email))
    
    if missing_in_pf:
        for name, email in sorted(missing_in_pf):
            print(f"   {name:40} ({email})")
    else:
        print("   ✅ Всі є в PeopleForce")
    print(f"   Всього: {len(missing_in_pf)}")
    
    # Хто є в PeopleForce, але НЕ в нашій базі
    print(f"\n➕ В PEOPLEFORCE, АЛЕ НЕ В БАЗІ:")
    missing_in_our_base_pf = []
    for email, name in pf_users.items():
        if email and email not in our_by_email:
            norm_name = normalize(name)
            if norm_name not in our_by_name:
                missing_in_our_base_pf.append((name, email))
    
    if missing_in_our_base_pf:
        for name, email in sorted(missing_in_our_base_pf)[:20]:  # Перші 20
            print(f"   {name:40} ({email})")
        if len(missing_in_our_base_pf) > 20:
            print(f"   ... та ще {len(missing_in_our_base_pf) - 20}")
    else:
        print("   ✅ Всіх є в базі")
    print(f"   Всього: {len(missing_in_our_base_pf)}")
    
    # Підсумок
    print("\n" + "=" * 80)
    print("ПІДСУМОК")
    print("=" * 80)
    print(f"Наша база:        {len(our_users)} користувачів")
    print(f"YaWare:           {len(yaware_users)} користувачів")
    print(f"PeopleForce:      {len(pf_users)} співробітників")
    print(f"\nНе в YaWare:      {len(missing_in_yaware)}")
    print(f"Нових в YaWare:   {len(missing_in_our_base)}")
    print(f"Не в PeopleForce: {len(missing_in_pf)}")
    print(f"Нових в PF:       {len(missing_in_our_base_pf)}")
    print("=" * 80)


if __name__ == "__main__":
    main()
