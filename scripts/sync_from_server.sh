#!/bin/bash
# Швидка синхронізація даних з сервера (стягування + бекап + оновлення локальних)

set -e

# Конфігурація
SERVER="${DEPLOY_HOST:-deploy@your-server.com}"
REMOTE_PATH="${DEPLOY_REMOTE_DIR:-/home/deploy/www/YaWare_Bot}"
LOCAL_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Кольори
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${BLUE}=========================================="
echo "СИНХРОНІЗАЦІЯ З СЕРВЕРОМ"
echo "==========================================${NC}"
echo ""
echo "Сервер: $SERVER"
echo "Локальна папка: $LOCAL_PATH"
echo ""

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$LOCAL_PATH/backups/server_backup_$TIMESTAMP"

# Створюємо директорію для бекапу серверних даних
mkdir -p "$BACKUP_DIR/instance"
mkdir -p "$BACKUP_DIR/config"

# ========================================
# КРОК 1: СТЯГУВАННЯ З СЕРВЕРА
# ========================================
echo -e "${YELLOW}[1/3] Завантаження даних з сервера...${NC}"

# База даних
if scp "$SERVER:$REMOTE_PATH/instance/dashboard.db" "$BACKUP_DIR/instance/dashboard.db" 2>/dev/null; then
    DB_SIZE=$(du -h "$BACKUP_DIR/instance/dashboard.db" | cut -f1)
    echo "✓ База даних завантажена ($DB_SIZE)"
else
    echo -e "${RED}✗ Не вдалось завантажити базу даних${NC}"
    exit 1
fi

# Week notes
if scp "$SERVER:$REMOTE_PATH/instance/week_notes.json" "$BACKUP_DIR/instance/week_notes.json" 2>/dev/null; then
    echo "✓ Week notes завантажено"
else
    echo "⚠ Week notes не знайдено на сервері (це нормально)"
fi

# Monthly notes
if scp "$SERVER:$REMOTE_PATH/instance/monthly_notes.json" "$BACKUP_DIR/instance/monthly_notes.json" 2>/dev/null; then
    echo "✓ Monthly notes завантажено"
else
    echo "⚠ Monthly notes не знайдено на сервері (це нормально)"
fi

# User schedules
if scp "$SERVER:$REMOTE_PATH/config/user_schedules.json" "$BACKUP_DIR/config/user_schedules.json" 2>/dev/null; then
    echo "✓ User schedules завантажено"
else
    echo -e "${RED}✗ Не вдалось завантажити user_schedules${NC}"
    exit 1
fi

echo ""

# ========================================
# КРОК 2: СТВОРЕННЯ БЕКАПУ
# ========================================
echo -e "${YELLOW}[2/3] Створення бекапу серверних даних...${NC}"
echo "✓ Бекап збережено в: backups/server_backup_$TIMESTAMP/"
echo ""

# ========================================
# КРОК 3: ОНОВЛЕННЯ ЛОКАЛЬНИХ ФАЙЛІВ
# ========================================
echo -e "${YELLOW}[3/3] Оновлення локальних файлів...${NC}"

# Копіюємо з бекапу в локальні файли
cp "$BACKUP_DIR/instance/dashboard.db" "$LOCAL_PATH/instance/dashboard.db"
echo "✓ База даних оновлена"

if [ -f "$BACKUP_DIR/instance/week_notes.json" ]; then
    cp "$BACKUP_DIR/instance/week_notes.json" "$LOCAL_PATH/instance/week_notes.json"
    echo "✓ Week notes оновлено"
fi

if [ -f "$BACKUP_DIR/instance/monthly_notes.json" ]; then
    cp "$BACKUP_DIR/instance/monthly_notes.json" "$LOCAL_PATH/instance/monthly_notes.json"
    echo "✓ Monthly notes оновлено"
fi

cp "$BACKUP_DIR/config/user_schedules.json" "$LOCAL_PATH/config/user_schedules.json"
echo "✓ User schedules оновлено"

echo ""

# ========================================
# ПІДСУМОК
# ========================================
echo -e "${GREEN}✅ Синхронізація завершена!${NC}"
echo ""

echo -e "${GREEN}✅ Синхронізація завершена!${NC}"
echo ""

# Статистика
if [ -f "$LOCAL_PATH/instance/dashboard.db" ]; then
    DB_SIZE=$(du -h "$LOCAL_PATH/instance/dashboard.db" | cut -f1)
    RECORD_COUNT=$(sqlite3 "$LOCAL_PATH/instance/dashboard.db" "SELECT COUNT(*) FROM attendance_records;" 2>/dev/null || echo "N/A")
    echo "📊 База даних: $DB_SIZE, записів: $RECORD_COUNT"
fi

if [ -f "$LOCAL_PATH/instance/week_notes.json" ]; then
    WEEK_NOTES_COUNT=$(cat "$LOCAL_PATH/instance/week_notes.json" | grep -o '"note"' | wc -l | tr -d ' ')
    echo "📝 Week notes: $WEEK_NOTES_COUNT коментарів"
fi

echo "💾 Бекап збережено: backups/server_backup_$TIMESTAMP/"
echo ""

