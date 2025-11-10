#!/bin/bash
# Daily database backup script

# Configuration
BACKUP_DIR="/home/deploy/YaWare_Bot/backups"
DB_PATH="/home/deploy/YaWare_Bot/instance/dashboard.db"
RETENTION_DAYS=30

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Generate backup filename with timestamp
BACKUP_FILE="$BACKUP_DIR/dashboard_$(date +%Y%m%d_%H%M%S).db"

# Create backup
cp "$DB_PATH" "$BACKUP_FILE"

# Compress backup
gzip "$BACKUP_FILE"

# Delete backups older than retention period
find "$BACKUP_DIR" -name "dashboard_*.db.gz" -type f -mtime +$RETENTION_DAYS -delete

echo "✅ Database backup created: $BACKUP_FILE.gz"
echo "📊 Total backups: $(ls -1 $BACKUP_DIR/dashboard_*.db.gz 2>/dev/null | wc -l)"
