"""Scheduler for automated daily attendance reports."""
import logging
from datetime import datetime, time, timedelta
from typing import Optional

import asyncio
import pytz

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from tracker_alert.services.dashboard_report import DashboardReportService
from tracker_alert.services.report_formatter import format_attendance_report

logger = logging.getLogger(__name__)

DASHBOARD_URL = "https://dbrd.ctrlbot.website/"


class AttendanceScheduler:
    """Scheduler for automated attendance reports."""
    
    REPORT_TIMEZONE = "Europe/Warsaw"
    REPORT_TIME = time(10, 0)            # 10:00 Warsaw – основний звіт (після синків БД)
    MORNING_MESSAGE_TIME = time(9, 20)   # 09:20 Warsaw – ранкове нагадування
    
    def __init__(self, bot):
        """Initialize scheduler.
        
        Args:
            bot: AttendanceBot instance for sending messages
        """
        self.bot = bot
        self.report_service = DashboardReportService()
        self.scheduler: Optional[BackgroundScheduler] = None
    
    def _send_daily_report_sync(self) -> None:
        """Wrapper to run async send_daily_report in sync context."""
        try:
            asyncio.run(self.send_daily_report())
        except Exception as e:
            logger.error(f"Failed to run daily report: {e}")
    
    async def send_daily_report(self) -> None:
        """Generate and send daily attendance report to admins."""
        today = datetime.now(pytz.timezone(self.REPORT_TIMEZONE)).date()
        logger.info(f"Generating daily attendance report for {today}")
        try:
            base_report = self.report_service.get_daily_report(today)
            admin_ids = list(self.bot.admin_chat_ids) if self.bot.admin_chat_ids else []
            if not admin_ids:
                await self.bot.send_message_to_admins(format_attendance_report(base_report, today))
                logger.info("Daily report sent to default channel (no admins configured)")
                return

            for chat_id in admin_ids:
                allowed_managers = self.bot.get_allowed_managers(chat_id)
                report = self.report_service.filter_report_by_managers(base_report, allowed_managers)
                if report['late'] or report['absent']:
                    message = format_attendance_report(report, today)
                else:
                    message = (
                        f"✅ *Attendance Report - {today.strftime('%Y-%m-%d')}*\n\n"
                        "🎉 All employees are on time! No issues to report."
                    )
                try:
                    await self.bot.send_message(chat_id, message)
                except Exception as send_error:
                    logger.error(f"Failed to send daily report to chat {chat_id}: {send_error}")

            logger.info(f"Daily report sent to {len(admin_ids)} admin chats")

        except Exception as e:
            logger.error(f"Failed to send daily report: {e}")
            error_message = (
                "⚠️ *Daily Report Failed*\n\n"
                f"Error generating attendance report: {str(e)}"
            )
            for chat_id in self.bot.admin_chat_ids or []:
                try:
                    await self.bot.send_message(chat_id, error_message)
                except Exception as send_error:
                    logger.error(f"Failed to notify chat {chat_id} about error: {send_error}")
    
    def _send_morning_message_sync(self) -> None:
        """Wrapper для ранкового повідомлення."""
        try:
            asyncio.run(self.send_morning_message())
        except Exception as e:
            logger.error(f"Failed to send morning message: {e}", exc_info=True)
    
    async def send_morning_message(self) -> None:
        """Відправити ранкове повідомлення о 9:00."""
        today = datetime.now(pytz.timezone(self.REPORT_TIMEZONE)).date()
        weekday = today.weekday()
        
        # Субота та неділя - не відправляємо
        if weekday in [5, 6]:
            logger.info(f"⏭️  Skipping morning message on weekend: {today}")
            return
        
        # Визначаємо яку дату експортували
        if weekday == 0:  # Monday
            exported_date = today - timedelta(days=3)  # Friday
        else:
            exported_date = today - timedelta(days=1)  # Yesterday
        
        try:
            message = (
                f"☀️ Доброе утро!\n\n"
                f"📊 В нашу таблицу уже добавлена статистика за {exported_date.strftime('%d.%m.%Y')} ({exported_date.strftime('%A')}).\n\n"
                f"🔍 Начинаю собирать статистику по утренним опозданиям..."
            )
            
            # Використовуємо inline keyboard з посиланням
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            # Відправляємо в адмін чати
            if not self.bot.admin_chat_ids:
                logger.warning("No admin chat IDs configured")
                return
            
            for chat_id in self.bot.admin_chat_ids:
                reply_markup = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🌐 Открыть сайт", url=DASHBOARD_URL)],
                    [InlineKeyboardButton("📄 Сформировать отчет за сегодня", callback_data="report_today")]
                ])
                try:
                    await self.bot.application.bot.send_message(
                        chat_id=chat_id,
                        text=message,
                        reply_markup=reply_markup
                    )
                    logger.info(f"Morning message sent to chat {chat_id}")
                except Exception as e:
                    logger.error(f"Failed to send morning message to chat {chat_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to send morning message: {e}", exc_info=True)
    
    def start(self) -> None:
        """Start the scheduler."""
        if self.scheduler:
            logger.warning("Scheduler already running")
            return
        
        self.scheduler = BackgroundScheduler(timezone=self.REPORT_TIMEZONE)
        
        # Schedule daily Telegram report (Mon-Fri only)
        self.scheduler.add_job(
            self._send_daily_report_sync,
            trigger=CronTrigger(
                hour=self.REPORT_TIME.hour,
                minute=self.REPORT_TIME.minute,
                day_of_week='mon-fri',  # Тільки робочі дні
                timezone=pytz.timezone(self.REPORT_TIMEZONE)
            ),
            id='daily_attendance_report',
            name='Daily Attendance Report',
            replace_existing=True
        )
        
        # Schedule morning message at 09:00 Warsaw time (Mon-Fri)
        self.scheduler.add_job(
            self._send_morning_message_sync,
            trigger=CronTrigger(
                hour=self.MORNING_MESSAGE_TIME.hour,
                minute=self.MORNING_MESSAGE_TIME.minute,
                day_of_week='mon-fri',  # Тільки робочі дні
                timezone=pytz.timezone(self.REPORT_TIMEZONE)
            ),
            id='morning_message',
            name='Morning Message',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info(
            f"Scheduler started (timezone: {self.REPORT_TIMEZONE}):\n"
            f"  - {self.REPORT_TIME} - Telegram reports (Mon-Fri)\n"
            f"  - {self.MORNING_MESSAGE_TIME} - Morning reminder (Mon-Fri)"
        )
    
    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler:
            self.scheduler.shutdown()
            self.scheduler = None
            logger.info("Scheduler stopped")
