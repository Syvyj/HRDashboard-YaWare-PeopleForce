# dashboard_app/__init__.py
from __future__ import annotations
import os
from flask import Flask
from .extensions import db, login_manager
from .auth import auth_bp
from .views import views_bp
from .api import api_bp
from .admin import admin_bp
from .tasks import register_tasks               # залишаємо імпорт
from .models import ensure_schema

def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'static')
    )

    # --- базові налаштування ---
    secret_key = os.getenv('DASHBOARD_SECRET_KEY', 'change-this-secret')
    app.config['SECRET_KEY'] = secret_key
    app.secret_key = secret_key

    app.config.setdefault('SQLALCHEMY_DATABASE_URI',
                          os.getenv('DASHBOARD_DATABASE_URL', 'sqlite:///dashboard.db'))
    app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
    # вмикаємо scheduler лише якщо ENABLE_SCHEDULER=1
    app.config.setdefault('ENABLE_SCHEDULER', os.getenv('ENABLE_SCHEDULER', '0') == '1')

    # --- ініціалізація розширень ---
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # --- реєстрація blueprints ---
    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(admin_bp)

    # --- робота з БД + (опційно) запуск APScheduler ---
    with app.app_context():
        db.create_all()
        ensure_schema()

        if app.config['ENABLE_SCHEDULER']:
            from apscheduler.schedulers.background import BackgroundScheduler
            tz = os.getenv('TZ', 'Europe/Warsaw')
            scheduler = BackgroundScheduler(timezone=tz)

            # НОВА сигнатура: передаємо і app, і scheduler
            register_tasks(app)
            scheduler.start()
            print(f"[scheduler] started (timezone={tz})")

    return app
