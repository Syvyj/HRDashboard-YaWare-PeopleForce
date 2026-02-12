"""Scheduler for automated daily attendance reports."""
import logging
from datetime import datetime, time
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
    """Scheduler for automated attendance reports.
    
    Звіт «ОТЧЕТ ПО ОПОЗДАНИЯМ» — це звіт про запізнення **сьогодні** на роботу. О 10:00 на сайті
    запускається лише синхронізація запізнень з YaWare (collect_lateness_for_date → lateness_records),
    потім бот о 10:02 формує звіт з lateness_records і відправляє в чат. Якщо запізнень/відсутностей
    немає — бот нічого не відправляє.
    На сервері має бути ENABLE_SCHEDULER=1.
    """
    
    REPORT_TIMEZONE = "Europe/Warsaw"
    REPORT_TIME_FULL = time(10, 2)  # 10:02 Warsaw – повний звіт «ОТЧЕТ ПО ОПОЗДАНИЯМ» (після синку сьогодні о 10:00)
    REPORT_TIME_SHORT = time(9, 32)  # 09:32 Warsaw – коротке повідомлення з кнопкою на дашборд
    
    def __init__(self, bot):
        """Initialize scheduler.
        
        Args:
            bot: AttendanceBot instance for sending messages
        """
        self.bot = bot
        self.report_service = DashboardReportService()
        self.scheduler: Optional[BackgroundScheduler] = None
    
    def _send_full_report_sync(self) -> None:
        """Wrapper to run async send_full_report in sync context."""
        try:
            asyncio.run(self.send_full_report())
        except Exception as e:
            logger.error(f"Failed to run full report: {e}")
    
    async def send_full_report(self) -> None:
        """Звіт про запізнення сьогодні на роботу. Дані з lateness_records (синк запізнень о 10:00 на сайті). Якщо немає запізнень/відсутностей — нічого не відправляємо."""
        today = datetime.now(pytz.timezone(self.REPORT_TIMEZONE)).date()
        logger.info(f"Generating full attendance report for {today} (from lateness_records)")
        try:
            base_report = self.report_service.get_daily_report(today, from_lateness=True)
            if base_report.get("total_issues", 0) == 0:
                logger.info("No late/absent today — skipping full report")
                return
            message = format_attendance_report(base_report, today)
            await self.bot.send_message_to_admins(message, parse_mode="Markdown")
            logger.info("Full report sent to admin chats")
        except Exception as e:
            logger.error(f"Failed to send full report: {e}")
            error_message = (
                "⚠️ *Daily Report Failed*\n\n"
                f"Error generating attendance report: {str(e)}"
            )
            for chat_id in self.bot.admin_chat_ids or []:
                try:
                    await self.bot.send_message(chat_id, error_message)
                except Exception as send_error:
                    logger.error(f"Failed to notify chat {chat_id} about error: {send_error}")
    
    def _send_short_report_sync(self) -> None:
        """Wrapper to run async send_short_report in sync context."""
        try:
            asyncio.run(self.send_short_report())
        except Exception as e:
            logger.error(f"Failed to run short report: {e}")
    
    async def send_short_report(self) -> None:
        """Надіслати коротке повідомлення з кнопкою на дашборд (09:32). Без посилання в тексті."""
        today = datetime.now(pytz.timezone(self.REPORT_TIMEZONE)).date()
        if not self.bot.admin_chat_ids:
            logger.warning("No admin chat IDs configured for short report")
            return
        message = (
            f"📊 Отчет посещаемости за {today.strftime('%d.%m.%Y')}\n\n"
            "Данные собраны и доступны на дашборде."
        )
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Открыть дашборд", url=DASHBOARD_URL)]
        ])
        for chat_id in self.bot.admin_chat_ids:
            try:
                await self.bot.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Failed to send short report to chat {chat_id}: {e}")
        logger.info("Short report (with dashboard button) sent to admin chats")
    
    def start(self) -> None:
        """Start the scheduler."""
        if self.scheduler:
            logger.warning("Scheduler already running")
            return
        
        self.scheduler = BackgroundScheduler(timezone=self.REPORT_TIMEZONE)
        
        # 10:02 Warsaw – повний звіт «ОТЧЕТ ПО ОПОЗДАНИЯМ» (Mon–Fri), тільки якщо є запізнення/відсутні
        self.scheduler.add_job(
            self._send_full_report_sync,
            trigger=CronTrigger(
                hour=self.REPORT_TIME_FULL.hour,
                minute=self.REPORT_TIME_FULL.minute,
                day_of_week='mon-fri',
                timezone=pytz.timezone(self.REPORT_TIMEZONE)
            ),
            id='daily_full_report',
            name='Full attendance report (ОТЧЕТ ПО ОПОЗДАНИЯМ)',
            replace_existing=True
        )
        
        # 09:32 Warsaw – коротке повідомлення з кнопкою на дашборд (Mon–Fri)
        self.scheduler.add_job(
            self._send_short_report_sync,
            trigger=CronTrigger(
                hour=self.REPORT_TIME_SHORT.hour,
                minute=self.REPORT_TIME_SHORT.minute,
                day_of_week='mon-fri',
                timezone=pytz.timezone(self.REPORT_TIMEZONE)
            ),
            id='daily_short_report',
            name='Short report with dashboard button',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info(
            f"Scheduler started (timezone: {self.REPORT_TIMEZONE}):\n"
            f"  - {self.REPORT_TIME_FULL} - Full report ОТЧЕТ ПО ОПОЗДАНИЯМ (Mon-Fri)\n"
            f"  - {self.REPORT_TIME_SHORT} - Short report + dashboard button (Mon-Fri)"
        )
    
    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler:
            self.scheduler.shutdown()
            self.scheduler = None
            logger.info("Scheduler stopped")
