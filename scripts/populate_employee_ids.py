#!/usr/bin/env python3
"""
Заповнення internal_user_id для існуючих записів attendance_records
"""
import sys
sys.path.insert(0, '/Users/User-001/Documents/YaWare_Bot')

from dashboard_app import create_app, db
from dashboard_app.models import AttendanceRecord, Employee
from tracker_alert.domain.schedules import load_user_schedules

def main():
    app = create_app()
    
    with app.app_context():
        print("Завантаження schedules...")
        schedules = load_user_schedules()
        
        # Створюємо мапу email -> peopleforce_id
        email_to_pf = {}
        for user_name, info in schedules.items():
            if isinstance(info, dict):
                email = info.get('email')
                pf_id = info.get('peopleforce_id')
                if email and pf_id:
                    email_to_pf[email.lower()] = int(pf_id)
        
        print(f"Знайдено {len(email_to_pf)} користувачів з peopleforce_id")
        
        # Отримуємо всі унікальні email з attendance_records
        records = db.session.query(
            AttendanceRecord.user_email,
            AttendanceRecord.user_name,
            AttendanceRecord.user_id
        ).distinct().all()
        
        print(f"\nСтворення Employee записів для {len(records)} унікальних користувачів...")
        
        employee_map = {}  # email -> Employee
        created = 0
        
        for user_email, user_name, user_id in records:
            if not user_email:
                continue
            
            email_lower = user_email.lower()
            
            # Перевіряємо чи вже є такий Employee
            employee = Employee.query.filter_by(email=email_lower).first()
            
            if not employee:
                # Знаходимо наступний вільний ID
                max_id = db.session.query(db.func.max(Employee.internal_id)).scalar() or 99
                next_id = max(max_id + 1, 100)
                
                peopleforce_id = email_to_pf.get(email_lower)
                
                employee = Employee(
                    internal_id=next_id,
                    email=email_lower,
                    name=user_name,
                    peopleforce_id=peopleforce_id,
                    yaware_user_id=user_id
                )
                db.session.add(employee)
                created += 1
                
                if created % 10 == 0:
                    print(f"  Створено {created} Employee записів...")
            
            employee_map[email_lower] = employee
        
        db.session.commit()
        print(f"✓ Створено {created} нових Employee записів")
        
        # Тепер оновлюємо internal_user_id в attendance_records
        print("\nОновлення internal_user_id в attendance_records...")
        
        updated = 0
        batch_size = 1000
        
        # Обробляємо батчами
        total = AttendanceRecord.query.filter(AttendanceRecord.internal_user_id.is_(None)).count()
        print(f"Потрібно оновити {total} записів...")
        
        while True:
            records_to_update = AttendanceRecord.query.filter(
                AttendanceRecord.internal_user_id.is_(None)
            ).limit(batch_size).all()
            
            if not records_to_update:
                break
            
            for record in records_to_update:
                if record.user_email:
                    email_lower = record.user_email.lower()
                    employee = employee_map.get(email_lower)
                    if employee:
                        record.internal_user_id = employee.internal_id
                        updated += 1
            
            db.session.commit()
            print(f"  Оновлено {updated}/{total} записів...")
        
        print(f"\n✓ Готово! Оновлено {updated} записів")
        
        # Показуємо статистику
        print("\nСтатистика Employee:")
        total_employees = Employee.query.count()
        with_pf = Employee.query.filter(Employee.peopleforce_id.isnot(None)).count()
        print(f"  Всього Employee: {total_employees}")
        print(f"  З peopleforce_id: {with_pf}")
        
        # Показуємо користувачів 24/7
        seven_day_ids = {297356, 297357, 297358, 297365, 551929, 297362, 297363, 297364, 356654, 374722, 433837, 406860, 372364}
        seven_day_employees = Employee.query.filter(Employee.peopleforce_id.in_(seven_day_ids)).all()
        print(f"\nКористувачі 24/7 ({len(seven_day_employees)}):")
        for emp in seven_day_employees:
            print(f"  ID {emp.internal_id}: {emp.name} (PF: {emp.peopleforce_id})")

if __name__ == '__main__':
    main()
