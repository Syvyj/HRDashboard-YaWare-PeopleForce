"""Run the attendance monitoring Telegram bot."""
import asyncio
import logging
import signal
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracker_alert.bot.telegram_bot import AttendanceBot
from tracker_alert.bot.scheduler import AttendanceScheduler
from tracker_alert.config.settings import Settings

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """Run the attendance bot with scheduler."""
    try:
        # Initialize settings
        settings = Settings()
        
        # Create bot
        bot = AttendanceBot(settings)
        application = bot.build_application()
        
        # Create scheduler (will be started when bot starts)
        scheduler = AttendanceScheduler(bot)
        
        # Setup graceful shutdown
        def shutdown_handler(signum, frame):
            logger.info("Shutdown signal received")
            if scheduler.scheduler:
                scheduler.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)
        
        # Run bot
        logger.info("Starting Attendance Monitoring Bot")
        logger.info(f"Admin chats: {settings.telegram_admin_chat_ids or 'None (dev mode)'}")
        logger.info(f"Scheduled reports: Daily at 10:00 Warsaw time")
        
        # Start scheduler
        scheduler.start()
        logger.info("✅ Scheduler started")
        
        # Run bot (blocking)
        bot.run()
        
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.error("Please ensure TELEGRAM_BOT_TOKEN is set in .env file")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
