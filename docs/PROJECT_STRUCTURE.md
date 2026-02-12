# Структура проекту YaWare_Bot

Оновлено: 19 листопада 2025

## 📁 Поточна структура проекту:

```
YaWare_Bot/
├── .env                          # Конфігурація (API ключі)
├── .gitignore                    # Git ignore правила
├── README.md                     # Головна документація
├── requirements.txt              # Python залежності
├── gcp-sa.json                   # Google Cloud service account
├── web_dashboard.py              # Flask веб-додаток (точка входу)
├── app.py                        # Legacy точка входу
│
├── config/                       # Конфігураційні файли
│   ├── user_schedules.json       # База співробітників (170+ осіб, 4-рівнева ієрархія)
│   ├── user_schedules.json.backup # Автоматичний backup
│   ├── work_schedules.json       # Правила визначення графіків
│   └── Level_Grade.json          # Довідник для адаптації даних (562 записи)
│
├── instance/                     # SQLite база даних
│   └── dashboard.db              # Attendance records, users, audit logs
│
├── logs/                         # Логи застосунку
│
├── docs/                         # Документація
│   ├── ADMIN_GUIDE.md            # Керівництво адміністратора
│   ├── DEPLOYMENT.md             # Інструкція з деплою
│   ├── YAWARE_API_GUIDE.md       # YaWare API документація
│   ├── PEOPLEFORCE_API_GUIDE.md  # PeopleForce API документація
│   ├── AUTO_EXPORT_GUIDE.md      # Автоматизація експорту
│   ├── TELEGRAM_BOT_GUIDE.md     # Telegram бот
│   ├── AVAILABLE_DATA.md         # Опис доступних даних
│   ├── PROJECT_STRUCTURE.md      # Цей файл
│   └── MIGRATION_CHECKLIST.md    # Чеклист міграції
│
├── dashboard_app/                # Flask додаток
│   ├── __init__.py               # Ініціалізація Flask app
│   ├── api.py                    # REST API endpoints (3500+ рядків)
│   ├── views.py                  # HTML views (dashboard, login)
│   ├── auth.py                   # Авторизація користувачів
│   ├── admin.py                  # Адмін панель
│   ├── models.py                 # SQLAlchemy моделі (AttendanceRecord, User, AdminAuditLog)
│   ├── extensions.py             # Flask extensions (db, login_manager)
│   ├── tasks.py                  # Background tasks (attendance updates, control manager assignment)
│   └── user_data.py              # Робота з user_schedules.json
│
├── static/                       # Статичні файли
│   ├── css/
│   │   └── style.css             # Стилі веб-панелі
│   ├── js/
│   │   ├── common.js             # Загальні функції
│   │   ├── report.js             # Dashboard фільтри та звіти (1100+ рядків)
│   │   ├── admin.js              # Адмін панель (1350+ рядків)
│   │   ├── scheduler.js          # Scheduler для control managers
│   │   └── user_detail.js        # Деталі користувача
│   └── logo/                     # Логотипи (YaWare, PeopleForce, Telegram)
│
├── templates/                    # HTML шаблони (Jinja2)
│   ├── dashboard.html            # Головна панель з фільтрами
│   ├── admin.html                # Адмін панель управління співробітниками
│   ├── admin_scheduler.html      # Scheduler для control managers
│   ├── user_detail.html          # Деталі користувача
│   └── login.html                # Сторінка входу
│
├── tracker_alert/                # Основний пакет інтеграцій
│   ├── bot/                      # Telegram бот
│   │   ├── telegram_bot.py       # Основний бот
│   │   ├── scheduler.py          # Планувальник повідомлень
│   │   ├── run_polling.py        # Запуск polling mode
│   │   └── handlers/
│   │       └── commands.py       # Обробники команд
│   │
│   ├── client/                   # API клієнти
│   │   ├── peopleforce_api.py    # PeopleForce API client
│   │   └── yaware_v2_api.py      # YaWare API v2 client
│   │
│   ├── config/                   # Налаштування
│   │   └── settings.py           # Глобальні налаштування (.env)
│   │
│   ├── domain/                   # Бізнес-логіка
│   │   ├── mapping_v2.py         # Мапінг даних для експорту
│   │   ├── schedules.py          # Управління графіками роботи
│   │   ├── week_utils.py         # Утиліти для роботи з тижнями
│   │   └── weekly_mapping.py     # Мапінг тижневих даних
│   │
│   ├── scripts/                  # CLI скрипти
│   │   ├── add_is_control_manager_column.py  # Міграція БД
│   │   ├── add_telegram_usernames.py         # Додавання Telegram username
│   │   ├── clean_telegram_html.py            # Очищення HTML
│   │   ├── sync_peopleforce_telegram.py      # Синхронізація Telegram username
│   │   ├── export_weekly.py                  # Тижневий експорт
│   │   └── run_attendance_bot.py             # Запуск attendance бота
│   │
│   └── services/                 # Сервіси
│       ├── attendance_monitor.py # Моніторинг відвідуваності
│       ├── attendance_reports.py # Генерація звітів (Excel/PDF)
│       ├── report_formatter.py   # Форматування звітів
│       ├── schedule_utils.py     # Утиліти для графіків (manual_overrides)
│       ├── sheets.py              # Google Sheets API
│       └── user_manager.py       # Управління user_schedules.json
│
├── tasks/                        # Background tasks
│   └── update_attendance.py      # Оновлення attendance з YaWare
│
├── scripts/                      # Deployment скрипти
│   ├── backup_database.sh        # Backup БД
│   ├── pull_from_server.sh       # Завантаження з сервера
│   ├── post-merge-hook.sh        # Git post-merge hook
│   └── setup_protection.sh       # Захист БД
│
└── archive/                      # Архів
    └── tests/                    # Тестові скрипти (історичні)
```

