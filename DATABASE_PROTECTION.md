# Database Protection & Backup System

## 🛡️ Protection Measures

### Files Protected from Git

- `instance/dashboard.db` - Main database with all user data and notes
- `config/user_schedules.json` - User schedule configurations
- `config/work_schedules.json` - Work schedule configurations

These files are in `.gitignore` and will **NEVER** be committed to git.

## 📦 Automatic Backups

### Daily Backups

- **Time**: 3:00 AM daily
- **Location**: `/home/deploy/YaWare_Bot/backups/`
- **Retention**: 30 days
- **Format**: `dashboard_YYYYMMDD_HHMMSS.db.gz`

### Manual Backup

```bash
/home/deploy/YaWare_Bot/scripts/backup_database.sh
```

## 🔧 Server Setup (One-time)

Run on the server:

```bash
bash /home/deploy/YaWare_Bot/scripts/setup_protection.sh
```

## 🔄 Restore from Backup

```bash
# 1. List available backups
ls -lh /home/deploy/YaWare_Bot/backups/

# 2. Restore specific backup
cd /home/deploy/YaWare_Bot
gunzip -c backups/dashboard_20251110_030000.db.gz > instance/dashboard.db

# 3. Restart application
sudo systemctl restart yaware-bot
```

## ⚠️ Emergency Recovery

If data was lost after deployment:

```bash
# 1. Find latest backup
LATEST_BACKUP=$(ls -t /home/deploy/YaWare_Bot/backups/dashboard_*.db.gz | head -1)

# 2. Restore it
cd /home/deploy/YaWare_Bot
gunzip -c "$LATEST_BACKUP" > instance/dashboard.db

# 3. Restart
sudo systemctl restart yaware-bot
```

## 🚨 What Caused Data Loss?

The database was accidentally committed to git and pushed. When deploying, git overwrote the server's database with the old version from the repository.

**This is now prevented by**:

1. `.gitignore` properly configured
2. Git hooks that block merges if database is in commit
3. Daily backups for recovery
4. Config files also protected

## 📊 Verify Protection

```bash
# Check .gitignore
git check-ignore instance/dashboard.db
git check-ignore config/user_schedules.json

# Check cron job
crontab -l | grep backup

# Check latest backup
ls -lh /home/deploy/YaWare_Bot/backups/ | tail -5
```

## 📝 Backup Logs

View backup history:

```bash
tail -50 /home/deploy/YaWare_Bot/logs/backup.log
```
