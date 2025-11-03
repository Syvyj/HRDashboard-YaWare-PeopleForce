"""
Скрипт для щоденного оновлення вчорашньої дати в тижневому звіті.

Запускається автоматично кожного ранку і додає дані за попередній робочий день 
до існуючого тижневого аркушу.

Використання:
    python3 -m tracker_alert.scripts.update_yesterday
    
Автоматизація (cron):
    # Щодня о 09:00
    0 9 * * * cd /path/to/YaWare_Bot && python3 -m tracker_alert.scripts.update_yesterday
"""
import logging
from datetime import date, timedelta
from tracker_alert.client.yaware_v2_api import YaWareV2Client
from tracker_alert.config.settings import Settings
from tracker_alert.domain.week_utils import get_week_sheet_name, get_week_range
from tracker_alert.domain.weekly_mapping import format_user_block, seconds_to_time_format
from tracker_alert.services.sheets import get_sheet_id_by_name, _service

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)

logger = logging.getLogger(__name__)


def update_yesterday_in_sheet():
    """
    Оновити дані за вчорашній день у тижневому звіті.
    """
    settings = Settings()
    client = YaWareV2Client()
    sheets_service = _service()
    
    # Визначаємо вчорашню дату
    yesterday = date.today() - timedelta(days=1)
    
    # Пропускаємо вихідні (субота=5, неділя=6)
    if yesterday.weekday() >= 5:
        logger.info(f"⏭️  {yesterday.strftime('%d.%m.%Y')} - вихідний, пропускаємо")
        return
    
    logger.info(f"📅 Оновлення даних за {yesterday.strftime('%d.%m.%Y (%A)')}")
    
    # Визначаємо назву аркушу для цього тижня
    sheet_name = get_week_sheet_name(yesterday)
    logger.info(f"   Аркуш: '{sheet_name}'")
    
    # Перевіряємо чи існує такий аркуш
    sheet_id = get_sheet_id_by_name(sheets_service, sheet_name)
    if not sheet_id:
        logger.error(f"❌ Аркуш '{sheet_name}' не знайдено!")
        logger.info(f"💡 Спочатку створіть тижневий аркуш за допомогою:")
        logger.info(f"   python3 -m tracker_alert.scripts.export_weekly {yesterday.isoformat()}")
        return
    
    logger.info(f"✅ Аркуш знайдено (ID: {sheet_id})")
    
    # Отримуємо дані за вчорашній день
    logger.info(f"🔍 Отримуємо дані з YaWare API...")
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    day_data = client.get_summary_by_day(yesterday_str)
    
    if not day_data:
        logger.warning(f"⚠️  Немає даних за {yesterday.strftime('%d.%m.%Y')}")
        return
    
    logger.info(f"✅ Отримано дані для {len(day_data)} користувачів")
    
    # Групуємо дані по user_id
    users_map = {}
    for record in day_data:
        user_id = record.get('user_id')
        if user_id not in users_map:
            # Парсимо "Name Surname, email@domain.com"
            user_parts = record.get('user', '').split(", ")
            full_name = user_parts[0] if len(user_parts) > 0 else record.get('user', '')
            email = user_parts[1] if len(user_parts) > 1 else ""
            
            users_map[user_id] = {
                'user_id': user_id,
                'full_name': full_name,
                'email': email,
                'group': record.get('group', ''),
                'days': []
            }
        
        # Додаємо дані за цей день
        users_map[user_id]['days'].append({
            'date': yesterday,
            'time_start': record.get('time_start', ''),
            'time_end': record.get('time_end', ''),
            'productive': int(record.get('productive', 0)),
            'uncategorized': int(record.get('uncategorized', 0)),
            'distracting': int(record.get('distracting', 0)),
            'total': int(record.get('total', 0))
        })
    
    logger.info(f"📊 Унікальних користувачів: {len(users_map)}")
    
    # Зчитуємо існуючий аркуш щоб знайти позиції користувачів
    logger.info(f"📖 Зчитуємо існуючий аркуш...")
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=settings.spreadsheet_id,
        range=f"'{sheet_name}'!A:J"
    ).execute()
    
    existing_rows = result.get('values', [])
    logger.info(f"✅ Зчитано {len(existing_rows)} рядків")
    
    # Визначаємо який це день тижня (0=Пн, 4=Пт)
    monday, _ = get_week_range(yesterday)
    day_offset = (yesterday - monday).days
    yesterday_formatted = yesterday.strftime("%d.%m.%Y")
    logger.info(f"📍 День тижня: {yesterday.strftime('%A')} (день #{day_offset + 1}), шукаємо дату {yesterday_formatted}")
    
    # Шукаємо рядки для оновлення
    updates = []
    updated_users = 0
    skipped_users = 0
    not_found_users = 0
    
    logger.info(f"🔍 Шукаємо рядки з датою {yesterday_formatted}...")
    found_date_rows = []
    
    # Спочатку знаходимо всі рядки з потрібною датою
    for row_idx, row in enumerate(existing_rows):
        if len(row) > 2 and row[2].strip() == yesterday_formatted:
            found_date_rows.append(row_idx)
    
    logger.info(f"✅ Знайдено {len(found_date_rows)} рядків з датою {yesterday_formatted}")
    
    if not found_date_rows:
        logger.error(f"❌ Не знайдено жодного рядка з датою {yesterday_formatted}")
        logger.info(f"💡 Можливо, аркуш створено неправильно або дата не співпадає")
        return
    
    # Тепер для кожного рядка з датою шукаємо заголовок користувача
    updates = []
    updated_users = 0
    skipped_users = 0
    not_found_users = 0
    
    for date_row_idx in found_date_rows:
        # Шукаємо заголовок користувача (рядок з ім'ям вище цього рядка)
        user_name = None
        for back_idx in range(date_row_idx - 1, max(0, date_row_idx - 10), -1):
            if len(existing_rows[back_idx]) > 0:
                candidate = existing_rows[back_idx][0].strip()
                # Заголовок користувача не починається з "Total" і не порожній
                if candidate and candidate != "Name" and not candidate.startswith("Total"):
                    user_name = candidate
                    break
        
        if not user_name:
            logger.warning(f"⚠️  Не знайдено ім'я користувача для рядка {date_row_idx + 1}")
            not_found_users += 1
            continue
        
        # Перевіряємо чи вже є дані (колонка D - Fact Start)
        existing_data_row = existing_rows[date_row_idx]
        if len(existing_data_row) > 3 and existing_data_row[3]:  # Fact Start заповнено
            logger.debug(f"   {user_name}: дані вже є")
            skipped_users += 1
            continue
        
        # Шукаємо дані цього користувача в мапі
        matched_user = None
        for user_id, user_data in users_map.items():
            if user_data['full_name'] in user_name or user_name in user_data['full_name']:
                matched_user = user_data
                break
        
        if not matched_user:
            logger.debug(f"   {user_name}: немає даних за вчора (не працював)")
            not_found_users += 1
            continue
        
        # Формуємо рядок з новими даними
        day_record = matched_user['days'][0]  # У нас тільки один день
        
        new_row = [
            "",  # A: Name (порожня, бо це не заголовок)
            "",  # B: Plan Start (порожня)
            yesterday.strftime("%d.%m.%Y"),  # C: Data (вже є, але залишаємо)
            day_record['time_start'] if day_record['time_start'] else "",  # D: Fact Start
            seconds_to_time_format(day_record['distracting']),  # E: Non Productive
            seconds_to_time_format(day_record['uncategorized']),  # F: Not Categorized
            seconds_to_time_format(day_record['productive']),  # G: Productive
            seconds_to_time_format(day_record['total']),  # H: Total
            "",  # I: Screenshots
            ""   # J: Notes
        ]
        
        # Додаємо до списку оновлень (використовуємо date_row_idx)
        cell_range = f"'{sheet_name}'!A{date_row_idx + 1}:J{date_row_idx + 1}"  # +1 бо Sheets 1-indexed
        updates.append({
            'range': cell_range,
            'values': [new_row]
        })
        
        updated_users += 1
        logger.debug(f"   ✏️  {matched_user['full_name']}: рядок {date_row_idx + 1}")
    
    if not updates:
        logger.info(f"✅ Всі дані вже актуальні")
        logger.info(f"   Оновлено: {updated_users}")
        logger.info(f"   Пропущено (вже є дані): {skipped_users}")
        logger.info(f"   Не знайдено рядків: {not_found_users}")
        return
    
    # Виконуємо пакетне оновлення
    logger.info(f"💾 Оновлюємо {updated_users} користувачів...")
    logger.info(f"   Пропущено (вже є дані): {skipped_users}")
    logger.info(f"   Не знайдено рядків: {not_found_users}")
    
    body = {
        'valueInputOption': 'USER_ENTERED',
        'data': updates
    }
    
    sheets_service.spreadsheets().values().batchUpdate(
        spreadsheetId=settings.spreadsheet_id,
        body=body
    ).execute()
    
    logger.info(f"✅ Оновлення завершено!")
    logger.info(f"📊 Статистика:")
    logger.info(f"   Оновлено: {updated_users}")
    logger.info(f"   Пропущено: {skipped_users}")
    logger.info(f"   Всього користувачів: {len(users_map)}")
    
    logger.info(f"🎉 Готово! Total автоматично перераховується формулами SUM в Google Sheets")


