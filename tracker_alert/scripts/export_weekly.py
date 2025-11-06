"""Скрипт для експорту тижневої статистики в Google Sheets."""
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


def normalize_email_value(email):
    """Повертає нормалізоване значення email (lower + strip)."""
    if not email:
        return None
    return email.strip().lower()


def generate_email_variants(email):
    """Повертає набір можливих варіантів email з альтернативними доменами."""
    variants = {email}
    if "@evrius.com" in email:
        variants.add(email.replace("@evrius.com", "@evadav.com"))
    if "@evadav.com" in email:
        variants.add(email.replace("@evadav.com", "@evrius.com"))
    return variants


def parse_manager_number(value):
    """Конвертує значення менеджера у ціле число або повертає None."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_manager_number(record):
    """Отримати номер менеджера з запису користувача."""
    manager_value = record.get("manager_number")
    if manager_value is None:
        manager_value = record.get("control_manager")
    return parse_manager_number(manager_value)


def parse_time_value(value: str):
    """Парсинг часу у форматі HH:MM або HH:MM:SS."""
    if not value:
        return None
    value = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def adjust_fact_start(day_data: dict, plan_start: str):
    """Скоригувати час фактичного старту з урахуванням плану."""
    fact_raw = day_data.get("time_start")
    parsed_fact = parse_time_value(fact_raw)
    parsed_plan = parse_time_value(plan_start)
    
    if not parsed_fact:
        return
    
    if not parsed_plan:
        day_data["fact_start_adjusted"] = parsed_fact.strftime("%H:%M")
        return
    
    earliest_allowed = parsed_plan - timedelta(hours=1)
    if parsed_fact < earliest_allowed:
        adjusted = earliest_allowed
    else:
        adjusted = parsed_fact
    
    day_data["fact_start_adjusted"] = adjusted.strftime("%H:%M")


def collect_peopleforce_data(week_days: list[date], user_emails: list[str]) -> dict:
    """
    Зібрати дані з PeopleForce для користувачів на вказаний тиждень.
    
    Args:
        week_days: Список дат тижня
        user_emails: Список email користувачів
        
    Returns:
        Dictionary з locations та leaves
    """
    try:
        pf_client = get_peopleforce_client()
        
        # Збираємо локації
        logger.info("📍 Получаю локации из PeopleForce...")
        locations = {}
        for email in user_emails:
            location = pf_client.get_employee_location(email)
            if location:
                formatted = pf_client.format_location_display(location)
                locations[email] = formatted.replace("Location: ", "")  # Тільки назва
        
        logger.info(f"   ✅ Найдено локации для {len(locations)} пользователей")
        
        # Збираємо відпустки/відсутності
        logger.info("🏖️ Получаю отпуска и отсутствия из PeopleForce...")
        first_day = week_days[0]
        last_day = week_days[-1]
        all_leaves = pf_client.get_leave_requests(start_date=first_day, end_date=last_day)
        
        # Групуємо по email і датам
        leaves = {}
        for leave in all_leaves:
            emp_email = leave.get("employee", {}).get("email", "").lower()
            if emp_email not in user_emails:
                continue
            
            # Визначаємо які дні тижня потрапляють в період відпустки
            leave_start = date.fromisoformat(leave["starts_on"])
            leave_end = date.fromisoformat(leave["ends_on"])
            
            if emp_email not in leaves:
                leaves[emp_email] = {}
            
            for day in week_days:
                if leave_start <= day <= leave_end:
                    leaves[emp_email][day] = leave

        logger.info(f"   ✅ Найдено отсутствий: {len(leaves)} пользователей")

        return {
            "locations": locations,
            "leaves": leaves
        }
        
    except Exception as e:
        logger.warning(f"⚠️  Ошибка получения данных из PeopleForce: {e}")
        logger.warning("   Продолжаем без PeopleForce данных")
        return {"locations": {}, "leaves": {}}


def export_weekly_stats(target_date: date, force: bool = False):
    """
    Експортувати тижневу статистику в Google Sheets.
    
    Створює аркуш типу "Week 41 (06-10 Oct 2025)" з блоками для кожного користувача.
    Кожен блок містить:
    - Заголовок з іменем + локацією
    - 5 рядків з даними (Пн-Пт)
    - Рядок Total з сумами
    - Порожній рядок-розділювач
    
    Args:
        target_date: Будь-яка дата в тижні для експорту
    """
    
    # 0. Перевірка: чи не експортуємо сьогоднішній день до завершення робочого дня
    today = date.today()
    now = datetime.now()
    end_of_workday_hour = 19  # 19:00 - після цього часу можна експортувати сьогодні
    
    # Якщо запитують дані за тиждень, що включає сьогодні
    monday, friday = get_week_range(target_date)
    week_includes_today = monday <= today <= friday
    
    # ВАЖЛИВО: блокуємо тільки якщо target_date >= today (тобто запитують саме сьогодні)
    # Якщо target_date < today, то це експорт минулих днів - дозволяємо
    if (
        not force
        and week_includes_today
        and target_date >= today
        and now.hour < end_of_workday_hour
    ):
        logger.warning("=" * 80)
        logger.warning("⚠️  Внимание: Рабочий день еще не завершен!")
        logger.warning(f"   Текущее время: {now.strftime('%H:%M')}")
        logger.warning(f"   Экспорт сегодняшнего дня ({today.strftime('%d.%m.%Y')}) возможен после {end_of_workday_hour}:00")
        logger.warning(f"   Данные за сегодня будут НЕПОЛНЫМИ и НЕКОРРЕКТНЫМИ")
        logger.warning("")
        logger.warning("❌ Я не могу предоставить отчет за сегодняшний день, так как рабочий день еще продолжается")
        logger.warning("")
        logger.warning("💡 Рекомендации:")
        logger.warning(f"   - Подождите до {end_of_workday_hour}:00 для экспорта с сегодняшним днем")
        logger.warning(f"   - ИЛИ запустите экспорт без сегодняшнего дня")
        logger.warning("=" * 80)
        return
    
    # 0.1. Визначаємо всі 5 днів тижня (Пн-Пт)
    all_week_days = [monday + timedelta(days=i) for i in range(5)]
    
    # 1. Визначаємо тиждень
    week_days = get_week_days(target_date, exclude_today=True)  # Виключаємо сьогодні
    week_days_str = [d.isoformat() for d in week_days]
    sheet_name = get_week_sheet_name(target_date)

    logger.info(f"📅 Экспорт недельной статистики")
    logger.info(f"   Неделя: {all_week_days[0]} - {all_week_days[-1]}")
    logger.info(f"   Лист: '{sheet_name}'")
    logger.info(f"=" * 80)
    
    # 2. Отримуємо дані з API за всі 5 днів
    if week_days_str:
        logger.info(f"🔍 Получаю данные из YaWare API за {len(week_days)} дней...")
        try:
            week_data = client.get_week_data(week_days_str)
            logger.info(f"✅ Получено данные из YaWare для {len(week_data)} пользователей")
        except Exception as e:
            logger.error(f"❌ Ошибка получения данных из API: {e}")
            raise
    else:
        logger.info("ℹ️  Нет завершенных рабочих дней для загрузки данных из YaWare.")
        week_data = {}

    # 2.1. Загружаємо ВСІХ користувачів з бази та додаємо тих, кого немає в YaWare
    logger.info("📚 Загружаю базу пользователей...")

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    db_path = os.path.join(base_dir, 'config', 'user_schedules.json')
    
    try:
        with open(db_path, 'r', encoding='utf-8') as f:
            database = json.load(f)
        
        all_users_from_db = database.get('users', {})
        
        # Функція нормалізації імені
        def normalize(name):
            """Нормалізація імені: lower, strip, множинні пробіли -> один пробіл"""
            if not name:
                return ""
            return re.sub(r'\s+', ' ', name.lower().strip())
        
        def apply_db_fields(target, source):
            """Додає додаткові поля з бази до запису користувача."""
            if not target.get("start_time"):
                target["start_time"] = source.get("start_time", "")
            target["project"] = source.get("project") or ""
            target["department"] = source.get("department") or ""
            target["team"] = source.get("team") or ""
            manager_value = source.get("manager_number")
            if manager_value is None:
                manager_value = source.get("control_manager")
            parsed_manager = parse_manager_number(manager_value)
            if parsed_manager is not None:
                target["manager_number"] = parsed_manager
        
        db_email_map = {}
        db_name_map = {}
        
        for db_name, db_data in all_users_from_db.items():
            normalized_name = normalize(db_name)
            if normalized_name:
                db_name_map.setdefault(normalized_name, db_data)
            words = db_name.split()
            if len(words) == 2:
                reversed_name = normalize(f"{words[1]} {words[0]}")
                db_name_map.setdefault(reversed_name, db_data)
            
            normalized_email = normalize_email_value(db_data.get('email'))
            if normalized_email:
                for variant in generate_email_variants(normalized_email):
                    db_email_map.setdefault(variant, db_data)
        
        # 2.1.1. ВИДАЛЯЄМО виключених користувачів з YaWare даних
        excluded_names = set()
        for db_name, db_data in all_users_from_db.items():
            if not db_data.get('exclude_from_reports', False):
                continue
            normalized_name = normalize(db_name)
            if normalized_name:
                excluded_names.add(normalized_name)
            words = db_name.split()
            if len(words) == 2:
                excluded_names.add(normalize(f"{words[1]} {words[0]}"))
        
        excluded_count = 0
        keys_to_remove = []
        
        for week_key, week_user_data in week_data.items():
            full_name = week_user_data.get("full_name", "")
            if normalize(full_name) in excluded_names:
                keys_to_remove.append(week_key)
                excluded_count += 1
        
        for key in keys_to_remove:
            del week_data[key]
        
        if excluded_count > 0:
            logger.info(f"🚫 Удалено {excluded_count} исключенных пользователей из YaWare данных")
            logger.info(f"📊 Осталось пользователей: {len(week_data)}")

        # 2.1.2. Создаем нормализованную мапу для сравнения
        yaware_normalized = {normalize(data.get("full_name", "")): key for key, data in week_data.items()}
        
        # 2.1.3. Доповнюємо дані користувачів інформацією з бази
        for week_user_data in week_data.values():
            db_record = None
            normalized_email = normalize_email_value(week_user_data.get("email"))
            if normalized_email:
                db_record = db_email_map.get(normalized_email)
            if not db_record:
                db_record = db_name_map.get(normalize(week_user_data.get("full_name", "")))
            
            if db_record:
                apply_db_fields(week_user_data, db_record)
            else:
                week_user_data.setdefault("project", "")
                week_user_data.setdefault("department", "")
                week_user_data.setdefault("team", "")
            
            plan_start_value = week_user_data.get("start_time")
            for day_entry in week_user_data.get("days", []):
                adjust_fact_start(day_entry, plan_start_value)
        
        # 2.1.4. Додаємо користувачів з бази, яких немає в YaWare
        added_count = 0
        for db_name, db_data in all_users_from_db.items():
            if db_data.get('exclude_from_reports', False):
                continue
            
            words = db_name.split()
            found = False
            
            if normalize(db_name) in yaware_normalized:
                found = True
            elif len(words) == 2:
                reversed_name = f"{words[1]} {words[0]}"
                if normalize(reversed_name) in yaware_normalized:
                    found = True
            
            if not found:
                record = {
                    "full_name": db_name,
                    "email": db_data.get('email', ''),
                    "start_time": db_data.get('start_time', ''),
                    "days": [],
                    "from_database": True
                }
                apply_db_fields(record, db_data)
                week_data[f"missing_{db_name}"] = record
                added_count += 1

        logger.info(f"✅ Добавлено {added_count} пользователей из базы (без данных YaWare)")
        logger.info(f"📊 Всего пользователей для экспорта: {len(week_data)}")

        managerless_count = sum(1 for data in week_data.values() if get_manager_number(data) is None)
        if managerless_count:
            logger.info(f"ℹ️  {managerless_count} пользователей без привязки к менеджеру (остаются лишь в общем отчете)")
        
    except Exception as e:
        logger.warning(f"⚠️  Не удалось загрузить базу пользователей: {e}")
        logger.warning("   Продолжаем только с YaWare данными")

    if not week_data:
        logger.warning("⚠️  Нет данных для экспорта за указанный период.")
        return

    # 2.5. Получаем данные из PeopleForce
    logger.info("🔄 Получаем данные из PeopleForce...")
    user_emails = [user["email"].lower() for user in week_data.values() if "email" in user]
    peopleforce_data = collect_peopleforce_data(all_week_days, user_emails)

    # 3. Форматируем данные для Sheets (передаем все дни недели чтобы зарезервировать строки)
    logger.info("🔄 Форматируем данные для экспорта...")
    # Получаем все 5 дней недели (Пн-Пт) независимо от того, есть ли данные
    monday, friday = get_week_range(target_date)
    all_week_days = [monday + timedelta(days=i) for i in range(5)]
    
    all_rows = format_all_user_blocks(week_data, all_week_days, peopleforce_data)
    logger.info(f"✅ Сгенерировано {len(all_rows)} строк")

    # 4. Создаем/обновляем лист
    logger.info(f"📤 Создаем лист '{sheet_name}'...")
    success = create_weekly_sheet(sheet_name, all_rows)
    
    if not success:
        logger.error("❌ Ошибка создания листа")
        return

    # 5. Применяем форматирование
    logger.info("🎨 Применяем форматирование...")
    # Передаем week_data чтобы иметь доступ к email пользователей
    apply_weekly_formatting(sheet_name, len(all_rows), week_data, all_week_days, peopleforce_data)

    # 6. Обновляем таблицы контроль менеджеров
    manager_configs = [
        (1, settings.spreadsheet_id_control_1),
        (2, settings.spreadsheet_id_control_2)
    ]
    for manager_number, spreadsheet_id in manager_configs:
        manager_week_data = {
            key: value
            for key, value in week_data.items()
            if get_manager_number(value) == manager_number
        }
        
        if not manager_week_data:
            logger.info(f"⚠️  Пропуск таблицы менеджера {manager_number}: нет пользователей")
            continue

        logger.info(f"📤 Синхронизируем таблицу менеджера {manager_number} ({len(manager_week_data)} пользователей)")
        manager_rows = format_all_user_blocks(manager_week_data, all_week_days, peopleforce_data)
        
        original_spreadsheet_id = settings.spreadsheet_id
        settings.spreadsheet_id = spreadsheet_id
        try:
            manager_success = create_weekly_sheet(sheet_name, manager_rows)
            if not manager_success:
                logger.error(f"❌ Ошибка создания листа для менеджера {manager_number}")
                continue
            apply_weekly_formatting(sheet_name, len(manager_rows), manager_week_data, all_week_days, peopleforce_data)
        finally:
            settings.spreadsheet_id = original_spreadsheet_id

    # 7. Финальная статистика
    logger.info(f"=" * 80)
    logger.info(f"📊 Статистика экспорта:")
    logger.info(f"   Пользователей: {len(week_data)}")
    logger.info(f"   Дней: {len(week_days)}")
    logger.info(f"   Строк: {len(all_rows)}")
    logger.info(f"=" * 80)
    logger.info(f"🎉 Экспорт завершен успешно!")
    logger.info(f"🔗 Просмотреть: https://docs.google.com/spreadsheets/d/{settings.spreadsheet_id}")


def main():
    """CLI для экспорта недельной статистики."""
    parser = argparse.ArgumentParser(
        description="Экспорт недельной статистики YaWare в Google Sheets"
    )
    parser.add_argument(
        "date",
        nargs="?",
        help="Любая дата в неделе (YYYY-MM-DD). По умолчанию: текущая неделя"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Игнорировать проверку продолжительности рабочего дня для текущей недели"
    )
    
    args = parser.parse_args()

    # Определяем дату
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error(f"❌ Неверный формат даты: {args.date}. Используйте YYYY-MM-DD")
            return 1
    else:
        # По умолчанию - текущая неделя
        target_date = date.today()
    
    try:
        export_weekly_stats(target_date, force=args.force)
        return 0
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit(main())
