#!/bin/bash
# Очищення тестових/дебаг файлів на сервері
# Використання: ./scripts/cleanup_server_test_files.sh

set -e

HOST="${DEPLOY_HOST:-deploy@your-server.com}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/home/deploy/www/YaWare_Bot}"

echo "==================================="
echo "Очищення тестових/дебаг файлів на сервері"
echo "==================================="
echo ""

echo "🗑️  Видалення тестових/дебаг файлів..."
ssh "$HOST" "cd $REMOTE_DIR && \
    rm -f debug_start.sh \
          deploy_debug.sh \
          server_debug.py \
          test_bakumova.py \
          test_kulik_filter.py \
          fix_adjustments.py \
          migrate_presets.py \
          sync_control_manager.py \
          start_gunicorn.sh \
          fetch_server_logs.sh 2>/dev/null || true"

echo "✅ Тестові/дебаг файли видалено з сервера"

# Показати що залишилось
echo ""
echo "📊 Перевірка (має бути порожньо):"
ssh "$HOST" "cd $REMOTE_DIR && \
    ls -la *.py *.sh 2>/dev/null | grep -E 'test_|debug|fix_|migrate|sync_|start_|fetch_' || echo '✅ Всі тестові файли видалено'"

echo ""
echo "✅ Очищення завершено!"
