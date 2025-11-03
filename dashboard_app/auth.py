from __future__ import annotations
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from .extensions import login_manager, db
from .models import User
import os

auth_bp = Blueprint('auth', __name__)


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('views.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        allowed_domain = os.getenv('DASHBOARD_ALLOWED_DOMAIN', 'evadav.com')

        if not email.endswith(f"@{allowed_domain}"):
            flash(f"Доступ дозволено лише для корпоративної пошти @{allowed_domain}", 'danger')
            return redirect(url_for('auth.login'))

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('views.dashboard'))

        flash('Невірний email або пароль', 'danger')
        return redirect(url_for('auth.login'))

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
