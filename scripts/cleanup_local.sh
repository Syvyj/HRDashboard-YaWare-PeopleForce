#!/bin/bash
# Очищення непотрібних файлів локально
# Використання: ./scripts/cleanup_local.sh

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "==================================="
echo "Очищення непотрібних файлів локально"
echo "==================================="
echo ""

# Питаємо підтвердження для великих видалень
read -p "⚠️  Видалити All_Backup/ (1.3GB)? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🗑️  Видалення All_Backup/..."
    rm -rf All_Backup/
    echo "✅ All_Backup/ видалено"
else
    echo "⏭️  All_Backup/ пропущено"
fi

# Backup файли в config/
echo "🗑️  Видалення backup файлів у config/..."
rm -f config/user_schedules.json.backup \
      config/user_schedules.json.backup_20260107_131219 \
      config/user_schedules.json.server
echo "✅ Backup файли у config/ видалено"

# Backup файли в instance/
echo "🗑️  Видалення backup файлів у instance/..."
rm -f instance/monthly_notes.json.backup_20260107_131229 \
      instance/monthly_notes.json.server \
      instance/monthly_notes.json.server_new \
      instance/week_notes.json.backup_20251215_210529 \
      instance/week_notes.json.backup_20260107_131707 \
      instance/week_notes.json.server \
      instance/week_notes.json.server_new
echo "✅ Backup файли у instance/ видалено"

# Тестові/дебаг скрипти (безпечно видалити - не використовуються)
echo "🗑️  Видалення тестових/дебаг скриптів..."
rm -f debug_start.sh \
      deploy_debug.sh \
      server_debug.py \
      test_bakumova.py \
      test_kulik_filter.py \
      fix_adjustments.py \
      migrate_presets.py \
      sync_control_manager.py \
      start_gunicorn.sh \
      fetch_server_logs.sh
echo "✅ Тестові/дебаг скрипти видалено (10 файлів)"

# Старі документи (опційно)
read -p "⚠️  Видалити старі документи (REFACTORING_ANALYSIS.md тощо)? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🗑️  Видалення старих документів..."
    rm -f REFACTORING_ANALYSIS.md \
          SERVER_SYNC_SUMMARY.md \
          DEPLOYMENT_PF_STATUS.md \
          DEPLOYMENT_WEEK_NAVIGATION.md
    echo "✅ Старі документи видалено"
else
    echo "⏭️  Старі документи пропущено"
fi

echo ""
echo "✅ Очищення завершено!"
echo ""
echo "📊 Розмір проекту після очищення:"
du -sh "$PROJECT_ROOT" 2>/dev/null || echo "Не вдалося підрахувати"
