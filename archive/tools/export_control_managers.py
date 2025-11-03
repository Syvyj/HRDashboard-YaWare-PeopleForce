#!/usr/bin/env python3
"""Тестовий експорт для таблиць контроль менеджерів."""
import argparse
import json
import logging
import os
import re
from datetime import date, datetime, timedelta

from tracker_alert.client.yaware_v2_api import client
from tracker_alert.client.peopleforce_api import get_peopleforce_client
from tracker_alert.domain.week_utils import get_week_days, get_week_sheet_name, get_week_range
from tracker_alert.domain.weekly_mapping import format_all_user_blocks
from tracker_alert.services.sheets import create_weekly_sheet, apply_weekly_formatting
from tracker_alert.config.settings import settings

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def export_control_manager_table(target_date: date, control_manager: int, spreadsheet_id: str):
    """
    Експортувати тижневу статистику для контроль менеджера.
    
    Args:
        target_date: Дата в тижні для експорту
        control_manager: 1 або 2
        spreadsheet_id: ID Google Sheets таблиці
    """
    
    logger.info("=" * 80)
    logger.info(f"📊 ЕКСПОРТ ДЛЯ CONTROL MANAGER {control_manager}")
    logger.info("=" * 80)
    
    # Визначаємо тиждень
    monday, friday = get_week_range(target_date)
    week_days = get_week_days(target_date, exclude_today=True)
    week_days_str = [d.isoformat() for d in week_days]
    sheet_name = get_week_sheet_name(target_date)
    
    logger.info(f"📅 Тиждень: {monday} - {friday}")
    logger.info(f"📋 Аркуш: '{sheet_name}'")
    logger.info(f"🔗 Таблиця: {spreadsheet_id}")
    
    # Завантажуємо базу користувачів
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    db_path = os.path.join(base_dir, 'config', 'user_schedules.json')
    
    with open(db_path, 'r', encoding='utf-8') as f:
        database = json.load(f)
    
    all_users = database.get('users', {})
    
    # Фільтруємо користувачів по control_manager
    filtered_users = {}
    for name, data in all_users.items():
        if data.get('control_manager') == control_manager:
            filtered_users[name] = data
    
    logger.info(f"👥 Користувачів з control_manager={control_manager}: {len(filtered_users)}")
    
    if not filtered_users:
        logger.warning(f"⚠️  Немає користувачів для control_manager={control_manager}")
        return
    
    # Отримуємо emails для PeopleForce
    user_emails = [data.get('email', '').lower() for data in filtered_users.values() if data.get('email')]
    
    # Отримуємо дані з YaWare
    logger.info(f"🔍 Отримуємо дані з YaWare API...")
    try:
        all_week_data = client.get_week_data(week_days_str)
        logger.info(f"✅ Отримано дані для {len(all_week_data)} користувачів")
    except Exception as e:
        logger.error(f"❌ Помилка API: {e}")
        raise
    
    # Фільтруємо YaWare дані - залишаємо тільки наших користувачів
    def normalize(name):
        return re.sub(r'\s+', ' ', name.lower().strip())
    
    filtered_names_normalized = {normalize(name) for name in filtered_users.keys()}
    
    week_data = {}
    for key, data in all_week_data.items():
        full_name = data.get('full_name', '')
        norm_name = normalize(full_name)
        
        # Перевіряємо пряме співпадіння або reversed
        if norm_name in filtered_names_normalized:
            week_data[key] = data
        else:
            # Спробуємо reversed
            words = full_name.split()
            if len(words) == 2:
                reversed_name = f"{words[1]} {words[0]}"
                if normalize(reversed_name) in filtered_names_normalized:
                    week_data[key] = data
    
    logger.info(f"📊 Після фільтрації: {len(week_data)} користувачів з YaWare даних")
    
    # Додаємо start_time з бази
    for key, data in week_data.items():
        full_name = data.get('full_name', '')
        
        for db_name, db_data in filtered_users.items():
            if normalize(full_name) == normalize(db_name):
                data['start_time'] = db_data.get('start_time', '')
                break
            
            # Reversed
            words = db_name.split()
            if len(words) == 2:
                reversed_name = f"{words[1]} {words[0]}"
                if normalize(full_name) == normalize(reversed_name):
                    data['start_time'] = db_data.get('start_time', '')
                    break
    
    # Додаємо користувачів з бази які відсутні в YaWare
    yaware_normalized = {normalize(data.get('full_name', '')): key for key, data in week_data.items()}
    
    added_count = 0
    for db_name, db_data in filtered_users.items():
        words = db_name.split()
        found = False
        
        if normalize(db_name) in yaware_normalized:
            found = True
        elif len(words) == 2:
            reversed_name = f"{words[1]} {words[0]}"
            if normalize(reversed_name) in yaware_normalized:
                found = True
        
        if not found:
            email = db_data.get('email', '')
            start_time = db_data.get('start_time', '')
            week_data[f"missing_{db_name}"] = {
                "full_name": db_name,
                "email": email,
                "start_time": start_time,
                "days": []
            }
            added_count += 1
    
    if added_count > 0:
        logger.info(f"➕ Додано {added_count} користувачів без YaWare даних")
    
    logger.info(f"📊 Всього користувачів для експорту: {len(week_data)}")
    
    # Отримуємо дані з PeopleForce
    logger.info("🌍 Отримуємо дані з PeopleForce...")
    try:
        pf_client = get_peopleforce_client()
        
        locations = {}
        for email in user_emails:
            location = pf_client.get_employee_location(email)
            if location:
                formatted = pf_client.format_location_display(location)
                locations[email] = formatted.replace("Location: ", "")
        
        logger.info(f"   ✅ Локації: {len(locations)}")
        
        first_day = week_days[0]
        last_day = week_days[-1]
        all_leaves = pf_client.get_leave_requests(start_date=first_day, end_date=last_day)
        
        leaves = {}
        for leave in all_leaves:
            emp_email = leave.get("employee", {}).get("email", "").lower()
            if emp_email not in user_emails:
                continue
            
            leave_start = date.fromisoformat(leave["starts_on"])
            leave_end = date.fromisoformat(leave["ends_on"])
            
            if emp_email not in leaves:
                leaves[emp_email] = {}
            
            for day in week_days:
                if leave_start <= day <= leave_end:
                    leaves[emp_email][day] = leave
        
        logger.info(f"   ✅ Відсутності: {len(leaves)} користувачів")
        
        peopleforce_data = {"locations": locations, "leaves": leaves}
        
    except Exception as e:
        logger.warning(f"⚠️  Помилка PeopleForce: {e}")
        peopleforce_data = {"locations": {}, "leaves": {}}
    
    # Форматуємо дані
    logger.info("📝 Форматуємо дані для таблиці...")
    
    rows = format_all_user_blocks(
        week_data=week_data,
        week_days=week_days,
        peopleforce_data=peopleforce_data
    )
    
    logger.info(f"✅ Сформовано {len(rows)} рядків")
    
    # Створюємо аркуш
    logger.info("📄 Створюємо аркуш в Google Sheets...")
    
    # Тимчасово підміняємо spreadsheet_id
    original_id = settings.spreadsheet_id
    settings.spreadsheet_id = spreadsheet_id
    
    try:
        create_weekly_sheet(sheet_name, rows)
        logger.info(f"✅ Аркуш '{sheet_name}' створено")
        
        # Застосовуємо форматування
        logger.info("🎨 Застосовуємо форматування...")
        apply_weekly_formatting(sheet_name, len(week_data), week_data, week_days, peopleforce_data)
        logger.info("✅ Форматування застосовано")
        
    finally:
        settings.spreadsheet_id = original_id
    
    logger.info("=" * 80)
    logger.info(f"✅ ЕКСПОРТ ЗАВЕРШЕНО ДЛЯ CONTROL MANAGER {control_manager}")
    logger.info(f"🔗 Переглянути: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")
    logger.info("=" * 80)


def main():
    """Головна функція."""
    parser = argparse.ArgumentParser(description='Експорт статистики для контроль менеджерів')
    parser.add_argument('--date', type=str, help='Дата в форматі YYYY-MM-DD (за замовчуванням - поточний тиждень)')
    parser.add_argument('--manager', type=int, choices=[1, 2], help='Номер контроль менеджера (1 або 2, або обидва якщо не вказано)')
    
    args = parser.parse_args()
    
    # Визначаємо дату
    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        target_date = date.today()
    
    # Експортуємо
    managers_to_export = [args.manager] if args.manager else [1, 2]
    
    for manager in managers_to_export:
        spreadsheet_id = settings.spreadsheet_id_control_1 if manager == 1 else settings.spreadsheet_id_control_2
        export_control_manager_table(target_date, manager, spreadsheet_id)
        
        if len(managers_to_export) > 1 and manager == 1:
            logger.info("\n")  # Відступ між експортами


if __name__ == "__main__":
    main()
