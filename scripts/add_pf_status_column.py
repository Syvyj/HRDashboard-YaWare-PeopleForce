#!/usr/bin/env python3
"""Add pf_status column to attendance_records table."""

import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def add_pf_status_column(db_path: str):
    """Add pf_status column to attendance_records table."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if column already exists
        cursor.execute("PRAGMA table_info(attendance_records)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'pf_status' in columns:
            print("Column 'pf_status' already exists")
            return
        
        # Add the column
        cursor.execute("ALTER TABLE attendance_records ADD COLUMN pf_status TEXT")
        conn.commit()
        print("Successfully added 'pf_status' column")
        
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    db_path = "instance/dashboard.db"
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        sys.exit(1)
    
    add_pf_status_column(db_path)
