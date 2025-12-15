# PF Status Column Deployment Checklist

## Feature Overview

Separated PeopleForce automatic status updates from manager notes by adding a new `pf_status` column.

### Changes Summary:

1. **Database**: Added `pf_status` TEXT column to `attendance_records` table
2. **Backend Model**: Updated `AttendanceRecord` model with pf_status field
3. **API**: Added pf_status to JSON responses and Excel export
4. **Frontend**: Added "PF Status" column to attendance table
5. **Sync Logic**: Updated attendance sync to populate pf_status from PeopleForce leave_reason
6. **Bot**: Simplified telegram messages to Ukrainian with dashboard link

## Files Modified:

- `dashboard_app/models.py` - Added pf_status column definition
- `dashboard_app/api.py` - Added pf_status to API response (~line 1539) and Excel export (lines 4094-4150)
- `static/js/report.js` - Added "PF Status" column header and cell rendering
- `tasks/update_attendance.py` - Populated pf_status from leave_reason in 3 record creation blocks
- `tracker_alert/bot/scheduler.py` - Simplified message to Ukrainian
- `scripts/add_pf_status_column.py` - Migration script (already run locally)

## Deployment Steps:

### 1. Backup Server Data ✓

Already completed: backups/server_20251203_014310/

### 2. Run Migration on Server

```bash
ssh deploy@65.21.51.165
cd /home/deploy/www/YaWare_Bot
source .venv/bin/activate
python scripts/add_pf_status_column.py instance/dashboard.db
```

### 3. Deploy Code Changes

```bash
# Local machine
cd /Users/admin/Documents/YaWare_Bot
git add .
git commit -m "Add pf_status column: separate PeopleForce status from manager notes"
git push origin main
```

### 4. Restart Gunicorn

```bash
ssh deploy@65.21.51.165
sudo systemctl restart yaware-dashboard
sudo systemctl status yaware-dashboard
```

### 5. Verification

- [ ] Check that migration ran successfully (no errors)
- [ ] Verify dashboard loads without errors
- [ ] Check that "PF Status" column appears in attendance table
- [ ] Verify Excel export includes "PF Status" column
- [ ] Wait for next sync (09:15) and verify pf_status is populated for users with leaves
- [ ] Test that managers can still edit "Notes" column independently

## Rollback Plan (if needed):

1. Restore from backup: `backups/server_20251203_014310/dashboard.db`
2. Git revert: `git revert HEAD`
3. Restart gunicorn

## Testing Checklist:

- [ ] Local testing completed (dev server running)
- [ ] Migration script tested locally
- [ ] Frontend displays new column
- [ ] API returns pf_status field
- [ ] Excel export includes pf_status
- [ ] No Python errors in get_errors check

## Notes:

- The pf_status field will be automatically populated during the next PeopleForce sync (09:17 daily)
- Existing records will have pf_status=NULL until next sync
- Manager notes remain in the "Notes" column and are editable
- PF Status column is read-only and populated automatically
