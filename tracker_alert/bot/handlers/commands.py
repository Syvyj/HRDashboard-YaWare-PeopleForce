"""Command handlers for the Telegram bot."""
import logging
import json
from datetime import date, timedelta
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from tracker_alert.services.attendance_monitor import AttendanceMonitor
from tracker_alert.services.report_formatter import format_attendance_report, format_short_summary
from tracker_alert.client.yaware_v2_api import YaWareV2Client

logger = logging.getLogger(__name__)


def transliterate_to_english(text: str) -> str:
    """Транслітерувати кирилицю в латиницю.
    
    Args:
        text: Текст для транслітерації
        
    Returns:
        Транслітерований текст
    """
    # Українська транслітерація
    uk_translit = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e', 'є': 'ie',
        'ж': 'zh', 'з': 'z', 'и': 'y', 'і': 'i', 'ї': 'i', 'й': 'i', 'к': 'k', 'л': 'l',
        'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ь': '', 'ю': 'iu', 'я': 'ia',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'H', 'Ґ': 'G', 'Д': 'D', 'Е': 'E', 'Є': 'Ie',
        'Ж': 'Zh', 'З': 'Z', 'И': 'Y', 'І': 'I', 'Ї': 'I', 'Й': 'I', 'К': 'K', 'Л': 'L',
        'М': 'M', 'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch', 'Ь': '', 'Ю': 'Iu', 'Я': 'Ia'
    }
    
    # Російська транслітерація (схожа, але з відмінностями)
    ru_translit = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'i', 'к': 'k', 'л': 'l',
        'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'iu', 'я': 'ia',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'E',
        'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'I', 'К': 'K', 'Л': 'L',
        'М': 'M', 'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
        'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch', 'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Iu', 'Я': 'Ia'
    }
    
    # Об'єднуємо обидва словники
    translit = {**uk_translit, **ru_translit}
    
    result = []
    for char in text:
        result.append(translit.get(char, char))
    
    return ''.join(result)


def is_cyrillic(text: str) -> bool:
    """Перевірити чи містить текст кирилицю.
    
    Args:
        text: Текст для перевірки
        
    Returns:
        True якщо є хоча б один кириличний символ
    """
    return any('\u0400' <= char <= '\u04FF' for char in text)


