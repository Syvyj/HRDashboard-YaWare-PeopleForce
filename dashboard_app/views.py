from __future__ import annotations
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from dashboard_app.user_data import get_user_schedule
from urllib.parse import unquote

views_bp = Blueprint('views', __name__)


def _parse_manager_ids(manager_filter: str | None) -> list[int]:
    if not manager_filter:
        return []
    result: list[int] = []
    for value in manager_filter.split(','):
        value = value.strip()
        if not value:
            continue
        try:
            result.append(int(value))
        except ValueError:
            continue
    return result


def _can_delete_any_presets(user) -> bool:
    if getattr(user, 'is_admin', False):
        return True
    if not getattr(user, 'is_control_manager', False):
        return False
    return _parse_manager_ids(getattr(user, 'manager_filter', None)) == [3]


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
        can_manage_presets=can_edit,
        can_delete_any_presets=_can_delete_any_presets(current_user),
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
    body_user_key = (schedule.get('email') if schedule else None) or decoded_key
    is_admin = getattr(current_user, 'is_admin', False)
    return render_template(
        'user_detail.html',
        user_key=body_user_key,
        schedule=schedule,
        display_name=display_name,
        user_name=current_user.name,
        is_admin='1' if is_admin else '0',
        current_month=datetime.now().strftime('%Y-%m')
    )


@views_bp.route('/admin/audit')
@login_required
def admin_audit():
    """Admin audit log viewer page."""
    if not getattr(current_user, 'is_admin', False):
        abort(403)
    return render_template(
        'admin_audit.html',
        user_name=current_user.name,
        is_admin=True
    )


@views_bp.route('/monthly-report')
@login_required
def monthly_report():
    """Monthly report page."""
    from dashboard_app.models import AttendanceRecord
    from sqlalchemy import func
    from flask import make_response
    
    can_edit = getattr(current_user, 'is_admin', False) or getattr(current_user, 'is_control_manager', False)
    
    # Get current month for default value
    current_month = datetime.now().strftime('%Y-%m')
    
    # Get unique values for filters
    managers = []
    if getattr(current_user, 'is_admin', False):
        from dashboard_app.models import User
        managers = User.query.filter_by(is_control_manager=True).all()
    
    departments = [d[0] for d in AttendanceRecord.query.with_entities(
        AttendanceRecord.department
    ).filter(
        AttendanceRecord.department.isnot(None),
        AttendanceRecord.department != ''
    ).distinct().order_by(AttendanceRecord.department).all()]
    
    teams = [t[0] for t in AttendanceRecord.query.with_entities(
        AttendanceRecord.team
    ).filter(
        AttendanceRecord.team.isnot(None),
        AttendanceRecord.team != ''
    ).distinct().order_by(AttendanceRecord.team).all()]
    
    projects = [p[0] for p in AttendanceRecord.query.with_entities(
        AttendanceRecord.project
    ).filter(
        AttendanceRecord.project.isnot(None),
        AttendanceRecord.project != ''
    ).distinct().order_by(AttendanceRecord.project).all()]
    
    locations = [l[0] for l in AttendanceRecord.query.with_entities(
        AttendanceRecord.location
    ).filter(
        AttendanceRecord.location.isnot(None),
        AttendanceRecord.location != ''
    ).distinct().order_by(AttendanceRecord.location).all()]
    
    response = make_response(render_template(
        'monthly_report.html',
        user_name=current_user.name,
        is_admin=getattr(current_user, 'is_admin', False),
        can_edit=can_edit,
        can_manage_presets=can_edit,
        can_delete_any_presets=_can_delete_any_presets(current_user),
        current_month=current_month,
        managers=managers,
        departments=departments,
        teams=teams,
        projects=projects,
        locations=locations
    ))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@views_bp.route('/lateness')
@login_required
def lateness():
    """Daily lateness archive view."""
    can_edit = getattr(current_user, 'is_admin', False) or getattr(current_user, 'is_control_manager', False)
    return render_template(
        'lateness.html',
        user_name=current_user.name,
        is_admin=getattr(current_user, 'is_admin', False),
        can_edit=can_edit,
        default_days=7
    )
