"""Minimal command handlers for the Telegram bot."""
from __future__ import annotations

import logging
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CallbackQueryHandler

from tracker_alert.services.report_formatter import format_attendance_report

logger = logging.getLogger(__name__)

DASHBOARD_URL = "https://dbrd.ctrlbot.website/"


def _get_report_service(context: ContextTypes.DEFAULT_TYPE):
    service = context.application.bot_data.get('report_service')
    if not service:
        raise RuntimeError("Report service is not initialized")
    return service


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simple greeting with a link to the dashboard."""
    bot = context.bot_data.get('attendance_bot')
    chat_id = update.effective_chat.id

    if not bot or not bot.is_admin(chat_id):
        await update.effective_message.reply_text("⛔ Доступ заборонено.")
        return

    message = (
        "👋 Привіт! Я надсилаю ранкові звіти про запізнення.\n\n"
        "Перейди на сайт, щоб побачити повну статистику "
        "або натисни /report_today для повторного звіту."
    )
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Відкрити сайт", url=DASHBOARD_URL)]])
    await update.effective_message.reply_text(message, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Describe available commands."""
    bot = context.bot_data.get('attendance_bot')
    chat_id = update.effective_chat.id
    if not bot or not bot.is_admin(chat_id):
        await update.effective_message.reply_text("⛔ Доступ заборонено.")
        return

    await update.effective_message.reply_text(
        "Доступні команди:\n"
        "• /report_today – сформувати звіт за сьогодні\n"
        "• /start – посилання на сайт\n"
        "• /help – ця підказка"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return scheduler info."""
    bot = context.bot_data.get('attendance_bot')
    chat_id = update.effective_chat.id
    if not bot or not bot.is_admin(chat_id):
        await update.effective_message.reply_text("⛔ Доступ заборонено.")
        return

    await update.effective_message.reply_text("✅ Бот працює. Ранкове повідомлення о 09:20, щоденний звіт о 10:00 (Warsaw).")


async def report_today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate report for today on demand."""
    bot = context.bot_data.get('attendance_bot')
    chat_id = update.effective_chat.id

    if not bot or not bot.is_admin(chat_id):
        await update.effective_message.reply_text("⛔ Доступ заборонено.")
        return

    service = _get_report_service(context)
    target_date = date.today()

    try:
        await update.effective_message.reply_text("⏳ Генерую звіт ...")
        report = service.get_daily_report(target_date)
        allowed = bot.get_allowed_managers(chat_id)
        report = service.filter_report_by_managers(report, allowed)
        if report['late'] or report['absent']:
            message = format_attendance_report(report, target_date)
        else:
            message = (
                f"✅ *Attendance Report - {target_date.strftime('%Y-%m-%d')}*\n\n"
                "🎉 Всі співробітники вчасно!"
            )
        await update.effective_message.reply_text(message, parse_mode="Markdown")
    except Exception as exc:
        logger.error("Manual report failed: %s", exc, exc_info=True)
        await update.effective_message.reply_text("⚠️ Не вдалося згенерувати звіт. Перевірте логи.")


async def report_today_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline button handler to generate today's report."""
    query = update.callback_query
    if not query:
        return
    bot = context.bot_data.get('attendance_bot')
    chat_id = query.message.chat_id if query.message else None
    await query.answer()
    if not bot or not chat_id or not bot.is_admin(chat_id):
        await query.edit_message_text("⛔ Доступ заборонено.")
        return
    service = _get_report_service(context)
    target_date = date.today()
    try:
        await query.edit_message_text("⏳ Генерую звіт ...")
        report = service.get_daily_report(target_date)
        allowed = bot.get_allowed_managers(chat_id)
        report = service.filter_report_by_managers(report, allowed)
        if report['late'] or report['absent']:
            message = format_attendance_report(report, target_date)
        else:
            message = (
                f"✅ *Attendance Report - {target_date.strftime('%Y-%m-%d')}*\n\n"
                "🎉 Всі співробітники вчасно!"
            )
        await query.edit_message_text(message, parse_mode="Markdown")
    except Exception as exc:
        logger.error("Manual report callback failed: %s", exc, exc_info=True)
        await query.edit_message_text("⚠️ Не вдалося згенерувати звіт. Перевірте логи.")
