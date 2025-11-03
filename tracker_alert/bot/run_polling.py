import logging
from telegram.ext import ApplicationBuilder, CommandHandler
from tracker_alert.config.settings import Settings

logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)

settings = Settings()

# Базова перевірка
async def ping(update, context):
    await update.message.reply_text("✅ Bot is alive")

def build_app():
    # Якщо в твоєму tracker_alert/bot/telegram_bot.py вже є фабрика застосунку — використаймо її
    try:
        from tracker_alert.bot.telegram_bot import build_app as native_build_app  # типова назва
        app = native_build_app()
        # і все ж додамо /ping на всяк випадок
        app.add_handler(CommandHandler("ping", ping))
        logging.info("Loaded application via telegram_bot.build_app()")
        return app
    except Exception as e:
        logging.warning("No native build_app() in telegram_bot or failed to load: %s", e)

    # Інакше зберемо застосунок вручну і підключимо твої хендлери
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("ping", ping))

    # Підключаємо commands.py
    try:
        from tracker_alert.bot.handlers import commands as hcmd
        if hasattr(hcmd, "register"):
            hcmd.register(app)  # якщо у тебе є централізована реєстрація
            logging.info("handlers.commands.register(app) applied")
        else:
            # Авто-додавання поширених команд, якщо функції існують
            for name in ("start", "help", "stats", "admin", "report"):
                if hasattr(hcmd, name):
                    app.add_handler(CommandHandler(name, getattr(hcmd, name)))
            logging.info("handlers.commands.* auto-registered (start/help/stats/admin/report if present)")
    except Exception as e:
        logging.warning("Could not import/register handlers.commands: %s", e)

    # Опційно: callbacks.py (якщо є)
    try:
        from tracker_alert.bot.handlers import callbacks as cb
        if hasattr(cb, "register"):
            cb.register(app)
            logging.info("handlers.callbacks.register(app) applied")
    except Exception:
        pass

    return app

def main():
    app = build_app()
    app.run_polling(allowed_updates=None, close_loop=False)

if __name__ == "__main__":
    main()
