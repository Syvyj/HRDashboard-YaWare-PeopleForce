#!/usr/bin/env python3
"""
Створення таблиці employees та додавання поля internal_user_id до attendance_records
"""
from dashboard_app import create_app, db
from dashboard_app.models import Employee, AttendanceRecord

def main():
    app = create_app()
    
    with app.app_context():
        print("Створення таблиць...")
        
        # Створюємо таблицю employees
        db.create_all()
        print("✓ Таблиця employees створена")
        
        # Перевіряємо чи існує стовпець internal_user_id
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('attendance_records')]
        
        if 'internal_user_id' not in columns:
            print("Додавання стовпця internal_user_id до attendance_records...")
            with db.engine.connect() as conn:
                conn.execute(db.text('ALTER TABLE attendance_records ADD COLUMN internal_user_id INTEGER'))
                conn.execute(db.text('CREATE INDEX ix_attendance_records_internal_user_id ON attendance_records (internal_user_id)'))
                conn.commit()
            print("✓ Стовпець internal_user_id додано")
        else:
            print("✓ Стовпець internal_user_id вже існує")
        
        print("\nГотово! Тепер запустіть update_attendance.py щоб заповнити Employee записи.")

if __name__ == '__main__':
    main()