## 📊 Ключові компоненти

### 1. Веб-додаток (Flask)

**Точка входу**: `web_dashboard.py`

**Основні модулі**:

- `dashboard_app/api.py` - REST API (3500+ рядків):

  - `/api/attendance` - отримання даних відвідуваності
  - `/api/admin/employees` - управління співробітниками
  - `/api/admin/employees/<key>/sync` - синхронізація з PeopleForce
  - `/api/admin/employees/<key>/adapt` - адаптація через Level_Grade.json
  - `/api/admin/sync/users` - масова синхронізація
  - Експорт Excel/PDF звітів

- `dashboard_app/models.py` - SQLAlchemy моделі:

  - `AttendanceRecord` - записи відвідуваності
  - `User` - користувачі веб-панелі (адміни, control managers)
  - `AdminAuditLog` - логи дій адміністраторів

- `dashboard_app/tasks.py` - фонові задачі:
  - Оновлення attendance з YaWare
  - Автопризначення control_manager
  - Планувальник задач

### 2. Frontend (Vanilla JS + Bootstrap)

- `static/js/report.js` (1100+ рядків):

  - Динамічні фільтри з 4-рівневою ієрархією
  - Multi-select співробітників
  - Експорт звітів
  - Редагування нотаток

- `static/js/admin.js` (1350+ рядків):
  - CRUD операції співробітників
  - Синхронізація з PeopleForce
  - Адаптація даних через Level_Grade.json
  - Управління control managers

### 3. API Integration

**YaWare API v2** (`tracker_alert/client/yaware_v2_api.py`):

- Отримання даних продуктивності
- Статистика за період
- User activity tracking

**PeopleForce API** (`tracker_alert/client/peopleforce_api.py`):

- Синхронізація організаційної структури
- 4-рівнева ієрархія (Division → Direction → Unit → Team)
- HR дані (position, location, team_lead)

### 4. Data Management

**user_schedules.json** (132KB, 170+ співробітників):

