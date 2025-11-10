from __future__ import annotations
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from dashboard_app.user_data import get_user_schedule
from urllib.parse import unquote

views_bp = Blueprint('views', __name__)


@views_bp.route('/')
@login_required
def dashboard():
    today = date.today()
    yesterday = today - timedelta(days=1)
    now = datetime.now()
    can_edit = getattr(current_user, 'is_admin', False) or getattr(current_user, 'is_control_manager', False)
    return render_template(
        'dashboard.html',
        user_name=current_user.name,
        is_admin=getattr(current_user, 'is_admin', False),
        can_edit=can_edit,
        stats_date=yesterday.strftime('%d.%m.%Y'),
        current_time=now.strftime('%H:%M'),
        current_date=now.strftime('%d.%m.%Y')
    )


@views_bp.route('/users/<path:user_key>')
@login_required
def user_detail(user_key: str):
    decoded_key = unquote(user_key)
    schedule = get_user_schedule(decoded_key)
    if not schedule and current_user.allowed_managers is not None:
        # якщо немає графіка і користувач без адмін прав — відмовити
        abort(404)
    display_name = schedule.get('name') if schedule else decoded_key
    is_admin = getattr(current_user, 'is_admin', False)
    return render_template(
        'user_detail.html',
        user_key=decoded_key,
        schedule=schedule,
        display_name=display_name,
        user_name=current_user.name,
        is_admin='1' if is_admin else '0'
    )
