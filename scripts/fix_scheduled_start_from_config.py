#!/usr/bin/env python3
"""
Скрипт для виправлення scheduled_start в БД на основі user_schedules.json.
Виправляє записи де scheduled_start='00:00' або відрізняється від конфігу.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dashboard_app.extensions import db
from dashboard_app.models import AttendanceRecord
from dashboard_app.user_data import get_user_schedule
from web_dashboard import create_app


def fix_scheduled_start():
    app = create_app()
    with app.app_context():
        # Знайти всі записи з scheduled_start='00:00' або пусті
        records = AttendanceRecord.query.filter(
            (AttendanceRecord.scheduled_start == '00:00') | 
            (AttendanceRecord.scheduled_start == '') |
            (AttendanceRecord.scheduled_start.is_(None))
        ).all()
        
        print(f"Знайдено {len(records)} записів з невалідним scheduled_start")
        
        updated = 0
        skipped = 0
        
        for record in records:
            # Пропускаємо записи з ручним перевизначенням
            if getattr(record, 'manual_scheduled_start', False):
                skipped += 1
                continue
            
            # Шукаємо графік користувача
            schedule = get_user_schedule(record.user_name)
            if not schedule and record.user_email:
                schedule = get_user_schedule(record.user_email)
            if not schedule and record.user_id:
                schedule = get_user_schedule(record.user_id)
            
            if schedule and schedule.get('start_time'):
                old_value = record.scheduled_start
                record.scheduled_start = schedule['start_time']
                updated += 1
                print(f"  {record.user_name} ({record.record_date}): '{old_value}' -> '{schedule['start_time']}'")
        
        if updated > 0:
            db.session.commit()
            print(f"\n✅ Оновлено {updated} записів")
        else:
            print(f"\n✅ Нічого не потрібно оновлювати")
        
        if skipped > 0:
            print(f"⚠️  Пропущено {skipped} записів з ручним перевизначенням")


if __name__ == '__main__':
    fix_scheduled_start()
