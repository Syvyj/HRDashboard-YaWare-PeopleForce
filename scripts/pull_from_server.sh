#!/bin/bash
# Скрипт для завантаження всіх даних з сервера

set -e  # Зупинка при помилці

echo "=========================================="
echo "ЗАВАНТАЖЕННЯ ДАНИХ З СЕРВЕРА"
echo "=========================================="
echo ""

# Кольори для виводу
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Перевірка наявності SSH ключа або паролю
echo -e "${YELLOW}Переконайтесь що у вас є доступ до сервера через SSH${NC}"
echo ""

# Запитуємо дані сервера
read -p "Введіть адресу сервера (user@host): " SERVER
if [ -z "$SERVER" ]; then
    echo "Помилка: адреса сервера не може бути порожньою"
    exit 1
fi

read -p "Введіть шлях до проекту на сервері (наприклад: ~/YaWare_Bot): " REMOTE_PATH
if [ -z "$REMOTE_PATH" ]; then
    echo "Помилка: шлях до проекту не може бути порожнім"
    exit 1
fi

# Поточна директорія (локальна)
LOCAL_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ""
echo "Локальний шлях: $LOCAL_PATH"
echo "Віддалений шлях: $SERVER:$REMOTE_PATH"
echo ""

# 1. Завантажити зміни з git
echo -e "${GREEN}[1/5] Завантаження git змін...${NC}"
ssh "$SERVER" "cd $REMOTE_PATH && git pull origin main"
echo "✓ Git оновлено на сервері"
echo ""

# 2. Завантажити базу даних
echo -e "${GREEN}[2/5] Завантаження бази даних...${NC}"
mkdir -p "$LOCAL_PATH/instance"
rsync -avz --progress "$SERVER:$REMOTE_PATH/instance/dashboard.db" "$LOCAL_PATH/instance/" || {
    echo "Помилка при завантаженні БД"
    exit 1
}
echo "✓ База даних завантажена"
echo ""

# 3. Завантажити конфігураційні файли
echo -e "${GREEN}[3/5] Завантаження конфігурації...${NC}"
mkdir -p "$LOCAL_PATH/config"
rsync -avz --progress "$SERVER:$REMOTE_PATH/config/" "$LOCAL_PATH/config/" || {
    echo "Помилка при завантаженні config"
    exit 1
}
echo "✓ Конфігурація завантажена"
echo ""

# 4. Завантажити .env файл (якщо є)
echo -e "${GREEN}[4/5] Завантаження .env файлу...${NC}"
rsync -avz --progress "$SERVER:$REMOTE_PATH/.env" "$LOCAL_PATH/" 2>/dev/null && {
    echo "✓ .env файл завантажено"
} || {
    echo "⚠ .env файл не знайдено або помилка доступу (можливо його немає на сервері)"
}
echo ""

# 5. Завантажити логи (останні 7 днів)
echo -e "${GREEN}[5/5] Завантаження логів...${NC}"
mkdir -p "$LOCAL_PATH/logs"
rsync -avz --progress "$SERVER:$REMOTE_PATH/*.log" "$LOCAL_PATH/logs/" 2>/dev/null && {
    echo "✓ Логи завантажено"
} || {
    echo "⚠ Логи не знайдено"
}
echo ""

# Створити резервну копію БД
echo -e "${GREEN}Створення резервної копії БД...${NC}"
BACKUP_NAME="dashboard_backup_$(date +%Y%m%d_%H%M%S).db"
cp "$LOCAL_PATH/instance/dashboard.db" "$LOCAL_PATH/instance/$BACKUP_NAME"
echo "✓ Резервна копія: instance/$BACKUP_NAME"
echo ""

# Показати статистику БД
echo -e "${GREEN}Статистика бази даних:${NC}"
sqlite3 "$LOCAL_PATH/instance/dashboard.db" "SELECT COUNT(*) as total_records FROM attendance_records;" | head -1 | xargs -I {} echo "  Всього записів: {}"
sqlite3 "$LOCAL_PATH/instance/dashboard.db" "SELECT COUNT(DISTINCT user_name) as unique_users FROM attendance_records;" | head -1 | xargs -I {} echo "  Унікальних користувачів: {}"
sqlite3 "$LOCAL_PATH/instance/dashboard.db" "SELECT MIN(record_date) as oldest, MAX(record_date) as newest FROM attendance_records;" | head -1 | xargs -I {} echo "  Період даних: {}"
sqlite3 "$LOCAL_PATH/instance/dashboard.db" "SELECT ROUND(page_count * page_size / 1024.0 / 1024.0, 2) as size_mb FROM pragma_page_count(), pragma_page_size();" | head -1 | xargs -I {} echo "  Розмір БД: {} MB"
echo ""

echo "=========================================="
echo -e "${GREEN}✓ ЗАВАНТАЖЕННЯ ЗАВЕРШЕНО${NC}"
echo "=========================================="
echo ""
echo "Наступні кроки:"
echo "1. Перевірте дані в локальній БД"
echo "2. При необхідності запустіть: python3 web_dashboard.py"
echo "3. Резервна копія БД: instance/$BACKUP_NAME"
echo ""
