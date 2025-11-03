from __future__ import annotations
import os
from flask import Flask
from .extensions import db, login_manager
from .auth import auth_bp
from .views import views_bp
from .api import api_bp
from .admin import admin_bp
from .tasks import register_tasks
from .models import ensure_schema


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'static')
    )

    secret_key = os.getenv('DASHBOARD_SECRET_KEY', 'change-this-secret')
    app.config['SECRET_KEY'] = secret_key
    app.secret_key = secret_key
    app.config.setdefault('SQLALCHEMY_DATABASE_URI', os.getenv('DASHBOARD_DATABASE_URL', 'sqlite:///dashboard.db'))
    app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
    app.config.setdefault('ENABLE_SCHEDULER', os.getenv('ENABLE_SCHEDULER', '0') == '1')

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(admin_bp)

    with app.app_context():
        db.create_all()
        ensure_schema()
        register_tasks(app)

    return app
