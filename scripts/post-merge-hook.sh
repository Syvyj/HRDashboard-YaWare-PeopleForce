#!/bin/bash
# Post-merge hook to prevent database overwrites

echo "🔍 Checking for sensitive files..."

# Check if instance/dashboard.db was modified
if git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD | grep -q "instance/dashboard.db"; then
    echo "⚠️  WARNING: Database file was in commit!"
    echo "⚠️  This should NEVER happen. Database is in .gitignore"
    echo ""
    echo "🛑 ABORTING: Please restore database from backup"
    exit 1
fi

# Check if config files were modified
if git diff-tree -r --name-only --no-commit-id ORIG_HEAD HEAD | grep -q "config/user_schedules.json\|config/work_schedules.json"; then
    echo "⚠️  WARNING: Config files were in commit!"
    echo "⚠️  These files are in .gitignore and should not be tracked"
    echo ""
    echo "Creating backup before merge..."
    cp config/user_schedules.json config/user_schedules.json.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true
    cp config/work_schedules.json config/work_schedules.json.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true
fi

echo "✅ Post-merge check passed"
exit 0
