#!/bin/bash
# ========================================
# Eva_Control_Bot - Скрипт запуска macOS/Linux
# ========================================

# Переходимо в директорію скрипта, щоб усі відносні шляхи (наприклад .env) працювали
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "========================================"
echo "Eva_Control_Bot - Запуск..."
echo "========================================"
echo ""

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Проверка наличия Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR]${NC} Python3 не найден!"
    echo "Пожалуйста, установите Python 3.8+ с https://www.python.org/downloads/"
    exit 1
fi

echo -e "${GREEN}[OK]${NC} Python найден"
python3 --version

# Проверка наличия .env файла
if [ ! -f ".env" ]; then
    echo ""
    echo -e "${RED}[ERROR]${NC} Файл .env не найден!"
    echo "Пожалуйста, создайте .env файл с необходимыми переменными:"
    echo "  - YAWARE_API_TOKEN"
    echo "  - PEOPLEFORCE_API_TOKEN"
    echo "  - TELEGRAM_BOT_TOKEN"
    echo "  - TELEGRAM_ADMIN_CHAT_IDS"
    echo "  - GOOGLE_SHEET_URL"
    echo ""
    exit 1
fi

echo -e "${GREEN}[OK]${NC} Файл .env найден"

# Проверка наличия gcp-sa.json
if [ ! -f "gcp-sa.json" ]; then
    echo ""
    echo -e "${RED}[ERROR]${NC} Файл gcp-sa.json не найден!"
    echo "Это сервисный аккаунт для доступа к Google Sheets"
    echo ""
    exit 1
fi

echo -e "${GREEN}[OK]${NC} Файл gcp-sa.json найден"

# Проверка наличия конфигурации расписания
if [ ! -f "config/work_schedules.json" ]; then
    echo ""
    echo -e "${RED}[ERROR]${NC} Файл config/work_schedules.json не найден!"
    echo ""
    exit 1
fi

if [ ! -f "config/user_schedules.json" ]; then
    echo ""
    echo -e "${RED}[ERROR]${NC} Файл config/user_schedules.json не найден!"
    echo ""
    exit 1
fi

echo -e "${GREEN}[OK]${NC} Конфигурационные файлы найдены"

# Установка/обновление зависимостей
echo ""
echo "Проверка зависимостей..."

# Попытка использовать pip3
if command -v pip3 &> /dev/null; then
    pip3 install -r requirements.txt --quiet
elif command -v pip &> /dev/null; then
    pip install -r requirements.txt --quiet
else
    echo -e "${YELLOW}[WARNING]${NC} pip не найден, пропускаем установку зависимостей"
    echo "Запустите вручную: pip3 install -r requirements.txt"
fi

echo -e "${GREEN}[OK]${NC} Зависимости установлены"

# Запуск бота
echo ""
echo "========================================"
echo "Запуск бота..."
echo "========================================"
echo ""
echo "Для остановки бота нажмите Ctrl+C"
echo ""

# Запуск с обработкой ошибок
python3 scripts/run_attendance_bot.py

# Проверка кода выхода
exit_code=$?
if [ $exit_code -ne 0 ]; then
    echo ""
    echo "========================================"
    echo -e "${RED}[ERROR]${NC} Бот завершился с ошибкой!"
    echo "========================================"
    echo ""
    exit $exit_code
fi
