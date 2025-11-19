#!/usr/bin/env python3
"""
Script to add database indexes for improved query performance.
Run this script after updating models.py with new indexes.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dashboard_app.extensions import db
from dashboard_app.models import AttendanceRecord, AdminAuditLog
from web_dashboard import app


def add_indexes():
    """Add indexes to existing tables."""
    with app.app_context():
        inspector = db.inspect(db.engine)
        
        # Get existing indexes
        attendance_indexes = {idx['name'] for idx in inspector.get_indexes('attendance_records')}
        audit_indexes = {idx['name'] for idx in inspector.get_indexes('admin_audit_log')}
        
        print("Current indexes on attendance_records:", attendance_indexes)
        print("Current indexes on admin_audit_log:", audit_indexes)
        
        # Create new indexes if they don't exist
        new_indexes = [
            ('idx_user_date', 'attendance_records', ['user_id', 'record_date']),
            ('idx_date_status', 'attendance_records', ['record_date', 'status']),
            ('idx_control_manager_date', 'attendance_records', ['control_manager', 'record_date']),
            ('idx_user_name', 'attendance_records', ['user_name']),
            ('idx_audit_user_action', 'admin_audit_log', ['user_id', 'action']),
            ('idx_audit_created', 'admin_audit_log', ['created_at']),
        ]
        
        with db.engine.connect() as conn:
            for idx_name, table_name, columns in new_indexes:
                if table_name == 'attendance_records' and idx_name in attendance_indexes:
                    print(f"✓ Index {idx_name} already exists on {table_name}")
                    continue
                if table_name == 'admin_audit_log' and idx_name in audit_indexes:
                    print(f"✓ Index {idx_name} already exists on {table_name}")
                    continue
                
                try:
                    cols = ', '.join(columns)
                    sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({cols})"
                    conn.execute(db.text(sql))
                    conn.commit()
                    print(f"✓ Created index {idx_name} on {table_name}({cols})")
                except Exception as exc:
                    print(f"✗ Failed to create index {idx_name}: {exc}")
        
        print("\n✅ Index creation complete!")
        
        # Show final state
        attendance_indexes = {idx['name'] for idx in inspector.get_indexes('attendance_records')}
        audit_indexes = {idx['name'] for idx in inspector.get_indexes('admin_audit_log')}
        print(f"\nFinal indexes on attendance_records ({len(attendance_indexes)}): {sorted(attendance_indexes)}")
        print(f"Final indexes on admin_audit_log ({len(audit_indexes)}): {sorted(audit_indexes)}")


if __name__ == '__main__':
    add_indexes()
