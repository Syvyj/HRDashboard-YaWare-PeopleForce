#!/usr/bin/env python3
"""
Скрипт для заповнення відсутніх internal_user_id в attendance_records
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dashboard_app.extensions import db
from dashboard_app.models import AttendanceRecord
from web_dashboard import create_app


def fix_missing_internal_ids():
    app = create_app()
    with app.app_context():
        # Знайти записи без internal_user_id
        records_without_id = AttendanceRecord.query.filter(
            AttendanceRecord.internal_user_id.is_(None),
            AttendanceRecord.record_type == 'daily'
        ).all()
        
        print(f"Знайдено {len(records_without_id)} записів без internal_user_id")
        
        # Для кожного користувача знайдемо його internal_user_id з інших записів
        user_id_map = {}
        updated = 0
        
        for record in records_without_id:
            email = record.user_email
            if not email:
                continue
            
            # Якщо ще не знаємо internal_user_id для цього email - шукаємо
            if email not in user_id_map:
                existing = AttendanceRecord.query.filter(
                    AttendanceRecord.user_email == email,
                    AttendanceRecord.internal_user_id.isnot(None)
                ).first()
                
                if existing and existing.internal_user_id:
                    user_id_map[email] = existing.internal_user_id
                else:
                    print(f"  ⚠️  Не знайдено internal_user_id для {email}")
                    continue
            
            # Встановлюємо internal_user_id
            internal_id = user_id_map[email]
            record.internal_user_id = internal_id
            updated += 1
            print(f"  {record.user_name} ({record.record_date}): internal_user_id -> {internal_id}")
        
        if updated > 0:
            db.session.commit()
            print(f"\n✅ Оновлено {updated} записів")
        else:
            print(f"\n✅ Нічого не потрібно оновлювати")


if __name__ == '__main__':
    fix_missing_internal_ids()
