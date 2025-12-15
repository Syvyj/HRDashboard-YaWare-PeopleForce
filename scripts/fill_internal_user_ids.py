#!/usr/bin/env python3
"""
Fill missing internal_user_id in AttendanceRecord table
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard_app import create_app, db
from dashboard_app.models import AttendanceRecord
from sqlalchemy import func

def fill_internal_user_ids():
    """Fill missing internal_user_id based on user_email"""
    app = create_app()
    with app.app_context():
        # Get records without internal_user_id
        records_without_id = AttendanceRecord.query.filter(
            (AttendanceRecord.internal_user_id == None) | (AttendanceRecord.internal_user_id == 0)
        ).all()
        
        print(f"Found {len(records_without_id)} records without internal_user_id")
        
        if not records_without_id:
            print("All records have internal_user_id!")
            return
        
        # Group by email to assign same ID to same user
        email_to_id = {}
        next_id = db.session.query(func.max(AttendanceRecord.internal_user_id)).scalar() or 0
        next_id += 1
        
        updated = 0
        for record in records_without_id:
            email = record.user_email
            if not email:
                print(f"Warning: Record {record.id} has no email, skipping")
                continue
            
            # Check if we already have an ID for this email
            if email not in email_to_id:
                # Try to find existing ID for this email
                existing = AttendanceRecord.query.filter(
                    AttendanceRecord.user_email == email,
                    AttendanceRecord.internal_user_id != None,
                    AttendanceRecord.internal_user_id != 0
                ).first()
                
                if existing:
                    email_to_id[email] = existing.internal_user_id
                    print(f"Found existing ID {existing.internal_user_id} for {email}")
                else:
                    email_to_id[email] = next_id
                    print(f"Assigning new ID {next_id} to {email}")
                    next_id += 1
            
            record.internal_user_id = email_to_id[email]
            updated += 1
            
            if updated % 100 == 0:
                print(f"Updated {updated} records...")
                db.session.commit()
        
        db.session.commit()
        print(f"✅ Updated {updated} records")
        print(f"Next available ID: {next_id}")

if __name__ == '__main__':
    fill_internal_user_ids()
