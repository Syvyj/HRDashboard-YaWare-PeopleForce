#!/usr/bin/env python3
"""
Migration script to add record_type column to attendance_records table
"""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard_app import create_app, db
from sqlalchemy import text

def add_record_type_column():
    """Add record_type column to attendance_records table"""
    app = create_app()
    
    with app.app_context():
        try:
            # Check if column exists
            result = db.session.execute(text(
                "SELECT COUNT(*) FROM pragma_table_info('attendance_records') WHERE name='record_type'"
            )).scalar()
            
            if result > 0:
                print("✓ Колонка record_type вже існує")
                return
            
            # Add column
            print("Додаємо колонку record_type...")
            db.session.execute(text(
                "ALTER TABLE attendance_records ADD COLUMN record_type VARCHAR(16) DEFAULT 'daily'"
            ))
            
            # Create index
            print("Створюємо індекс...")
            db.session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_record_type ON attendance_records(record_type)"
            ))
            
            db.session.commit()
            print("✓ Колонка record_type успішно додана")
            
            # Show stats
            total = db.session.execute(text(
                "SELECT COUNT(*) FROM attendance_records"
            )).scalar()
            
            print(f"\nВсього записів: {total}")
            print("Всі записи отримали record_type='daily' за замовчуванням")
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ Помилка: {e}")
            raise

if __name__ == '__main__':
    add_record_type_column()