def levenshtein_distance(s1: str, s2: str) -> int:
    """Обчислити відстань Левенштейна між двома рядками.
    
    Args:
        s1: Перший рядок
        s2: Другий рядок
        
    Returns:
        Кількість операцій (вставка/видалення/заміна) для перетворення s1 в s2
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Вартість вставки, видалення або заміни
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def find_similar_users(search_query: str, users_db: dict, max_results: int = 5) -> list:
    """Знайти схожі імена користувачів в базі.
    
    Args:
        search_query: Пошуковий запит (може бути транслітерований)
        users_db: База користувачів
        max_results: Максимальна кількість результатів
        
    Returns:
        Список імен користувачів, які найбільш схожі
    """
    query_lower = search_query.lower()
    matches = []
    
    # 1. Точний збіг (повне ім'я або email)
    for user_name, user_data in users_db.items():
        if query_lower == user_name.lower():
            return [user_name]  # Точний збіг - повертаємо одразу
        if query_lower == user_data.get('email', '').lower():
            return [user_name]
    
    # 2. Пошук по частині імені (прізвище або ім'я)
    for user_name in users_db.keys():
        name_parts = user_name.lower().split()
        for part in name_parts:
            # Якщо запит повністю співпадає з частиною імені
            if query_lower == part:
                matches.append((user_name, 100, 0))  # (ім'я, пріоритет, відстань)
                break
            # Якщо запит є підстрокою частини імені або навпаки
            elif query_lower in part or part in query_lower:
                matches.append((user_name, 90, 0))
                break
    
    # 3. Пошук з Levenshtein distance (для транслітерації)
    if len(matches) < max_results:
        for user_name in users_db.keys():
            # Перевіряємо чи вже додано
            if any(user_name == m[0] for m in matches):
                continue
            
            name_parts = user_name.lower().split()
            best_distance = float('inf')
            
            # Шукаємо найближчу частину імені
            for part in name_parts:
                distance = levenshtein_distance(query_lower, part)
                if distance < best_distance:
                    best_distance = distance
            
            # Також перевіряємо повне ім'я
            full_name_distance = levenshtein_distance(query_lower, user_name.lower())
            if full_name_distance < best_distance:
                best_distance = full_name_distance
            
            # Обчислюємо схожість у відсотках
            max_len = max(len(query_lower), max(len(p) for p in name_parts))
            similarity = (1 - best_distance / max_len) * 100
            
            # Додаємо якщо схожість > 50%
            if similarity > 50:
                matches.append((user_name, int(similarity), best_distance))
    
    # Сортуємо: спочатку за пріоритетом (більший краще), потім за відстанню (менша краще)
    matches.sort(key=lambda x: (-x[1], x[2]))
    
    # Повертаємо тільки імена (без пріоритету та відстані)
    return [name for name, _, _ in matches[:max_results]]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    bot = context.bot_data.get('attendance_bot')
    chat_id = update.effective_chat.id
    
    if not bot or not bot.is_admin(chat_id):
        await update.effective_message.reply_text("⛔ Доступ запрещен.")
        logger.warning(f"Unauthorized access attempt from chat {chat_id}")
        return
    
    # Отримуємо статистику (без викликів до PeopleForce для швидкості)
    from tracker_alert.services import user_manager
    
    try:
        monitor = AttendanceMonitor()
        
        # Загальна кількість користувачів
        all_users_data = user_manager.load_users()
        total_user_count = len(all_users_data.get('users', {}))
        
        # Активні користувачі
        active_user_count = len(monitor.schedules)
        
        welcome_message = (
            "👋 Добро пожаловать в Eva_Control_Bot!\n\n"
            "Я помогаю отслеживать присутствие сотрудников.\n\n"
            f"📊 *СТАТИСТИКА:*\n"
            f"   • Всего пользователей в базе: *{total_user_count}*\n"
            f"   • Активных (с графиком): *{active_user_count}*\n\n"
            "Выберите действие из меню ниже:"
        )
    except Exception as e:
        logger.error(f"Помилка отримання статистики: {e}")
        welcome_message = (
            "👋 Добро пожаловать в Eva_Control_Bot!\n\n"
            "Я помогаю отслеживать присутствие сотрудников.\n\n"
            "Выберите действие из меню ниже:"
        )
    
    # Створюємо Inline кнопки
    bot = context.bot_data.get('attendance_bot')
    sheet_url = bot.get_manager_sheet_url(chat_id) if bot else "https://docs.google.com/spreadsheets/d/1MAOpHjbOssn1hXR0RPnXjmYJaRbziqQud3TwMKc8jBs/edit#gid=0"
    keyboard = [
        [
            InlineKeyboardButton("📊 Отчет на сегодня", callback_data="report_today"),
            InlineKeyboardButton("👤 Статистика пользователя", callback_data="ask_user")
        ],
        [
            InlineKeyboardButton("❓ Справка", callback_data="help")
        ],
        [
            InlineKeyboardButton("📅 Отчет за вчера в Google Sheets", url=sheet_url)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.effective_message.reply_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    bot = context.bot_data.get('attendance_bot')
    chat_id = update.effective_chat.id
    
    if not bot or not bot.is_admin(chat_id):
        await update.effective_message.reply_text("⛔ Доступ запрещен.")
        return
    
    help_message = (
        "📖 СПРАВКА БОТА\n\n"
        "КОМАНДЫ:\n"
        "/start - Запустить бота\n"
        "/help - Показать эту справку\n"
        "/status - Статус бота\n"
        "/report_today - Отчет на сегодня\n"
        "/user <имя> - Статистика пользователя\n\n"
        "АВТОМАТИЧЕСКИЕ ОТЧЕТЫ:\n"
        "Бот отправляет ежедневные отчеты в 10:00 Warsaw time.\n\n"
        "КАТЕГОРИИ ОТЧЕТОВ:\n"
        "⚠️ Опоздали - более 15 мин\n"
        "❌ Отсутствуют - нет данных\n"
        "✅ Вовремя - не включены в отчет\n\n"
        "Сотрудники в отпуске (PeopleForce) автоматически исключаются."
    )
    
    await update.effective_message.reply_text(help_message)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    bot = context.bot_data.get('attendance_bot')
    chat_id = update.effective_chat.id
    
    if not bot or not bot.is_admin(chat_id):
        await update.effective_message.reply_text("⛔ Доступ заборонено.")
        return
    
    try:
        # Load monitor to check configuration
        monitor = AttendanceMonitor()
        user_count = len(monitor.schedules)
        
        status_message = (
            f"✅ БОТ АКТИВНИЙ\n\n"
            f"👥 Активних користувачів: {user_count}\n"
            f"⏰ Grace period: {monitor.GRACE_PERIOD_MINUTES} хв\n"
            f"📊 Час щоденного звіту: 10:00 Warsaw\n"
            f"🔐 Адмін чатів: {len(bot.admin_chat_ids) if bot.admin_chat_ids else 'None (dev mode)'}"
        )
        
        await update.effective_message.reply_text(status_message)
        
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        await update.effective_message.reply_text(
            f"⚠️ Помилка перевірки статусу\n\nError: {str(e)}"
        )


async def report_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /report_today command."""
    bot = context.bot_data.get('attendance_bot')
    chat_id = update.effective_chat.id
    
    if not bot or not bot.is_admin(chat_id):
        await update.effective_message.reply_text("⛔ Доступ заборонено.")
        return
    
    try:
        # Send "generating..." message
        status_msg = await update.effective_message.reply_text("⏳ Генерую звіт за сьогодні...")
        
        # Generate report
        monitor = AttendanceMonitor()
        today = date.today()
        report = monitor.get_daily_report(today)
        allowed_managers = bot.get_allowed_managers(chat_id)
        report, _ = monitor.filter_report_by_managers(report, allowed_managers)
        
        # Format and send
        if report['late'] or report['absent']:
            formatted_report = format_attendance_report(report, today)
            await status_msg.edit_text(formatted_report, parse_mode="Markdown")
        else:
            await status_msg.edit_text(
                f"✅ Звіт за {today.strftime('%Y-%m-%d')}\n\n"
                "🎉 Всі співробітники вчасно! Проблем немає."
            )
        
    except Exception as e:
        logger.error(f"Report generation failed: {e}")
        await update.effective_message.reply_text(
            f"⚠️ Помилка генерації звіту\n\nError: {str(e)}"
        )


