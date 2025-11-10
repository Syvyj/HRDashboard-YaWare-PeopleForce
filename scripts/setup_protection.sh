#!/bin/bash
# Setup script for server deployment protection

echo "🚀 Setting up database protection..."

# 1. Make backup script executable
chmod +x /home/deploy/YaWare_Bot/scripts/backup_database.sh

# 2. Setup cron job for daily backups at 3 AM
CRON_JOB="0 3 * * * /home/deploy/YaWare_Bot/scripts/backup_database.sh >> /home/deploy/YaWare_Bot/logs/backup.log 2>&1"
(crontab -l 2>/dev/null | grep -v "backup_database.sh"; echo "$CRON_JOB") | crontab -

# 3. Create logs directory
mkdir -p /home/deploy/YaWare_Bot/logs
mkdir -p /home/deploy/YaWare_Bot/backups

# 4. Install git hooks
cp /home/deploy/YaWare_Bot/scripts/post-merge-hook.sh /home/deploy/YaWare_Bot/.git/hooks/post-merge
chmod +x /home/deploy/YaWare_Bot/.git/hooks/post-merge

# 5. Verify .gitignore has all sensitive files
echo "Verifying .gitignore..."
cd /home/deploy/YaWare_Bot
git check-ignore instance/dashboard.db > /dev/null || echo "⚠️  WARNING: instance/dashboard.db NOT in .gitignore!"
git check-ignore config/user_schedules.json > /dev/null || echo "⚠️  WARNING: config/user_schedules.json NOT in .gitignore!"
git check-ignore config/work_schedules.json > /dev/null || echo "⚠️  WARNING: config/work_schedules.json NOT in .gitignore!"

# 6. Create initial backup
echo "Creating initial backup..."
/home/deploy/YaWare_Bot/scripts/backup_database.sh

echo ""
echo "✅ Setup complete!"
echo ""
echo "📋 Summary:"
echo "  - Daily backups: 3:00 AM (kept for 30 days)"
echo "  - Backup location: /home/deploy/YaWare_Bot/backups/"
echo "  - Git hooks: installed"
echo "  - Logs: /home/deploy/YaWare_Bot/logs/backup.log"
echo ""
echo "To verify cron job: crontab -l"
