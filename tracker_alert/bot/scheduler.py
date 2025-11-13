"""Scheduler for automated daily attendance reports."""
import logging
import os
from datetime import datetime, time, timedelta, date as date_type
from pathlib import Path
from typing import Optional

import asyncio
import pytz
import subprocess
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from tracker_alert.config.settings import settings
from tracker_alert.services.attendance_monitor import AttendanceMonitor
from tracker_alert.services.report_formatter import format_attendance_report
from tracker_alert.client.peopleforce_api import PeopleForceClient

logger = logging.getLogger(__name__)


class AttendanceScheduler:
    """Scheduler for automated attendance reports."""
    
    # Report time in Warsaw timezone
    REPORT_TIME = time(10, 0)      # 10:00 - Telegram звіт
    EXPORT_TIME = time(8, 0)       # 08:00 - Експорт в Google Sheets
    MORNING_MESSAGE_TIME = time(9, 0)  # 09:00 - Ранкове повідомлення
    REPORT_TIMEZONE = "Europe/Warsaw"
    DEFAULT_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{settings.spreadsheet_id}"
    MANAGER_SHEET_URLS = {
        1: f"https://docs.google.com/spreadsheets/d/{settings.spreadsheet_id_control_1}",
        2: f"https://docs.google.com/spreadsheets/d/{settings.spreadsheet_id_control_2}",
    }
    
    def __init__(self, bot):
        """Initialize scheduler.
        
        Args:
            bot: AttendanceBot instance for sending messages
        """
        self.bot = bot
        self.monitor = AttendanceMonitor()
        self.scheduler: Optional[BackgroundScheduler] = None
    
    def _send_daily_report_sync(self) -> None:
        """Wrapper to run async send_daily_report in sync context."""
        try:
            asyncio.run(self.send_daily_report())
        except Exception as e:
            logger.error(f"Failed to run daily report: {e}")
    
    async def send_daily_report(self) -> None:
        """Generate and send daily attendance report to admins."""
        try:
            today = datetime.now().date()
            logger.info(f"Generating daily attendance report for {today}")
            
            # Отримуємо дані про відпустки з PeopleForce
            leaves_list = []
            try:
                from tracker_alert.client.peopleforce_api import PeopleForceClient
                pf_client = PeopleForceClient()
                all_leaves = pf_client.get_leave_requests(start_date=today, end_date=today)
                leaves_list = all_leaves or []
                logger.debug(f"Fetched {len(leaves_list)} leave requests for {today}")
            except Exception as e:
                logger.warning(f"Failed to fetch leaves from PeopleForce: {e}")
            
            # Generate report
            report = self.monitor.get_daily_report(today)
            admin_ids = list(self.bot.admin_chat_ids) if self.bot.admin_chat_ids else []
            if not admin_ids:
                message = format_attendance_report(report, today, leaves_list=leaves_list)
                await self.bot.send_message_to_admins(message)
                logger.info("Daily report sent to default channel (no admins configured)")
                return

            for chat_id in admin_ids:
                allowed_managers = self.bot.get_allowed_managers(chat_id)
                filtered_report, filtered_leaves = self.monitor.filter_report_by_managers(report, allowed_managers, leaves_list)
                if filtered_report['late'] or filtered_report['absent'] or filtered_leaves:
                    message = format_attendance_report(filtered_report, today, leaves_list=filtered_leaves)
                else:
                    message = (
                        f"✅ *Attendance Report - {today.strftime('%Y-%m-%d')}*\n\n"
                        "🎉 All employees are on time! No issues to report."
                    )
                try:
                    await self.bot.send_message(chat_id, message)
                except Exception as send_error:
                    logger.error(f"Failed to send daily report to chat {chat_id}: {send_error}")
            logger.info(f"Daily report prepared for {len(admin_ids)} admin chats")

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
    
    def _export_to_sheets_sync(self) -> None:
        """Wrapper для експорту в Google Sheets."""
        try:
            self.export_to_sheets()
        except Exception as e:
            logger.error(f"Failed to export to sheets: {e}", exc_info=True)
    
    def export_to_sheets(self) -> None:
        """Експортувати дані в Google Sheets о 8:00."""
        today = datetime.now(pytz.timezone(self.REPORT_TIMEZONE)).date()
        weekday = today.weekday()  # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday
        
        # Субота та неділя - не експортуємо
        if weekday in [5, 6]:  # Saturday or Sunday
            logger.info(f"⏭️  Skipping export on weekend: {today} ({today.strftime('%A')})")
            return
        
        # Визначаємо дату для експорту
        if weekday == 0:  # Monday
            # Експортуємо п'ятницю минулого тижня
            export_date = today - timedelta(days=3)  # Friday
            logger.info(f"📅 Monday detected: exporting last Friday ({export_date})")
        else:
            # Експортуємо вчорашній день
            export_date = today - timedelta(days=1)
            logger.info(f"📅 Exporting yesterday: {export_date}")
        
        try:
            # Запускаємо export_weekly.py як subprocess
            logger.info(f"🚀 Starting export for {export_date}...")
            
            env = os.environ.copy()
            project_root = Path(__file__).resolve().parents[2]
            existing_path = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                f"{project_root}{os.pathsep}{existing_path}"
                if existing_path
                else str(project_root)
            )
            result = subprocess.run(
                [sys.executable, "-m", "tracker_alert.scripts.export_weekly", str(export_date)],
                capture_output=True,
                text=True,
                timeout=300,  # 5 хвилин timeout
                env=env,
                cwd=project_root,
            )
            
            if result.returncode == 0:
                logger.info(f"✅ Export completed successfully for {export_date}")
                logger.info(f"Output: {result.stdout}")
            else:
                logger.error(f"❌ Export failed for {export_date}")
                logger.error(f"Error: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Export timeout for {export_date} (exceeded 5 minutes)")
        except Exception as e:
            logger.error(f"❌ Export error for {export_date}: {e}", exc_info=True)
    
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
                button_url = self._resolve_sheet_url(chat_id)
                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📅 Открыть таблицу", url=button_url)]]
                )
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

    def _resolve_sheet_url(self, chat_id: int) -> str:
        """Підібрати Google Sheet для конкретного чату з урахуванням доступів."""
        allowed_managers = self.bot.get_allowed_managers(chat_id) or []
        if len(allowed_managers) == 1:
            manager_id = allowed_managers[0]
            sheet_url = self.MANAGER_SHEET_URLS.get(manager_id)
            if sheet_url:
                return sheet_url
        return self.DEFAULT_SHEET_URL
    
    def start(self) -> None:
        """Start the scheduler."""
        if self.scheduler:
            logger.warning("Scheduler already running")
            return
        
        self.scheduler = BackgroundScheduler(timezone=self.REPORT_TIMEZONE)
        
        # Schedule daily Telegram report at 10:00 Warsaw time
        self.scheduler.add_job(
            self._send_daily_report_sync,
            trigger=CronTrigger(
                hour=self.REPORT_TIME.hour,
                minute=self.REPORT_TIME.minute,
                timezone=pytz.timezone(self.REPORT_TIMEZONE)
            ),
            id='daily_attendance_report',
            name='Daily Attendance Report',
            replace_existing=True
        )
        
        # Schedule daily Google Sheets export at 08:00 Warsaw time (Mon-Fri)
        self.scheduler.add_job(
            self._export_to_sheets_sync,
            trigger=CronTrigger(
                hour=self.EXPORT_TIME.hour,
                minute=self.EXPORT_TIME.minute,
                day_of_week='mon-fri',  # Тільки робочі дні
                timezone=pytz.timezone(self.REPORT_TIMEZONE)
            ),
            id='daily_sheets_export',
            name='Daily Google Sheets Export',
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
            f"Scheduler started:\n"
            f"  - Sheets export: {self.EXPORT_TIME.strftime('%H:%M')} {self.REPORT_TIMEZONE} (Mon-Fri)\n"
            f"  - Morning message: {self.MORNING_MESSAGE_TIME.strftime('%H:%M')} {self.REPORT_TIMEZONE} (Mon-Fri)\n"
            f"  - Telegram reports: {self.REPORT_TIME.strftime('%H:%M')} {self.REPORT_TIMEZONE}"
        )
    
    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler:
            self.scheduler.shutdown()
            self.scheduler = None
            logger.info("Scheduler stopped")