async def user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /user command to get specific user statistics."""
    bot = context.bot_data.get('attendance_bot')
    chat_id = update.effective_chat.id
    
    if not bot or not bot.is_admin(chat_id):
        await update.effective_message.reply_text("⛔ Доступ заборонено.")
        return
    
    # Перевірка аргументів
    if not context.args:
        await update.effective_message.reply_text(
            "ℹ️ Використання:\n"
            "/user <ім'я або email>\n\n"
            "Приклади:\n"
            "/user Ziuzin\n"
            "/user Shilko Alexandra\n"
            "/user o.ziuzin@evadav.com"
        )
        return
    
    search_query = " ".join(context.args)
    
    try:
        # Завантажити базу користувачів
        db_path = Path(__file__).resolve().parents[3] / "config" / "user_schedules.json"
        with open(db_path, 'r', encoding='utf-8') as f:
            database = json.load(f)
        users_db = database['users']
        
        # Знайти користувача
        user_name, user_data = find_user_in_db(search_query, users_db)
        
        if not user_name:
            await update.effective_message.reply_text(
                f"❌ Користувача '{search_query}' не знайдено!\n\n"
                "Спробуйте:\n"
                "• Повне ім'я (наприклад: 'Ziuzin Oleksii')\n"
                "• Email (наприклад: 'o.ziuzin@evadav.com')\n"
                "• Частина імені (наприклад: 'Ziuzin')"
            )
            return
        
        # Відправити "завантаження..."
        status_msg = await update.effective_message.reply_text(
            f"⏳ Завантаження даних для {user_name}..."
        )
        
        # Отримати дані за сьогодні
        yaware_client = YaWareV2Client()
        today = date.today()
        today_info = get_user_today_stats(user_name, user_data, yaware_client, today)
        
        # Форматувати повідомлення
        message = format_user_stats_message(user_name, user_data, today_info)
        
        await status_msg.edit_text(message)
        
    except Exception as e:
        logger.error(f"User stats error: {e}", exc_info=True)
        await update.effective_message.reply_text(
            f"⚠️ Помилка отримання даних\n\nError: {str(e)}"
        )


def find_user_in_db(search_query, users_db):
    """Знайти користувача по імені або email."""
    search_lower = search_query.lower().strip()
    
    # Пошук по email
    for name, data in users_db.items():
        if data.get('email', '').lower() == search_lower:
            return name, data
    
    # Пошук по точному імені
    for name, data in users_db.items():
        if name.lower() == search_lower:
            return name, data
    
    # Пошук по словам (будь-який порядок)
    search_words = search_lower.split()
    if len(search_words) >= 2:
        for name, data in users_db.items():
            name_words = name.lower().split()
            if all(word in name_words for word in search_words):
                return name, data
    
    # Пошук по частині
    for name, data in users_db.items():
        name_lower = name.lower()
        if search_lower in name_lower or name_lower in search_lower:
            return name, data
    
    return None, None


def get_user_today_stats(user_name, user_data, yaware_client, target_date):
    """Отримати статистику користувача за день."""
    user_id = str(user_data.get('user_id'))
    
    if not user_id:
        return None
    
    date_str = target_date.strftime('%Y-%m-%d')
    all_data = yaware_client.get_summary_by_day(date_str)
    
    # Знайти дані користувача
    user_record = None
    for record in all_data:
        if str(record.get('user_id')) == user_id:
            user_record = record
            break
    
    if not user_record:
        return {
            'date': target_date.strftime('%d.%m.%Y'),
            'started': None,
            'worked_minutes': 0,
            'productive_minutes': 0,
            'distracting_minutes': 0,
            'status': 'Не почав роботу'
        }
    
    # Парсинг даних
    start_time = user_record.get('time_start')
    total_seconds = int(user_record.get('total', 0))
    productive_seconds = int(user_record.get('productive', 0))
    distracting_seconds = int(user_record.get('distracting', 0))
    
    worked_minutes = total_seconds / 60
    productive_minutes = productive_seconds / 60
    distracting_minutes = distracting_seconds / 60
    
    status = 'Працює' if worked_minutes > 0 else 'Тільки почав'
    
    return {
        'date': target_date.strftime('%d.%m.%Y'),
        'started': start_time if start_time and start_time != '—' else None,
        'worked_minutes': worked_minutes,
        'productive_minutes': productive_minutes,
        'distracting_minutes': distracting_minutes,
        'status': status
    }


def format_time_hhmm(minutes):
    """Конвертувати хвилини в HH:MM."""
    if minutes is None or minutes == 0:
        return "—"
    hours = int(minutes // 60)
    mins = int(minutes % 60)
    return f"{hours:02d}:{mins:02d}"


def format_user_stats_message(user_name, user_data, today_info):
    """Форматувати повідомлення зі статистикою користувача."""
    lines = []
    lines.append("=" * 40)
    lines.append(f"👤 СТАТИСТИКА КОРИСТУВАЧА")
    lines.append("=" * 40)
    lines.append("")
    lines.append(f"📋 Ім'я: {user_name}")
    lines.append(f"📧 Email: {user_data.get('email', '—')}")
    lines.append(f"📍 Локація: {user_data.get('location', '—')}")
    lines.append(f"⏰ Графік: {user_data.get('start_time', '09:00')}")
    
    if user_data.get('exclude_from_reports'):
        lines.append(f"⚠️ Статус: ВИКЛЮЧЕНИЙ З ЗВІТІВ")
        if user_data.get('note'):
            lines.append(f"   Примітка: {user_data['note']}")
    
    lines.append("")
    lines.append("-" * 40)
    lines.append(f"📅 РОБОТА СЬОГОДНІ ({today_info['date']})")
    lines.append("-" * 40)
    lines.append("")
    
    if today_info['started']:
        lines.append(f"🕐 Початок: {today_info['started']}")
        lines.append(f"📊 Статус: {today_info['status']}")
        lines.append("")
        lines.append(f"⏱️  Відпрацьовано: {format_time_hhmm(today_info['worked_minutes'])}")
        lines.append(f"✅ Продуктивне: {format_time_hhmm(today_info['productive_minutes'])}")
        lines.append(f"❌ Непродуктивне: {format_time_hhmm(today_info['distracting_minutes'])}")
        
        if today_info['worked_minutes'] > 0:
            productivity = (today_info['productive_minutes'] / today_info['worked_minutes']) * 100
            lines.append("")
            lines.append(f"📈 Продуктивність: {productivity:.1f}%")
    else:
        lines.append(f"❌ {today_info['status']}")
    
    lines.append("")
    lines.append("=" * 40)
    
    return "\n".join(lines)


# ========== CALLBACK HANDLERS ==========

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()  # Підтвердити натискання
    
    bot = context.bot_data.get('attendance_bot')
    chat_id = update.effective_chat.id
    
    if not bot or not bot.is_admin(chat_id):
        await query.edit_message_text("⛔ Доступ заборонено.")
        return
    
    # Обробка різних callback_data
    if query.data == "report_today":
        await handle_report_today_callback(query, context)
    elif query.data == "status":
        await handle_status_callback(query, context)
    elif query.data == "help":
        await handle_help_callback(query, context)
    elif query.data == "ask_user":
        await handle_ask_user_callback(query, context)
    elif query.data == "cancel_user_search":
        await handle_cancel_user_search(query, context)
    elif query.data == "back_to_menu":
        await handle_back_to_menu(query, context)
    elif query.data.startswith("user_select:"):
        # Обробка вибору користувача з транслітерації
        await handle_user_select_callback(query, context)


async def handle_report_today_callback(query, context):
    """Обробити запит звіту за сьогодні."""
    bot = context.bot_data.get('attendance_bot')
    chat_id = query.message.chat.id if query.message else query.from_user.id
    await query.edit_message_text("⏳ Генерирую отчет на сегодня...")
    
    try:
        monitor = AttendanceMonitor()
        today = date.today()
        report = monitor.get_daily_report(today)
        allowed_managers = bot.get_allowed_managers(chat_id) if bot else None
        
        # Отримуємо дані відсутніх з PeopleForce (точно як в peopleforce_api.py)
        leaves_list = []
        try:
            from tracker_alert.client.peopleforce_api import PeopleForceClient
            from datetime import datetime
            pf_client = PeopleForceClient()
            all_leaves = pf_client.get_leave_requests(start_date=today, end_date=today)
            
            # Фільтруємо тільки ті що попадають на сьогодні (як в get_employee_leave_on_date)
            for leave in all_leaves:
                leave_start = datetime.fromisoformat(leave["starts_on"]).date()
                leave_end = datetime.fromisoformat(leave["ends_on"]).date()
                if leave_start <= today <= leave_end:
                    leaves_list.append(leave)
        except Exception as e:
            logger.warning(f"Не вдалось отримати дані PeopleForce: {e}")
        
        report, leaves_list = monitor.filter_report_by_managers(report, allowed_managers, leaves_list)
        
        if report['late'] or report['absent']:
            formatted_report = format_attendance_report(report, today, leaves_list)
            
            # Додаємо кнопку "Назад"
            keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Если отчет слишком длинный, отправляем его как новое сообщение вместо редактирования
            from tracker_alert.services.report_formatter import split_message, TELEGRAM_MAX_LENGTH
            if len(formatted_report) > TELEGRAM_MAX_LENGTH:
                # Отправляем как новое сообщение вместо edit
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=formatted_report,
                    parse_mode="Markdown"
                )
                # Обновляем старое сообщение с финальной кнопкой
                await query.edit_message_text(
                    "📊 Отчет отправлен выше ⬆️",
                    reply_markup=reply_markup
                )
            else:
                await query.edit_message_text(
                    formatted_report,
                    reply_markup=reply_markup
                )
        else:
            # Якщо немає опозданий і відсутніх, але є відпустки
            if leaves_list:
                pf_lines = [f"📊 Отсутствуют по уважительной причине ({len(leaves_list)} чел):"]
                for leave in leaves_list:
                    # Отримуємо ім'я співробітника
                    employee_data = leave.get('employee', {})
                    if isinstance(employee_data, dict):
                        first_name = employee_data.get('first_name', '')
                        last_name = employee_data.get('last_name', '')
                        name = f"{first_name} {last_name}".strip() or "Unknown"
                    else:
                        name = str(employee_data)
                    
                    # leave_type може бути string або dict
                    leave_type_data = leave.get('leave_type', 'Неизвестно')
                    if isinstance(leave_type_data, dict):
                        leave_type_name = leave_type_data.get('name', 'Неизвестно')
                    else:
                        leave_type_name = str(leave_type_data)
                    
                    pf_lines.append(f"   • {name} - {leave_type_name}")
                pf_block = "\n".join(pf_lines)
                message = f"✅ Отчет за {today.strftime('%Y-%m-%d')}\n\n{pf_block}\n\n🎉 Все сотрудники вовремя! Проблем нет."
            else:
                message = f"✅ Отчет за {today.strftime('%Y-%m-%d')}\n\n🎉 Все сотрудники вовремя! Проблем нет."
            
            keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )
    except Exception as e:
        import traceback
        logger.error(f"Report generation failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⚠️ Ошибка генерации отчета\n\nError: {str(e)}",
            reply_markup=reply_markup
        )


async def handle_status_callback(query, context):
    """Обробити запит статусу."""
    try:
        from tracker_alert.services import user_manager
        from datetime import date
        
        # Створюємо монітор (так само як в інших функціях)
        monitor = AttendanceMonitor()
        
        # Кількість активних користувачів (з графіком)
        active_user_count = len(monitor.schedules)
        
        # Загальна кількість користувачів в базі
        all_users_data = user_manager.load_users()
        total_user_count = len(all_users_data.get('users', {}))
        
        # Кількість відсутніх за поважних причин (використовуємо той самий метод, що і для звітів)
        try:
            today = date.today()
            leaves_today = monitor._get_leaves_for_date(today)
            absent_count = len(leaves_today)
        except Exception as e:
            logger.warning(f"Не вдалось отримати дані PeopleForce: {e}")
            absent_count = "N/A"
        
        status_message = (
            f"✅ БОТ АКТИВЕН\n\n"
            f"📊 *СТАТИСТИКА БАЗИ ДАННЫХ:*\n"
            f"   • Всего пользователей в базе: *{total_user_count}*\n"
            f"   • Активных (с графиком): *{active_user_count}*\n"
            f"   • Отсутствуют по уважительным причинам (PF): *{absent_count}*\n\n"
            f"⚙️ *НАСТРОЙКИ:*\n"
            f"   • Grace period: *{monitor.GRACE_PERIOD_MINUTES}* мин\n"
            f"   • Время ежедневного отчета: *10:00 Warsaw*"
        )
        
        keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            status_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⚠️ Ошибка проверки статуса\n\nError: {str(e)}",
            reply_markup=reply_markup
        )


async def handle_help_callback(query, context):
    """Обробити запит довідки."""
    help_message = (
        "📖 СПРАВКА БОТА\n\n"
        "КОМАНДЫ:\n"
        "/start - Главное меню\n"
        "/user <имя> - Статистика пользователя\n\n"
        "АВТОМАТИЧЕСКИЕ ОТЧЕТЫ:\n"
        "Бот отправляет ежедневные отчеты в 10:00 Warsaw time.\n\n"
        "КАТЕГОРИИ:\n"
        "⚠️ Опоздали - более 15 мин\n"
        "❌ Отсутствуют - нет данных\n"
        "✅ Вовремя - не включены\n\n"
        "Сотрудники в отпуске автоматически исключаются."
    )
    
    keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        help_message,
        reply_markup=reply_markup
    )


async def handle_ask_user_callback(query, context):
    """Обробити запит статистики користувача."""
    # Зберігаємо стан що очікуємо введення імені користувача
    context.user_data['waiting_for_user_name'] = True
    context.user_data['original_message_id'] = query.message.message_id
    
    message = (
        "👤 Статистика пользователя\n\n"
        "Введите имя или email пользователя:\n\n"
        "Примеры:\n"
        "• Ziuzin\n"
        "• Shilko Alexandra\n"
        "• o.ziuzin@evadav.com"
    )
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="cancel_user_search")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        message,
        reply_markup=reply_markup
    )
    await query.answer()


async def handle_cancel_user_search(query, context):
    """Скасувати пошук користувача."""
    context.user_data['waiting_for_user_name'] = False
    await handle_back_to_menu(query, context)


async def handle_user_select_callback(query, context):
    """Обробити вибір користувача з транслітерації."""
    # Витягуємо ім'я користувача з callback_data
    user_name = query.data.replace("user_select:", "")
    
    try:
        # Завантажити базу користувачів
        db_path = Path(__file__).resolve().parents[3] / "config" / "user_schedules.json"
        with open(db_path, 'r', encoding='utf-8') as f:
            database = json.load(f)
        users_db = database['users']
        
        # Знайти користувача
        if user_name not in users_db:
            keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"❌ Пользователь '{user_name}' не найден в базе!",
                reply_markup=reply_markup
            )
            return
        
        user_data = users_db[user_name]
        
        # Показати "завантаження..."
        await query.edit_message_text(f"⏳ Загрузка данных для {user_name}...")
        
        # Отримати дані за сьогодні
        yaware_client = YaWareV2Client()
        today = date.today()
        today_info = get_user_today_stats(user_name, user_data, yaware_client, today)
        
        # Форматувати повідомлення
        message = format_user_stats_message(user_name, user_data, today_info)
        
        # Додаємо кнопку "Назад"
        keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)
        
    except Exception as e:
        logger.error(f"User select error: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"⚠️ Ошибка получения данных\n\nError: {str(e)}",
            reply_markup=reply_markup
        )



async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробити текстові повідомлення (для діалогів)."""
    # Перевіряємо чи очікуємо введення імені користувача
    if context.user_data.get('waiting_for_user_name'):
        bot = context.bot_data.get('attendance_bot')
        chat_id = update.effective_chat.id
        
        if not bot or not bot.is_admin(chat_id):
            return
        
        search_query = update.message.text.strip()
        
        # Скидаємо стан очікування
        context.user_data['waiting_for_user_name'] = False
        
        try:
            # Завантажити базу користувачів
            db_path = Path(__file__).resolve().parents[3] / "config" / "user_schedules.json"
            with open(db_path, 'r', encoding='utf-8') as f:
                database = json.load(f)
            users_db = database['users']
            
            # Перевірити чи введено кирилицею
            if is_cyrillic(search_query):
                # Транслітерувати
                transliterated = transliterate_to_english(search_query)
                logger.info(f"Cyrillic detected: '{search_query}' -> '{transliterated}'")
                search_query = transliterated  # Використовуємо транслітерацію для пошуку
            
            # Використовуємо розумний пошук
            possible_matches = find_similar_users(search_query, users_db, max_results=5)
            
            if not possible_matches:
                keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"❌ Не найдено соответствий для '{search_query}'\n\n"
                    "Попробуйте:\n"
                    "• Полное имя (например: 'Ziuzin Oleksii')\n"
                    "• Email (например: 'o.ziuzin@evadav.com')\n"
                    "• Часть фамилии (например: 'Ziuzin')",
                    reply_markup=reply_markup
                )
                return
            
            # Якщо знайдено варіанти - показуємо їх з кнопками
            if len(possible_matches) == 1:
                # Тільки один варіант - показуємо відразу
                search_query = possible_matches[0]
            else:
                # Декілька варіантів - запитуємо підтвердження
                message = f"🔍 Возможно вы имели в виду:\n"
                
                # Створюємо кнопки для кожного варіанту
                keyboard = []
                for i, match in enumerate(possible_matches):
                    # Зберігаємо ім'я користувача в callback_data
                    keyboard.append([InlineKeyboardButton(
                        f"👤 {match}",
                        callback_data=f"user_select:{match}"
                    )])
                
                # Додаємо кнопку скасування
                keyboard.append([InlineKeyboardButton("❌ Отменить", callback_data="back_to_menu")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    message,
                    reply_markup=reply_markup
                )
                return
            
            # Знайти користувача
            user_name, user_data = find_user_in_db(search_query, users_db)
            
            if not user_name:
                keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    f"❌ Пользователь '{search_query}' не найден!\n\n"
                    "Попробуйте:\n"
                    "• Полное имя (например: 'Ziuzin Oleksii')\n"
                    "• Email (например: 'o.ziuzin@evadav.com')\n"
                    "• Часть имени (например: 'Ziuzin')",
                    reply_markup=reply_markup
                )
                return
            
            # Відправити "завантаження..."
            status_msg = await update.message.reply_text(
                f"⏳ Загрузка данных для {user_name}..."
            )
            
            # Отримати дані за сьогодні
            yaware_client = YaWareV2Client()
            today = date.today()
            today_info = get_user_today_stats(user_name, user_data, yaware_client, today)
            
            # Форматувати повідомлення
            message = format_user_stats_message(user_name, user_data, today_info)
            
            # Додаємо кнопку "Назад"
            keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await status_msg.edit_text(message, reply_markup=reply_markup)
            
        except Exception as e:
            logger.error(f"User stats error: {e}", exc_info=True)
            keyboard = [[InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"⚠️ Ошибка получения данных\n\nError: {str(e)}",
                reply_markup=reply_markup
            )


async def handle_back_to_menu(query, context):
    """Повернутися до головного меню."""
    from tracker_alert.services import user_manager
    
    try:
        monitor = AttendanceMonitor()
        
        # Загальна кількість користувачів
        all_users_data = user_manager.load_users()
        total_user_count = len(all_users_data.get('users', {}))
        
        # Активні користувачі
        active_user_count = len(monitor.schedules)
        
        welcome_message = (
            "👋 Добро пожаловать в Eva_Control_Bot!\n\n"
            "Я помогаю отслеживать присутствие сотрудников.\n\n"
            f"📊 *СТАТИСТИКА:*\n"
            f"   • Всего пользователей в базе: *{total_user_count}*\n"
            f"   • Активных (с графиком): *{active_user_count}*\n\n"
            "Выберите действие из меню ниже:"
        )
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        welcome_message = (
            "👋 Добро пожаловать в Eva_Control_Bot!\n\n"
            "Я помогаю отслеживать присутствие сотрудников.\n\n"
            "Выберите действие из меню ниже:"
        )
    
    bot = context.bot_data.get('attendance_bot')
    sheet_url = bot.get_manager_sheet_url(query.message.chat_id) if bot else "https://docs.google.com/spreadsheets/d/1MAOpHjbOssn1hXR0RPnXjmYJaRbziqQud3TwMKc8jBs/edit#gid=0"
    keyboard = [
        [
            InlineKeyboardButton("📊 Отчет на сегодня", callback_data="report_today"),
            InlineKeyboardButton("👤 Статистика пользователя", callback_data="ask_user")
        ],
        [
            InlineKeyboardButton("❓ Справка", callback_data="help")
        ],
        [
            InlineKeyboardButton("📅 Отчет за вчера в Google Sheets", url=sheet_url)
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Відправляємо нове повідомлення замість редагування старого
    await query.message.reply_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Підтверджуємо callback
    await query.answer()


# ==================== ADMIN COMMANDS ====================

# Стани для conversation handler
(ADMIN_MENU, ADD_USER_NAME, ADD_USER_EMAIL, ADD_USER_ID, ADD_USER_LOCATION, ADD_USER_TIME,
 DELETE_USER_SEARCH, DELETE_USER_CONFIRM,
 EDIT_USER_SEARCH, EDIT_USER_FIELD, EDIT_USER_VALUE) = range(11)

# Імпорт функцій керування користувачами
from tracker_alert.services import user_manager


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Головне меню адміністратора (тільки для admin_chat_ids)."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    admin_ids = context.bot_data.get('admin_chat_ids', set())
    
    # Діагностика
    logger.info(f"🔍 Admin command: user_id={user_id}, chat_id={chat_id}, admin_ids={admin_ids}")
    
    # Перевірка: або user_id, або chat_id має бути в admin_ids
    if user_id not in admin_ids and chat_id not in admin_ids:
        await update.message.reply_text(
            f"❌ У вас нет прав администратора\n\n"
            f"Debug: user_id={user_id}, chat_id={chat_id}"
        )
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить пользователя", callback_data="admin_add_user")],
        [InlineKeyboardButton("🗑️ Удалить пользователя", callback_data="admin_delete_user")],
        [InlineKeyboardButton("✏️ Редактировать пользователя", callback_data="admin_edit_user")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔧 *ПАНЕЛЬ АДМИНИСТРАТОРА*\n\nВыберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ADMIN_MENU


# ==================== ДОБАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯ ====================

async def admin_add_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало добавления пользователя."""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(
        "➕ *ДОБАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯ*\n\n"
        "Введите полное имя пользователя (например: Ivanov Ivan):",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ADD_USER_NAME


async def admin_add_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить имя нового пользователя."""
    context.user_data['new_user_name'] = update.message.text.strip()
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Имя: *{context.user_data['new_user_name']}*\n\n"
        "Введите email пользователя:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ADD_USER_EMAIL


async def admin_add_user_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить email нового пользователя."""
    email = update.message.text.strip()
    
    if '@' not in email:
        await update.message.reply_text("❌ Неверный формат email. Попробуйте снова:")
        return ADD_USER_EMAIL
    
    context.user_data['new_user_email'] = email
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Email: *{email}*\n\n"
        "Введите ID пользователя (например: 7684922):",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ADD_USER_ID


async def admin_add_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить ID нового пользователя."""
    user_id = update.message.text.strip()
    context.user_data['new_user_id'] = user_id
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ ID: *{user_id}*\n\n"
        "Введите локацию (например: Ukraine, Philippines, India):",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ADD_USER_LOCATION


async def admin_add_user_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить локацию нового пользователя."""
    location = update.message.text.strip()
    context.user_data['new_user_location'] = location
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ Локация: *{location}*\n\n"
        "Введите время начала работы (формат HH:MM, например: 10:00):",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ADD_USER_TIME


async def admin_add_user_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить время начала и сохранить пользователя."""
    start_time = update.message.text.strip()
    
    # Перевірка формату часу
    if ':' not in start_time or len(start_time.split(':')) != 2:
        await update.message.reply_text("❌ Неверный формат времени. Используйте HH:MM (например: 10:00)")
        return ADD_USER_TIME
    
    # Додати користувача
    success, message = user_manager.add_user(
        name=context.user_data['new_user_name'],
        email=context.user_data['new_user_email'],
        user_id=context.user_data['new_user_id'],
        location=context.user_data['new_user_location'],
        start_time=start_time
    )
    
    # Очистити дані
    context.user_data.clear()
    
    keyboard = [[InlineKeyboardButton("◀️ В админ-панель", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup)
    
    return ConversationHandler.END


# ==================== УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ ====================

async def admin_delete_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало удаления пользователя."""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(
        "🗑️ *УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ*\n\n"
        "Введите имя или часть имени пользователя для поиска:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return DELETE_USER_SEARCH


async def admin_delete_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск пользователя для удаления."""
    query = update.message.text.strip()
    matches = user_manager.search_users(query)
    
    if not matches:
        await update.message.reply_text(
            f"❌ Пользователь '{query}' не найден.\n\nПопробуйте снова или /cancel для отмены:"
        )
        return DELETE_USER_SEARCH
    
    if len(matches) == 1:
        # Одно совпадение - сразу предлагаем удалить
        context.user_data['delete_user_name'] = matches[0]
        user_info = user_manager.get_user_info(matches[0])
        
        keyboard = [
            [InlineKeyboardButton("✅ Да, удалить", callback_data="admin_delete_confirm")],
            [InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🗑️ *ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ*\n\n"
            f"Имя: {matches[0]}\n"
            f"Email: {user_info.get('email', 'N/A')}\n"
            f"ID: {user_info.get('user_id', 'N/A')}\n"
            f"Локация: {user_info.get('location', 'N/A')}\n"
            f"График: {user_info.get('start_time', 'N/A')}\n\n"
            f"❗️ Вы уверены, что хотите удалить этого пользователя?",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return DELETE_USER_CONFIRM
    
    else:
        # Несколько совпадений - предлагаем выбрать
        keyboard = []
        for name in matches[:10]:  # Максимум 10 результатів
            keyboard.append([InlineKeyboardButton(name, callback_data=f"admin_delete_select:{name}")])
        keyboard.append([InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Найдено пользователей: {len(matches)}\n\nВыберите пользователя:",
            reply_markup=reply_markup
        )
        
        return DELETE_USER_SEARCH


async def admin_delete_user_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор пользователя из списка для удаления."""
    query = update.callback_query
    await query.answer()
    
    user_name = query.data.split(':', 1)[1]
    context.user_data['delete_user_name'] = user_name
    user_info = user_manager.get_user_info(user_name)
    
    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить", callback_data="admin_delete_confirm")],
        [InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(
        f"🗑️ *ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ*\n\n"
        f"Имя: {user_name}\n"
        f"Email: {user_info.get('email', 'N/A')}\n"
        f"ID: {user_info.get('user_id', 'N/A')}\n"
        f"Локация: {user_info.get('location', 'N/A')}\n"
        f"График: {user_info.get('start_time', 'N/A')}\n\n"
        f"❗️ Вы уверены, что хотите удалить этого пользователя?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return DELETE_USER_CONFIRM


async def admin_delete_user_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение и удаление пользователя."""
    query = update.callback_query
    await query.answer()
    
    user_name = context.user_data.get('delete_user_name')
    if not user_name:
        await query.message.reply_text("❌ Ошибка: пользователь не выбран")
        return ConversationHandler.END
    
    success, message = user_manager.delete_user(user_name)
    
    context.user_data.clear()
    
    keyboard = [[InlineKeyboardButton("◀️ В админ-панель", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(message, reply_markup=reply_markup)
    
    return ConversationHandler.END


# ==================== РЕДАКТИРОВАНИЕ ПОЛЬЗОВАТЕЛЯ ====================

async def admin_edit_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования пользователя."""
    query = update.callback_query
    await query.answer()
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(
        "✏️ *РЕДАКТИРОВАНИЕ ПОЛЬЗОВАТЕЛЯ*\n\n"
        "Введите имя или часть имени пользователя для поиска:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return EDIT_USER_SEARCH


async def admin_edit_user_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск пользователя для редактирования."""
    query = update.message.text.strip()
    matches = user_manager.search_users(query)
    
    if not matches:
        await update.message.reply_text(
            f"❌ Пользователь '{query}' не найден.\n\nПопробуйте снова или /cancel для отмены:"
        )
        return EDIT_USER_SEARCH
    
    if len(matches) == 1:
        # Одно совпадение - показываем поля для редактирования
        context.user_data['edit_user_name'] = matches[0]
        user_info = user_manager.get_user_info(matches[0])
        
        keyboard = [
            [InlineKeyboardButton("📧 Email", callback_data="admin_edit_field:email")],
            [InlineKeyboardButton("🆔 ID", callback_data="admin_edit_field:user_id")],
            [InlineKeyboardButton("🌍 Локация", callback_data="admin_edit_field:location")],
            [InlineKeyboardButton("⏰ Время начала", callback_data="admin_edit_field:start_time")],
            [InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✏️ *РЕДАКТИРОВАНИЕ: {matches[0]}*\n\n"
            f"📧 Email: `{user_info.get('email', 'N/A')}`\n"
            f"🆔 ID: `{user_info.get('user_id', 'N/A')}`\n"
            f"🌍 Локация: `{user_info.get('location', 'N/A')}`\n"
            f"⏰ График: `{user_info.get('start_time', 'N/A')}`\n\n"
            f"Выберите поле для изменения:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        return EDIT_USER_FIELD
    
    else:
        # Несколько совпадений - предлагаем выбрать
        keyboard = []
        for name in matches[:10]:
            keyboard.append([InlineKeyboardButton(name, callback_data=f"admin_edit_select:{name}")])
        keyboard.append([InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"Найдено пользователей: {len(matches)}\n\nВыберите пользователя:",
            reply_markup=reply_markup
        )
        
        return EDIT_USER_SEARCH


async def admin_edit_user_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор пользователя из списка для редактирования."""
    query = update.callback_query
    await query.answer()
    
    user_name = query.data.split(':', 1)[1]
    context.user_data['edit_user_name'] = user_name
    user_info = user_manager.get_user_info(user_name)
    
    keyboard = [
        [InlineKeyboardButton("📧 Email", callback_data="admin_edit_field:email")],
        [InlineKeyboardButton("🆔 ID", callback_data="admin_edit_field:user_id")],
        [InlineKeyboardButton("🌍 Локация", callback_data="admin_edit_field:location")],
        [InlineKeyboardButton("⏰ Время начала", callback_data="admin_edit_field:start_time")],
        [InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(
        f"✏️ *РЕДАКТИРОВАНИЕ: {user_name}*\n\n"
        f"📧 Email: `{user_info.get('email', 'N/A')}`\n"
        f"🆔 ID: `{user_info.get('user_id', 'N/A')}`\n"
        f"🌍 Локация: `{user_info.get('location', 'N/A')}`\n"
        f"⏰ График: `{user_info.get('start_time', 'N/A')}`\n\n"
        f"Выберите поле для изменения:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return EDIT_USER_FIELD


async def admin_edit_user_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор поля для редактирования."""
    query = update.callback_query
    await query.answer()
    
    field = query.data.split(':', 1)[1]
    context.user_data['edit_field'] = field
    
    field_names = {
        "email": "Email",
        "user_id": "ID",
        "location": "Локацию",
        "start_time": "Время начала (формат HH:MM)"
    }
    
    keyboard = [[InlineKeyboardButton("❌ Отменить", callback_data="admin_cancel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(
        f"✏️ Введите новое значение для *{field_names[field]}*:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return EDIT_USER_VALUE


async def admin_edit_user_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить новое значение и обновить."""
    new_value = update.message.text.strip()
    user_name = context.user_data.get('edit_user_name')
    field = context.user_data.get('edit_field')
    
    if not user_name or not field:
        await update.message.reply_text("❌ Ошибка: данные потеряны")
        return ConversationHandler.END
    
    # Валідація
    if field == 'email' and '@' not in new_value:
        await update.message.reply_text("❌ Неверный формат email. Попробуйте снова:")
        return EDIT_USER_VALUE
    
    if field == 'start_time' and ':' not in new_value:
        await update.message.reply_text("❌ Неверный формат времени. Используйте HH:MM (например: 10:00)")
        return EDIT_USER_VALUE
    
    # Оновити
    success, message = user_manager.update_user(user_name, field, new_value)
    
    context.user_data.clear()
    
    keyboard = [[InlineKeyboardButton("◀️ В админ-панель", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(message, reply_markup=reply_markup)
    
    return ConversationHandler.END


# ==================== ОБЩИЕ ФУНКЦИИ ====================

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена операции администратора."""
    query = update.callback_query
    await query.answer()
    
    context.user_data.clear()
    
    keyboard = [[InlineKeyboardButton("◀️ В админ-панель", callback_data="admin_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(
        "❌ Операция отменена",
        reply_markup=reply_markup
    )
    
    return ConversationHandler.END


async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повернутися в меню адміністратора."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    admin_ids = context.bot_data.get('admin_chat_ids', [])
    
    # Перевірка: або user_id, або chat_id має бути в admin_ids
    if user_id not in admin_ids and chat_id not in admin_ids:
        await query.message.reply_text("❌ У вас нет прав администратора")
        return ConversationHandler.END
    
    keyboard = [
        [InlineKeyboardButton("➕ Добавить пользователя", callback_data="admin_add_user")],
        [InlineKeyboardButton("🗑️ Удалить пользователя", callback_data="admin_delete_user")],
        [InlineKeyboardButton("✏️ Редактировать пользователя", callback_data="admin_edit_user")],
        [InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(
        "🔧 *ПАНЕЛЬ АДМИНИСТРАТОРА*\n\nВыберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ADMIN_MENU
