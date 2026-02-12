#!/bin/bash
# Очищення старих бекапів на сервері
# Використання: ./scripts/cleanup_server.sh

set -e

HOST="${DEPLOY_HOST:-deploy@your-server.com}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/home/deploy/www/YaWare_Bot}"

echo "==================================="
echo "Очищення старих бекапів на сервері"
echo "==================================="
echo ""

# 1. Видалити старі auto_backup БД (січень)
echo "🗑️  Видалення старих auto_backup БД..."
ssh "$HOST" "cd $REMOTE_DIR/instance && \
    rm -f dashboard.db.auto_backup_202601*.dashboard.db.backup \
         week_notes.json.local_backup week_notes.json.server 2>/dev/null || true"
echo "✅ Старі auto_backup видалено"

# 2. Видалити старий backup конфігу
echo "🗑️  Видалення старого backup конфігу..."
ssh "$HOST" "cd $REMOTE_DIR/config && \
    rm -f user_schedules.json.backup 2>/dev/null || true"
echo "✅ Старий backup конфігу видалено"

# 3. Очистити backups/ - залишити останні 7 code_backup та 5 server_backup
echo "🗑️  Очищення backups/ (залишаємо останні 7 code_backup та 5 server_backup)..."
ssh "$HOST" "cd $REMOTE_DIR/backups && \
    ls -t code_backup_*.tar.gz 2>/dev/null | tail -n +8 | xargs rm -f 2>/dev/null || true && \
    ls -t server_backup_* 2>/dev/null | tail -n +6 | xargs rm -rf 2>/dev/null || true && \
    rm -f backup_20251231_145553.tar.gz dashboard.db.20251211_100402 monthly_adjustments.json.20251211_100402 2>/dev/null || true"
echo "✅ Старі бекапи видалено"

# 4. Показати що залишилось
echo ""
echo "📊 Залишилось у backups/:"
ssh "$HOST" "cd $REMOTE_DIR/backups && \
    echo 'Code backups:' && ls -lh code_backup_*.tar.gz 2>/dev/null | tail -5 && \
    echo '' && echo 'Server backups:' && ls -ld server_backup_* 2>/dev/null | tail -5"

echo ""
echo "✅ Очищення завершено!"