```json
{
  "users": {
    "Employee Name": {
      "user_name": "Employee Name",
      "email": "user@example.com",
      "user_id": "7933838",
      "peopleforce_id": 554820,
      "start_time": "10:00",
      "location": "Warsaw office",
      "control_manager": 2,
      "division_name": "Apps",
      "direction_name": "Product Team",
      "unit_name": "IOS Unit",
      "team_name": "Development",
      "project": "Apps",
      "department": "Product Team",
      "unit": "IOS Unit",
      "team": "Development",
      "position": "Developer",
      "team_lead": "Manager Name",
      "manager_telegram": "manager_tg",
      "telegram_username": "employee_tg",
      "_manual_overrides": {
        "control_manager": true
      }
    }
  }
}
```

**Level_Grade.json** (562 записи):

- Довідник для адаптації даних
- Мапування Manager → Division/Direction/Unit/Team
- Нормалізація назв ("APPS Division" → "Apps")

**dashboard.db** (SQLite, 1.9MB):

- `attendance_records` - ~50K+ записів
- `users` - адміни та control managers
- `admin_audit_logs` - аудит дій

### 5. Background Tasks

- **Attendance Updates**: Щоденне оновлення з YaWare (tasks/update_attendance.py)
- **Google Sheets Export**: Щоденний/тижневий експорт (tracker_alert/scripts/)
- **Telegram Bot**: Алерти та нотифікації (tracker_alert/bot/)

### 6. Utilities & Scripts

**Deployment**:

- `scripts/backup_database.sh` - backup БД
- `scripts/pull_from_server.sh` - синхронізація з сервером
- `scripts/setup_protection.sh` - захист БД

**Migrations**:

- `tracker_alert/scripts/add_is_control_manager_column.py`
- `tracker_alert/scripts/sync_peopleforce_telegram.py`

## 🔧 Технічні деталі

### Залежності (requirements.txt)

**Core**:

- Flask 3.1.0 - веб-фреймворк
- SQLAlchemy 2.0.36 - ORM
- Flask-Login 0.6.3 - аутентифікація

**APIs**:

- requests 2.32.3 - HTTP клієнт
- google-api-python-client - Google Sheets
- python-telegram-bot 21.9 - Telegram бот

**Reports**:

- openpyxl 3.1.5 - Excel генерація
- reportlab 4.2.5 - PDF генерація

**Utils**:

- python-dotenv 1.0.1 - .env конфігурація
- APScheduler 3.11.0 - планувальник задач

### База даних

**Моделі**:

1. **AttendanceRecord**:

   - date, user_id, user_name, email
   - actual_hours, productive_hours, efficiency
   - lateness, note, control_manager
   - peopleforce_id, location, start_time

2. **User**:

   - email, name, password_hash
   - is_admin, is_control_manager
   - manager_filter (для фільтрації даних)

3. **AdminAuditLog**:
   - admin_user_id, action, details
   - timestamp

### API Endpoints

**Public**:

- `GET /` - головна панель
- `POST /login` - вхід
- `GET /logout` - вихід

**Protected**:

- `GET /api/attendance` - дані відвідуваності
- `GET /api/attendance/excel` - Excel експорт
- `GET /api/attendance/pdf` - PDF експорт
- `PATCH /api/attendance/<id>` - оновлення нотатки

**Admin**:

- `GET /admin` - адмін панель
- `GET /api/admin/employees` - список співробітників
- `PATCH /api/admin/employees/<id>` - редагування
- `DELETE /api/admin/employees/<id>` - видалення
- `POST /api/admin/employees/<key>/sync` - синхронізація з PeopleForce
- `POST /api/admin/employees/<key>/adapt` - адаптація через Level_Grade.json
- `POST /api/admin/sync/users` - масова синхронізація
- `DELETE /api/admin/attendance/<date>` - видалення дати

## 📈 Статистика проекту

- **Загальний код**: ~15K+ рядків Python
- **Frontend**: ~2.5K рядків JavaScript
- **Співробітників**: 170+ в базі
- **Attendance records**: 50K+
- **API endpoints**: 30+
- **Документація**: 7 MD файлів
  - Location-based scheduling

---

**Останнє оновлення:** 9 жовтня 2025 р.
