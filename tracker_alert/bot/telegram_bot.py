"""Telegram bot for attendance monitoring."""
import logging
from typing import Optional, Dict, List
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, ConversationHandler, filters, ContextTypes
)

from tracker_alert.config.settings import Settings

logger = logging.getLogger(__name__)


class AttendanceBot:
    """Telegram bot for monitoring employee attendance."""
    
    def __init__(self, settings: Optional[Settings] = None):
        """Initialize the bot with settings.
        
        Args:
            settings: Application settings (creates new if not provided)
        """
        self.settings = settings or Settings()
        
        if not self.settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN must be set in environment or .env file")
        
        # Parse admin chat IDs
        self.admin_chat_ids = set()
        logger.info(f"🔧 Loading admin IDs from: {self.settings.telegram_admin_chat_ids}")
        if self.settings.telegram_admin_chat_ids:
            self.admin_chat_ids = {
                int(chat_id.strip()) 
                for chat_id in self.settings.telegram_admin_chat_ids.split(',')
                if chat_id.strip()
            }
            logger.info(f"✅ Loaded admin IDs: {self.admin_chat_ids}")
        else:
            logger.warning("⚠️ No TELEGRAM_ADMIN_CHAT_IDS found in .env!")
        
        self.manager_access: Dict[int, List[int]] = {}
        if self.settings.telegram_manager_mapping:
            for item in self.settings.telegram_manager_mapping.split(','):
                item = item.strip()
                if not item or ':' not in item:
                    continue
                chat_part, managers_part = item.split(':', 1)
                try:
                    chat_id = int(chat_part.strip())
                except ValueError:
                    logger.warning(f"Невірний chat_id у TELEGRAM_MANAGER_MAPPING: {chat_part}")
                    continue
                managers = []
                for value in managers_part.replace(';', '|').split('|'):
                    value = value.strip()
                    if not value:
                        continue
                    try:
                        managers.append(int(value))
                    except ValueError:
                        logger.warning(f"Невірний manager id у TELEGRAM_MANAGER_MAPPING для chat {chat_part}: {value}")
                if managers:
                    self.manager_access[chat_id] = managers
        if self.manager_access:
            logger.info(f"✅ Manager mapping loaded: {self.manager_access}")

        self.application: Optional[Application] = None
    
    def is_admin(self, chat_id: int) -> bool:
        """Check if chat_id is authorized admin.
        
        Args:
            chat_id: Telegram chat ID to check
            
        Returns:
            True if chat_id is in admin list or no admins configured
        """
        # If no admins configured, allow all (for development)
        if not self.admin_chat_ids:
            logger.warning("No admin chat IDs configured - allowing all users")
            return True
        return chat_id in self.admin_chat_ids

    def get_allowed_managers(self, chat_id: int) -> Optional[List[int]]:
        """Отримати список контроль‑менеджерів доступних для чатa."""
        return self.manager_access.get(chat_id)
    
    def build_application(self) -> Application:
        """Build and configure the Telegram application.
        
        Returns:
            Configured Application instance
        """
        # Import handlers here to avoid circular imports
        from tracker_alert.bot.handlers.commands import (
            start_command,
            help_command,
            status_command,
            report_today_command,
            user_command,
            button_callback,
            handle_text_message,
            # Admin handlers
            admin_command,
            admin_add_user_start,
            admin_add_user_name,
            admin_add_user_email,
            admin_add_user_id,
            admin_add_user_location,
            admin_add_user_time,
            admin_delete_user_start,
            admin_delete_user_search,
            admin_delete_user_select,
            admin_delete_user_confirm,
            admin_edit_user_start,
            admin_edit_user_search,
            admin_edit_user_select,
            admin_edit_user_field,
            admin_edit_user_value,
            admin_cancel,
            admin_menu_callback,
            # States
            ADMIN_MENU, ADD_USER_NAME, ADD_USER_EMAIL, ADD_USER_ID, ADD_USER_LOCATION, ADD_USER_TIME,
            DELETE_USER_SEARCH, DELETE_USER_CONFIRM,
            EDIT_USER_SEARCH, EDIT_USER_FIELD, EDIT_USER_VALUE
        )
        
        # Create application
        application = Application.builder().token(self.settings.telegram_bot_token).build()
        
        # Admin conversation handler
        admin_conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("admin", admin_command),
                CallbackQueryHandler(admin_menu_callback, pattern="^admin_menu$")
            ],
            states={
                ADMIN_MENU: [
                    CallbackQueryHandler(admin_add_user_start, pattern="^admin_add_user$"),
                    CallbackQueryHandler(admin_delete_user_start, pattern="^admin_delete_user$"),
                    CallbackQueryHandler(admin_edit_user_start, pattern="^admin_edit_user$"),
                ],
                ADD_USER_NAME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user_name),
                    CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
                ],
                ADD_USER_EMAIL: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user_email),
                    CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
                ],
                ADD_USER_ID: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user_id),
                    CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
                ],
                ADD_USER_LOCATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user_location),
                    CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
                ],
                ADD_USER_TIME: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_user_time),
                    CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
                ],
                DELETE_USER_SEARCH: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_delete_user_search),
                    CallbackQueryHandler(admin_delete_user_select, pattern="^admin_delete_select:"),
                    CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
                ],
                DELETE_USER_CONFIRM: [
                    CallbackQueryHandler(admin_delete_user_confirm, pattern="^admin_delete_confirm$"),
                    CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
                ],
                EDIT_USER_SEARCH: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_user_search),
                    CallbackQueryHandler(admin_edit_user_select, pattern="^admin_edit_select:"),
                    CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
                ],
                EDIT_USER_FIELD: [
                    CallbackQueryHandler(admin_edit_user_field, pattern="^admin_edit_field:"),
                    CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
                ],
                EDIT_USER_VALUE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_user_value),
                    CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
                ],
            },
            fallbacks=[
                CommandHandler("cancel", admin_cancel),
                CallbackQueryHandler(admin_cancel, pattern="^admin_cancel$")
            ],
            allow_reentry=True
        )
        
        # Register command handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("report_today", report_today_command))
        application.add_handler(CommandHandler("user", user_command))
        
        # Register admin conversation handler
        application.add_handler(admin_conv_handler)
        
        # Register callback query handler (для inline кнопок)
        application.add_handler(CallbackQueryHandler(button_callback))
        
        # Register text message handler (для діалогів)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
        
        # Store bot instance in application context for handlers to access
        application.bot_data['attendance_bot'] = self
        # Store admin IDs in bot_data for handlers to access
        application.bot_data['admin_chat_ids'] = self.admin_chat_ids
        
        self.application = application
        return application
    
    async def send_message_to_admins(self, message: str, parse_mode: str = "Markdown") -> None:
        """Send message to all admin chats.
        
        Args:
            message: Message text to send
            parse_mode: Telegram parse mode (Markdown or HTML)
        """
        if not self.application:
            raise RuntimeError("Application not initialized. Call build_application() first.")
        
        if not self.admin_chat_ids:
            logger.warning("No admin chat IDs configured - cannot send message")
            return
        
        # Разбиваем длинное сообщение на части
        from tracker_alert.services.report_formatter import split_message
        parts = split_message(message)
        
        for chat_id in self.admin_chat_ids:
            try:
                for part in parts:
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=part,
                        parse_mode=parse_mode
                    )
                logger.info(f"Message sent to admin chat {chat_id}")
            except Exception as e:
                logger.error(f"Failed to send message to chat {chat_id}: {e}")

    async def send_message(self, chat_id: int, message: str, parse_mode: str = "Markdown") -> None:
        if not self.application:
            raise RuntimeError("Application not initialized. Call build_application() first.")
        
        # Разбиваем длинное сообщение на части
        from tracker_alert.services.report_formatter import split_message
        parts = split_message(message)
        
        for part in parts:
            await self.application.bot.send_message(
                chat_id=chat_id,
                text=part,
                parse_mode=parse_mode
            )

    def get_manager_sheet_url(self, chat_id: int) -> str:
        """Повернути посилання на Google Sheet відповідно до менеджера."""
        manager_ids = self.get_allowed_managers(chat_id) or []
        if 1 in manager_ids and not 2 in manager_ids:
            return f"https://docs.google.com/spreadsheets/d/{self.settings.spreadsheet_id_control_1}/edit#gid=0"
        if 2 in manager_ids and not 1 in manager_ids:
            return f"https://docs.google.com/spreadsheets/d/{self.settings.spreadsheet_id_control_2}/edit#gid=0"
        # Якщо доступ до кількох менеджерів або немає мапінгу - основна таблиця
        return f"https://docs.google.com/spreadsheets/d/{self.settings.spreadsheet_id}/edit#gid=0"
    
    def run(self) -> None:
        """Run the bot."""
        if not self.application:
            self.build_application()
        
        logger.info("Starting attendance bot...")
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)
