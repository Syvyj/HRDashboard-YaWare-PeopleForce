#!/usr/bin/env python3
"""Експорт статистики активних користувачів YaWare в Google Sheets (v2 API)."""
from __future__ import annotations
import argparse
import logging
from datetime import date, datetime
from pathlib import Path
import sys

# Додаємо шлях до проєкту
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tracker_alert.client.yaware_v2_api import client
from tracker_alert.domain.mapping_v2 import (
    parse_summary_by_day,
    format_for_sheets_row,
    get_sheets_headers
)
from tracker_alert.services.sheets import _service
from tracker_alert.config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger("export_daily_v2")


def ensure_sheet_with_headers(service, sheet_tab: str):
    """Переконатися що вкладка існує та має заголовки."""
    spreadsheet_id = settings.spreadsheet_id
    
    # Отримуємо metadata таблиці
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
    
    # Створюємо вкладку якщо не існує
    if sheet_tab not in sheet_titles:
        body = {
            "requests": [{
                "addSheet": {
                    "properties": {"title": sheet_tab}
                }
            }]
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body=body
        ).execute()
        logger.info(f"✅ Створено вкладку '{sheet_tab}'")
    
    # Перевіряємо чи є заголовки
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_tab}!A1:J1"
        ).execute()
        
        if not result.get("values"):
            # Додаємо заголовки
            headers = [get_sheets_headers()]
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{sheet_tab}!A1",
                valueInputOption="USER_ENTERED",
                body={"values": headers}
            ).execute()
            logger.info(f"✅ Додано заголовки до '{sheet_tab}'")
    except Exception as e:
        logger.warning(f"Не вдалося перевірити заголовки: {e}")


def delete_rows_for_date(service, sheet_tab: str, target_date: date):
    """
    Видалити всі рядки з певною датою перед оновленням.
    
    Args:
        service: Google Sheets service
        sheet_tab: Назва вкладки
        target_date: Дата для видалення
    """
    date_str = target_date.isoformat()
    
    try:
        # Отримуємо всі дані з листа
        result = service.spreadsheets().values().get(
            spreadsheetId=settings.spreadsheet_id,
            range=f"{sheet_tab}!A:H"
        ).execute()
        
        values = result.get("values", [])
        if len(values) <= 1:  # Тільки заголовок або порожньо
            return
        
        # Знаходимо рядки з цією датою (індекси з 1, бо перший рядок - заголовок)
        rows_to_delete = []
        for i, row in enumerate(values[1:], start=2):  # Починаємо з рядка 2
            if row and len(row) > 0 and row[0] == date_str:
                rows_to_delete.append(i)
        
        if not rows_to_delete:
            logger.info(f"📋 Немає існуючих даних за {date_str}")
            return
        
        # Видаляємо рядки (в зворотному порядку щоб індекси не зсувалися)
        logger.info(f"🗑️  Видаляємо {len(rows_to_delete)} існуючих рядків за {date_str}...")
        
        # Отримуємо sheet ID
        sheet_metadata = service.spreadsheets().get(spreadsheetId=settings.spreadsheet_id).execute()
        sheet_id = None
        for sheet in sheet_metadata.get("sheets", []):
            if sheet["properties"]["title"] == sheet_tab:
                sheet_id = sheet["properties"]["sheetId"]
                break
        
        if sheet_id is None:
            logger.warning(f"Не знайдено sheet ID для {sheet_tab}")
            return
        
        # Створюємо batch запити для видалення рядків
        requests = []
        for row_index in reversed(rows_to_delete):
            requests.append({
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": row_index - 1,  # API використовує 0-based індекси
                        "endIndex": row_index
                    }
                }
            })
        
        # Виконуємо batch update
        body = {"requests": requests}
        service.spreadsheets().batchUpdate(
            spreadsheetId=settings.spreadsheet_id,
            body=body
        ).execute()
        
        logger.info(f"✅ Видалено {len(rows_to_delete)} старих рядків")
        
    except Exception as e:
        logger.warning(f"⚠️  Помилка при видаленні старих рядків: {e}")


