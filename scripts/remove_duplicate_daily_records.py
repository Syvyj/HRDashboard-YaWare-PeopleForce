#!/usr/bin/env python3
"""
Скрипт для видалення дублікатів daily записів в AttendanceRecord.
Якщо для одного користувача і дати є кілька daily записів, залишає тільки той,
де total_minutes > 0, а решту видаляє.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard_app import create_app, db
from dashboard_app.models import AttendanceRecord
from collections import defaultdict

def find_and_remove_duplicates():
    app = create_app()
    with app.app_context():
        # Шукаємо всі daily записи
        records = AttendanceRecord.query.filter(
            AttendanceRecord.record_type == 'daily'
        ).all()
        
        # Групуємо по (email, date)
        groups = defaultdict(list)
        for r in records:
            key = (r.user_email, r.internal_user_id, r.record_date)
            groups[key].append(r)
        
        # Шукаємо групи з дублікатами
        duplicates_to_delete = []
        for key, recs in groups.items():
            if len(recs) <= 1:
                continue
            
            # Сортуємо: спочатку з даними (total > 0), потім порожні
            recs_sorted = sorted(recs, key=lambda r: (r.total_minutes == 0, r.id))
            
            # Залишаємо перший (з даними), решту видаляємо
            keep = recs_sorted[0]
            to_delete = recs_sorted[1:]
            
            email, internal_id, date = key
            print(f'\n📋 {email} | {date}')
            print(f'   Залишаємо: ID={keep.id}, total={keep.total_minutes} min')
            for r in to_delete:
                print(f'   ❌ Видаляємо: ID={r.id}, total={r.total_minutes} min')
                duplicates_to_delete.append(r)
        
        if duplicates_to_delete:
            print(f'\n🗑️  Всього знайдено {len(duplicates_to_delete)} дублікатів для видалення')
            confirm = input('\nВидалити ці записи? (yes/no): ')
            if confirm.lower() == 'yes':
                for r in duplicates_to_delete:
                    db.session.delete(r)
                db.session.commit()
                print(f'\n✅ Видалено {len(duplicates_to_delete)} дублікатів')
            else:
                print('\n❌ Скасовано')
        else:
            print('\n✅ Дублікатів не знайдено')

if __name__ == '__main__':
    find_and_remove_duplicates()
