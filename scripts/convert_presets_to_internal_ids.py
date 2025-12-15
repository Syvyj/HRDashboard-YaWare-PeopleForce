#!/usr/bin/env python3
"""
Convert employee presets from email/user_id keys to internal_user_id
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard_app import create_app, db
from dashboard_app.models import EmployeePreset, AttendanceRecord

def convert_presets():
    app = create_app()
    with app.app_context():
        presets = EmployeePreset.query.all()
        print(f"Found {len(presets)} presets")
        
        for preset in presets:
            if not preset.employee_keys:
                continue
            
            print(f"\n🔄 Converting preset: {preset.name}")
            print(f"   Old keys: {preset.employee_keys}")
            
            new_keys = []
            for key in preset.employee_keys:
                # Try to find user by email or user_id
                key_lower = str(key).lower().strip()
                
                # First try email
                record = AttendanceRecord.query.filter(
                    db.func.lower(AttendanceRecord.user_email) == key_lower
                ).first()
                
                # If not found, try user_id (from YaWare)
                if not record:
                    try:
                        user_id = int(key)
                        record = AttendanceRecord.query.filter(
                            AttendanceRecord.user_id == user_id
                        ).first()
                    except ValueError:
                        pass
                
                if record and record.internal_user_id:
                    new_keys.append(record.internal_user_id)
                    print(f"   ✅ {key} -> {record.internal_user_id} ({record.user_name})")
                else:
                    print(f"   ⚠️  {key} - not found or no internal_user_id")
            
            if new_keys:
                preset.employee_keys = new_keys
                print(f"   New keys: {new_keys}")
            else:
                print(f"   ⚠️  No valid keys found, skipping")
        
        db.session.commit()
        print(f"\n✅ Converted {len(presets)} presets")

if __name__ == '__main__':
    convert_presets()
