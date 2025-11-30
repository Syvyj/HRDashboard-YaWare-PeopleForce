from __future__ import annotations
from datetime import datetime, date
from typing import List, Optional
from sqlalchemy import text, inspect
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    manager_filter = db.Column(db.String(255), nullable=True)  # e.g. "1,2"
    is_admin = db.Column(db.Boolean, default=False)
    is_control_manager = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def allowed_managers(self) -> Optional[List[int]]:
        if self.is_admin or not self.manager_filter:
            return None
        managers = []
        for value in self.manager_filter.split(','):
            value = value.strip()
            if not value:
                continue
            try:
                managers.append(int(value))
            except ValueError:
                continue
        
        # Control manager with ID=3 sees everyone
        if self.is_control_manager and managers == [3]:
            return None
        
        return managers or None


class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'

    id = db.Column(db.Integer, primary_key=True)
    record_date = db.Column(db.Date, nullable=False, index=True)
    internal_user_id = db.Column(db.Integer, nullable=True, index=True)
    user_id = db.Column(db.String(64), nullable=False, index=True)
    user_name = db.Column(db.String(255), nullable=False)
    user_email = db.Column(db.String(255), nullable=True, index=True)
    record_type = db.Column(db.String(16), nullable=True, default='daily', index=True)  # 'daily', 'week_total', 'leave', 'absent'
    project = db.Column(db.String(255), nullable=True)
    department = db.Column(db.String(255), nullable=True)
    team = db.Column(db.String(255), nullable=True)
    location = db.Column(db.String(255), nullable=True)
    scheduled_start = db.Column(db.String(16), nullable=True)
    actual_start = db.Column(db.String(16), nullable=True)
    minutes_late = db.Column(db.Integer, nullable=False, default=0)
    non_productive_minutes = db.Column(db.Integer, nullable=False, default=0)
    not_categorized_minutes = db.Column(db.Integer, nullable=False, default=0)
    productive_minutes = db.Column(db.Integer, nullable=False, default=0)
    total_minutes = db.Column(db.Integer, nullable=False, default=0)
    corrected_total_minutes = db.Column(db.Integer, nullable=True)
    manual_scheduled_start = db.Column(db.Boolean, nullable=False, default=False)
    manual_actual_start = db.Column(db.Boolean, nullable=False, default=False)
    manual_minutes_late = db.Column(db.Boolean, nullable=False, default=False)
    manual_non_productive_minutes = db.Column(db.Boolean, nullable=False, default=False)
    manual_not_categorized_minutes = db.Column(db.Boolean, nullable=False, default=False)
    manual_productive_minutes = db.Column(db.Boolean, nullable=False, default=False)
    manual_total_minutes = db.Column(db.Boolean, nullable=False, default=False)
    manual_corrected_total_minutes = db.Column(db.Boolean, nullable=False, default=False)
    manual_status = db.Column(db.Boolean, nullable=False, default=False)
    manual_notes = db.Column(db.Boolean, nullable=False, default=False)
    manual_leave_reason = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(16), nullable=False)  # late / absent / present / leave
    control_manager = db.Column(db.Integer, nullable=True, index=True)
    leave_reason = db.Column(db.String(255), nullable=True)
    half_day_amount = db.Column(db.Float, nullable=True)  # 0.5 for half-day leave, 1.0 for full day, None if not a leave
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('record_date', 'user_id', name='uq_attendance_date_user'),
        db.Index('idx_user_date', 'user_id', 'record_date'),
        db.Index('idx_date_status', 'record_date', 'status'),
        db.Index('idx_control_manager_date', 'control_manager', 'record_date'),
        db.Index('idx_user_name', 'user_name'),
    )

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'date': self.record_date.isoformat(),
            'user_id': self.user_id,
            'user_name': self.user_name,
            'user_email': self.user_email,
            'project': self.project,
            'department': self.department,
            'team': self.team,
            'location': self.location,
            'scheduled_start': self.scheduled_start,
            'actual_start': self.actual_start,
            'minutes_late': self.minutes_late,
            'non_productive_minutes': self.non_productive_minutes,
            'not_categorized_minutes': self.not_categorized_minutes,
            'productive_minutes': self.productive_minutes,
            'total_minutes': self.total_minutes,
            'corrected_total_minutes': self.corrected_total_minutes,
            'manual_flags': {
                'scheduled_start': bool(self.manual_scheduled_start),
                'actual_start': bool(self.manual_actual_start),
                'minutes_late': bool(self.manual_minutes_late),
                'non_productive_minutes': bool(self.manual_non_productive_minutes),
                'not_categorized_minutes': bool(self.manual_not_categorized_minutes),
                'productive_minutes': bool(self.manual_productive_minutes),
                'total_minutes': bool(self.manual_total_minutes),
                'corrected_total_minutes': bool(self.manual_corrected_total_minutes),
                'status': bool(self.manual_status),
                'notes': bool(self.manual_notes),
                'leave_reason': bool(self.manual_leave_reason),
            },
            'status': self.status,
            'control_manager': self.control_manager,
            'leave_reason': self.leave_reason,
            'half_day_amount': self.half_day_amount,
            'notes': self.notes,
        }


