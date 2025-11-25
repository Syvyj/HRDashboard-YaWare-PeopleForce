#!/usr/bin/env python3
"""
Оновлення internal_user_id для існуючих записів в attendance_records
"""
import sys
sys.path.insert(0, '/Users/User-001/Documents/YaWare_Bot')

from dashboard_app import create_app, db
from dashboard_app.models import AttendanceRecord
from dashboard_app.user_data import load_user_schedules

def main():
    app = create_app()
    app.config['TESTING'] = True
    
    with app.app_context():
        print("Завантаження schedules...")
        schedules = load_user_schedules()
        
        # Створюємо мапу email -> internal_id
        email_to_internal = {}
        for user_name, info in schedules.items():
            if isinstance(info, dict):
                email = info.get('email')
                internal_id = info.get('internal_id')
                if email and internal_id:
                    email_to_internal[email.lower()] = int(internal_id)
        
        print(f"Знайдено {len(email_to_internal)} користувачів з internal_id")
        
        # Оновлюємо internal_user_id в attendance_records
        print("\nОновлення internal_user_id в attendance_records...")
        
        total = AttendanceRecord.query.filter(AttendanceRecord.internal_user_id.is_(None)).count()
        print(f"Потрібно оновити {total} записів...")
        
        updated = 0
        batch_size = 1000
        
        while True:
            records_to_update = AttendanceRecord.query.filter(
                AttendanceRecord.internal_user_id.is_(None)
            ).limit(batch_size).all()
            
            if not records_to_update:
                break
            
            for record in records_to_update:
                if record.user_email:
                    email_lower = record.user_email.lower()
                    internal_id = email_to_internal.get(email_lower)
                    if internal_id:
                        record.internal_user_id = internal_id
                        updated += 1
            
            db.session.commit()
            print(f"  Оновлено {updated}/{total} записів...")
        
        print(f"\n✓ Готово! Оновлено {updated} записів")

if __name__ == '__main__':
    main()