def export_daily_stats(target_date: date, sheet_tab: str = "daily_stats"):
    """
    Експортувати статистику за день для всіх активних користувачів.
    При повторному експорті за ту саму дату - оновлює дані, а не додає дублікати.
    
    Args:
        target_date: Дата для експорту
        sheet_tab: Назва вкладки в Google Sheets
    """
    date_str = target_date.isoformat()
    
    logger.info(f"📅 Експорт даних за {date_str}")
    logger.info(f"📊 Вкладка: {sheet_tab}")
    logger.info(f"=" * 80)
    
    # 1. Отримуємо дані з API (один швидкий запит!)
    logger.info("🔍 Отримуємо статистику з YaWare API (getSummaryByDay)...")
    try:
        raw_data = client.get_summary_by_day(date_str)
        logger.info(f"✅ Отримано дані для {len(raw_data)} користувачів")
    except Exception as e:
        logger.error(f"❌ Помилка отримання даних з API: {e}")
        raise
    
    if not raw_data:
        logger.warning("⚠️  Немає даних для експорту")
        return
    
    # 2. Парсимо дані
    logger.info("🔄 Парсимо дані...")
    parsed_rows = []
    for record in raw_data:
        try:
            parsed = parse_summary_by_day(record, target_date)
            row = format_for_sheets_row(parsed)
            parsed_rows.append(row)
        except Exception as e:
            logger.warning(f"⚠️  Помилка парсингу для запису: {e}")
            continue
    
    logger.info(f"✅ Оброблено {len(parsed_rows)} рядків")
    
    if not parsed_rows:
        logger.warning("⚠️  Немає оброблених рядків для експорту")
        return
    
    # 3. Експортуємо в Google Sheets
    logger.info("📤 Експортуємо в Google Sheets...")
    try:
        service = _service()
        ensure_sheet_with_headers(service, sheet_tab)
        
        # Видаляємо старі дані за цю дату (якщо є)
        delete_rows_for_date(service, sheet_tab, target_date)
        
        # Додаємо нові рядки
        service.spreadsheets().values().append(
            spreadsheetId=settings.spreadsheet_id,
            range=f"{sheet_tab}!A:H",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": parsed_rows}
        ).execute()
        
        logger.info(f"✅ Експортовано {len(parsed_rows)} рядків у '{sheet_tab}'")
        
        # Виводимо статистику
        total_hours = sum(row[4] for row in parsed_rows)  # Total (h) column
        avg_productive = sum(row[6] for row in parsed_rows) / len(parsed_rows) if parsed_rows else 0  # Productive (%)
        
        logger.info(f"=" * 80)
        logger.info(f"📊 Статистика експорту:")
        logger.info(f"   Користувачів: {len(parsed_rows)}")
        logger.info(f"   Загальний час: {total_hours:.2f} годин")
        logger.info(f"   Середня продуктивність: {avg_productive:.1f}%")
        logger.info(f"=" * 80)
        logger.info(f"🎉 Експорт завершено успішно!")
        logger.info(f"🔗 Переглянути: https://docs.google.com/spreadsheets/d/{settings.spreadsheet_id}")
        
    except Exception as e:
        logger.error(f"❌ Помилка експорту в Sheets: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Експорт щоденної статистики активних користувачів YaWare в Google Sheets"
    )
    parser.add_argument(
        "date",
        nargs="?",
        help="Дата для експорту (YYYY-MM-DD). За замовчуванням: вчора"
    )
    parser.add_argument(
        "--sheet",
        default="daily_stats",
        help="Назва вкладки в Google Sheets (за замовчуванням: daily_stats)"
    )
    
    args = parser.parse_args()
    
    # Парсимо дату
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"❌ Невірний формат дати: {args.date}. Використовуйте YYYY-MM-DD")
            sys.exit(1)
    else:
        # За замовчуванням - вчора
        from datetime import timedelta
        target_date = date.today() - timedelta(days=1)
    
    try:
        export_daily_stats(target_date, args.sheet)
    except Exception as e:
        logger.error(f"❌ Критична помилка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