class AdminAuditLog(db.Model):
    __tablename__ = 'admin_audit_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action = db.Column(db.String(128), nullable=False, index=True)
    details = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    user = db.relationship('User', backref=db.backref('audit_logs', lazy='dynamic'))

    __table_args__ = (
        db.Index('idx_audit_user_action', 'user_id', 'action'),
        db.Index('idx_audit_created', 'created_at'),
    )


class EmployeePreset(db.Model):
    __tablename__ = 'employee_presets'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=False)
    employee_keys = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    owner = db.relationship('User', backref=db.backref('employee_presets', lazy='dynamic'))

    __table_args__ = (
        db.UniqueConstraint('owner_id', 'name', name='uq_employee_preset_owner_name'),
        db.Index('idx_employee_preset_created', 'created_at'),
    )


class LatenessRecord(db.Model):
    __tablename__ = 'lateness_records'

    id = db.Column(db.Integer, primary_key=True)
    record_date = db.Column(db.Date, nullable=False, index=True)
    user_name = db.Column(db.String(255), nullable=False, index=True)
    user_email = db.Column(db.String(255), nullable=True, index=True)
    user_id = db.Column(db.String(64), nullable=True, index=True)
    project = db.Column(db.String(255), nullable=True)
    department = db.Column(db.String(255), nullable=True)
    team = db.Column(db.String(255), nullable=True)
    location = db.Column(db.String(255), nullable=True)
    scheduled_start = db.Column(db.String(16), nullable=True)
    actual_start = db.Column(db.String(16), nullable=True)
    minutes_late = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(16), nullable=False)  # late / absent
    control_manager = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.Index('idx_lateness_date_status', 'record_date', 'status'),
    )


def ensure_schema() -> None:
    """Ensure optional columns exist in database."""
    engine = db.engine
    manual_columns = {
        'corrected_total_minutes': 'INTEGER',
        'manual_scheduled_start': 'INTEGER DEFAULT 0',
        'manual_actual_start': 'INTEGER DEFAULT 0',
        'manual_minutes_late': 'INTEGER DEFAULT 0',
        'manual_non_productive_minutes': 'INTEGER DEFAULT 0',
        'manual_not_categorized_minutes': 'INTEGER DEFAULT 0',
        'manual_productive_minutes': 'INTEGER DEFAULT 0',
        'manual_total_minutes': 'INTEGER DEFAULT 0',
        'manual_corrected_total_minutes': 'INTEGER DEFAULT 0',
        'manual_status': 'INTEGER DEFAULT 0',
        'manual_notes': 'INTEGER DEFAULT 0',
        'manual_leave_reason': 'INTEGER DEFAULT 0',
    }

    if engine.dialect.name == 'sqlite':
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(attendance_records)"))
            columns = {row[1] for row in result}
            for column, ddl in manual_columns.items():
                if column not in columns:
                    conn.execute(text(f"ALTER TABLE attendance_records ADD COLUMN {column} {ddl}"))
    else:
        inspector = inspect(engine)
        column_names = {col['name'] for col in inspector.get_columns('attendance_records')}
        with engine.begin() as conn:
            for column, ddl in manual_columns.items():
                if column not in column_names:
                    conn.execute(text(f"ALTER TABLE attendance_records ADD COLUMN {column} {ddl}"))
