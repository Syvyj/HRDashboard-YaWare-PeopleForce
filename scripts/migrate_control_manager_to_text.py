#!/usr/bin/env python3
"""
Міграція колонки control_manager з Integer на Text
Конвертує існуючі значення: 1 -> "1", NULL -> NULL
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dashboard_app import create_app, db
from dashboard_app.models import AttendanceRecord
from sqlalchemy import text

def migrate_control_manager():
    app = create_app()
    
    with app.app_context():
        print("Міграція control_manager з Integer на Text...")
        
        try:
            # SQLite не підтримує ALTER COLUMN TYPE, тому треба:
            # 1. Видалити індекс
            # 2. Створити тимчасову колонку
            # 3. Скопіювати дані конвертуючи в строку
            # 4. Видалити стару колонку
            # 5. Перейменувати нову
            # 6. Відтворити індекс
            
            print("Крок 1: Видалення старих індексів...")
            try:
                db.session.execute(text('DROP INDEX IF EXISTS ix_attendance_records_control_manager'))
                db.session.execute(text('DROP INDEX IF EXISTS idx_control_manager_date'))
                db.session.commit()
            except Exception as e:
                print(f"   Попередження: {e}")
            
            print("Крок 2: Створення тимчасової колонки...")
            db.session.execute(text('ALTER TABLE attendance_records ADD COLUMN control_manager_temp TEXT'))
            db.session.commit()
            
            print("Крок 3: Копіювання даних (Integer -> Text)...")
            # Конвертуємо Integer в Text: 1 -> "1", NULL -> NULL
            db.session.execute(text('''
                UPDATE attendance_records 
                SET control_manager_temp = CAST(control_manager AS TEXT)
                WHERE control_manager IS NOT NULL
            '''))
            db.session.commit()
            
            print("Крок 4: Видалення старої колонки...")
            db.session.execute(text('ALTER TABLE attendance_records DROP COLUMN control_manager'))
            db.session.commit()
            
            print("Крок 5: Перейменування нової колонки...")
            db.session.execute(text('ALTER TABLE attendance_records RENAME COLUMN control_manager_temp TO control_manager'))
            db.session.commit()
            
            print("Крок 6: Відтворення індексів...")
            db.session.execute(text('CREATE INDEX ix_attendance_records_control_manager ON attendance_records (control_manager)'))
            db.session.execute(text('CREATE INDEX idx_control_manager_date ON attendance_records (control_manager, record_date)'))
            db.session.commit()
            
            # Перевіряємо результат
            result = db.session.execute(text('SELECT COUNT(*) as cnt, COUNT(control_manager) as with_cm FROM attendance_records')).fetchone()
            print(f"✅ Міграція завершена!")
            print(f"   Всього записів: {result.cnt}")
            print(f"   З control_manager: {result.with_cm}")
            
        except Exception as e:
            print(f"❌ Помилка міграції: {e}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    migrate_control_manager()
