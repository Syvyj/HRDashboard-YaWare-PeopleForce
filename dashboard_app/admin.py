from __future__ import annotations

from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin')
@login_required
def admin_index():
    if not getattr(current_user, 'is_admin', False):
        abort(403)
    return render_template('admin.html', user_name=current_user.name)


@admin_bp.route('/admin/scheduler')
@login_required
def admin_scheduler_page():
    if not getattr(current_user, 'is_admin', False):
        abort(403)
    return render_template('admin_scheduler.html', user_name=current_user.name)
