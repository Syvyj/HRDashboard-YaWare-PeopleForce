#!/usr/bin/env python3
"""
Migration script to add half_day_amount column to attendance_records table.
This column stores the leave amount: 0.5 for half-day leave, 1.0 for full day, None if not a leave.
"""
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dashboard_app import create_app, db

def add_column():
    """Add half_day_amount column to attendance_records table"""
    app = create_app()
    
    with app.app_context():
        try:
            # Check if column already exists
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('attendance_records')]
            
            if 'half_day_amount' in columns:
                print("[INFO] Column 'half_day_amount' already exists")
                return
            
            # Add the column
            from sqlalchemy import text
            with db.engine.connect() as conn:
                conn.execute(text('''
                    ALTER TABLE attendance_records 
                    ADD COLUMN half_day_amount FLOAT DEFAULT NULL
                '''))
                conn.commit()
            
            print("[SUCCESS] Added 'half_day_amount' column to attendance_records table")
            
        except Exception as e:
            print(f"[ERROR] Failed to add column: {e}")
            raise

if __name__ == '__main__':
    add_column()