def time_format_to_seconds(time_str: str) -> int:
    """
    Перетворити формат ГГ:ХХ назад в секунди.
    
    Args:
        time_str: Рядок формату "8:35" або "0:05"
        
    Returns:
        Кількість секунд
        
    Examples:
        time_format_to_seconds("8:35") -> 30900
        time_format_to_seconds("0:05") -> 300
    """
    if not time_str or time_str == "":
        return 0
    
    try:
        parts = time_str.split(":")
        if len(parts) != 2:
            return 0
        
        hours = int(parts[0])
        minutes = int(parts[1])
        
        return hours * 3600 + minutes * 60
    except (ValueError, IndexError):
        return 0


def update_totals_for_users(sheets_service, settings, sheet_name, existing_rows):
    """
    Оновити ВСІ рядки Total в аркуші.
    Зчитує дані у форматі ГГ:ХХ з рядків вище, конвертує в секунди, сумує і повертає назад в ГГ:ХХ.
    Не потребує users_map - просто рахує всі заповнені рядки між заголовком і Total.
    """
    updates = []
    
    for row_idx, row in enumerate(existing_rows):
        if len(row) == 0:
            continue
        
        first_cell = row[0].strip()
        
        # Шукаємо рядок Total
        if first_cell == "Total":
            # Збираємо дані з 5 рядків вище (це завжди дні тижня)
            data_rows_range = range(row_idx - 5, row_idx)
            
            totals_seconds = {
                'productive': 0,
                'uncategorized': 0,
                'distracting': 0,
                'total': 0
            }
            
            for data_idx in data_rows_range:
                if data_idx < 0 or data_idx >= len(existing_rows):
                    continue
                
                data_row = existing_rows[data_idx]
                if len(data_row) < 8:
                    continue
                
                # Пропускаємо порожні рядки (без дати в колонці C)
                if len(data_row) < 3 or not data_row[2]:
                    continue
                
                # Пропускаємо рядки без даних (Fact Start порожній)
                if len(data_row) < 4 or not data_row[3]:
                    continue
                
                # Збираємо значення (конвертуємо ГГ:ХХ -> секунди)
                try:
                    totals_seconds['distracting'] += time_format_to_seconds(data_row[4]) if len(data_row) > 4 and data_row[4] else 0  # E
                    totals_seconds['uncategorized'] += time_format_to_seconds(data_row[5]) if len(data_row) > 5 and data_row[5] else 0  # F
                    totals_seconds['productive'] += time_format_to_seconds(data_row[6]) if len(data_row) > 6 and data_row[6] else 0  # G
                    totals_seconds['total'] += time_format_to_seconds(data_row[7]) if len(data_row) > 7 and data_row[7] else 0  # H
                except (ValueError, IndexError) as e:
                    logger.debug(f"Помилка парсингу рядка {data_idx + 1}: {e}")
                    continue
            
            # Формуємо новий рядок Total (секунди -> ГГ:ХХ)
            new_total_row = [
                "Total",  # A
                "",  # B
                "",  # C
                "",  # D
                seconds_to_time_format(totals_seconds['distracting']),  # E
                seconds_to_time_format(totals_seconds['uncategorized']),  # F
                seconds_to_time_format(totals_seconds['productive']),  # G
                seconds_to_time_format(totals_seconds['total']),  # H
                "",  # I
                ""   # J
            ]
            
            cell_range = f"'{sheet_name}'!A{row_idx + 1}:J{row_idx + 1}"
            updates.append({
                'range': cell_range,
                'values': [new_total_row]
            })
    
    if updates:
        body = {
            'valueInputOption': 'USER_ENTERED',
            'data': updates
        }
        
        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=settings.spreadsheet_id,
            body=body
        ).execute()
        
        logger.info(f"✅ Оновлено {len(updates)} рядків Total")


if __name__ == "__main__":
    try:
        update_yesterday_in_sheet()
    except Exception as e:
        logger.error(f"❌ Помилка: {e}", exc_info=True)
        raise
