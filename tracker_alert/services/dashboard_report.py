"""Access attendance data from the dashboard database for Telegram reports."""
from __future__ import annotations

import os
from datetime import date
from typing import List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from tracker_alert.services.attendance_monitor import UserSchedule, AttendanceStatus


class DashboardReportService:
    """Fetch lateness/absence information from the dashboard DB."""

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or os.getenv("DASHBOARD_DATABASE_URL", "sqlite:///instance/dashboard.db")
        url = make_url(self.database_url)
        engine_kwargs = {"future": True}
        if url.drivername.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        self.engine: Engine = create_engine(self.database_url, **engine_kwargs)

    def _fetch_status_rows(self, target_date: date) -> List[dict]:
        query = text(
            """
            SELECT user_name,
                   COALESCE(user_email, '') AS user_email,
                   user_id,
                   COALESCE(project, '') AS project,
                   COALESCE(department, '') AS department,
                   COALESCE(team, '') AS team,
                   COALESCE(location, '') AS location,
                   COALESCE(scheduled_start, '') AS scheduled_start,
                   COALESCE(actual_start, '') AS actual_start,
                   COALESCE(minutes_late, 0) AS minutes_late,
                   status,
                   control_manager
            FROM attendance_records
            WHERE record_date = :target_date
              AND status IN ('late', 'absent')
            ORDER BY user_name
            """
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"target_date": target_date.isoformat()})
            return [dict(row) for row in rows]

    def _build_statuses(self, target_date: date) -> List[AttendanceStatus]:
        rows = self._fetch_status_rows(target_date)
        statuses: List[AttendanceStatus] = []
        for row in rows:
            schedule = UserSchedule(
                name=row["user_name"],
                email=row["user_email"],
                user_id=str(row["user_id"]),
                start_time=row["scheduled_start"],
                location=row["location"],
                project=row["project"],
                department=row["department"],
                team=row["team"],
                control_manager=row.get("control_manager"),
                exclude_from_reports=False,
                note=None,
            )
            statuses.append(
                AttendanceStatus(
                    user=schedule,
                    status=row["status"],
                    actual_time=row["actual_start"],
                    expected_time=row["scheduled_start"],
                    minutes_late=int(row.get("minutes_late", 0) or 0),
                )
            )
        return statuses

    def get_daily_report(self, target_date: date) -> dict:
        statuses = self._build_statuses(target_date)
        late = [s for s in statuses if s.status == "late"]
        absent = [s for s in statuses if s.status == "absent"]
        return {
            "date": target_date.isoformat(),
            "late": late,
            "absent": absent,
            "total_issues": len(late) + len(absent),
        }

    @staticmethod
    def filter_report_by_managers(report: dict, allowed_managers: Optional[List[int]]) -> dict:
        """Limit report entries by control manager ids."""
        if not allowed_managers:
            return report
        allowed_set = {int(mid) for mid in allowed_managers}

        def is_allowed(status: AttendanceStatus) -> bool:
            return status.user.control_manager is not None and status.user.control_manager in allowed_set

        filtered_late = [status for status in report["late"] if is_allowed(status)]
        filtered_absent = [status for status in report["absent"] if is_allowed(status)]
        return {
            "date": report.get("date"),
            "late": filtered_late,
            "absent": filtered_absent,
            "total_issues": len(filtered_late) + len(filtered_absent),
        }
