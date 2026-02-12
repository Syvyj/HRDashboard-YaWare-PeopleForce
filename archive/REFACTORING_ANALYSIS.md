# Аналіз рефакторингу API та рекомендації

**Дата аналізу:** 2 січня 2026  
**Версія:** Post-refactoring (модульна структура)

## Огляд змін

### Структура до рефакторингу

```
dashboard_app/
  api.py (5330+ рядків - монолітний файл)
```

### Структура після рефакторингу

```
dashboard_app/api/
  __init__.py
  attendance.py
  audit.py
  employees.py
  lateness.py
  notes.py
  reports.py
  scheduler.py
  sync.py
  users.py
  utils.py
  services/
    attendance_service.py
```

---

## Виявлені баги під час тестування

### 1. ❌ Критичний баг: Дублювання роутів (ВИПРАВЛЕНО)

**Проблема:**

```python
# В reports.py обидва роути вказували на одну функцію
@reports_bp.route('/report/pdf', methods=['GET'])
@reports_bp.route('/monthly-report/pdf', methods=['GET'])
def export_monthly_report_pdf():  # Тільки місячний звіт!
```

**Симптоми:**

- Всі експорти (dashboard, user detail, monthly) генерували місячний звіт
- Користувачі не могли отримати тижневі звіти

**Рішення:**

- Створено окремі функції: `export_report_pdf()` та `export_monthly_report_pdf()`
- Відновлено правильний формат таблиць з бекапу

**Статус:** ✅ Виправлено

---

### 2. ❌ Помилка імпорту: MANUAL_FLAG_MAP (ВИПРАВЛЕНО)

**Проблема:**

```python
# utils.py використовує MANUAL_FLAG_MAP
for flag_key, flag_name in MANUAL_FLAG_MAP.items()

# Але імпорт був видалений
from dashboard_app.constants import WEEK_TOTAL_USER_ID_SUFFIX  # MANUAL_FLAG_MAP відсутній!
```

**Симптоми:**

```
NameError: name 'MANUAL_FLAG_MAP' is not defined
```

- 500 Internal Server Error при відкритті карток користувачів
- Неможливість серіалізувати attendance records

**Причина:**

- `MANUAL_FLAG_MAP` критично важливий для захисту даних, які редагували контрол-менеджери
- Без цього мапінгу система не може відстежувати ручні зміни

**Рішення:**

- Повернуто імпорт: `from dashboard_app.constants import MANUAL_FLAG_MAP`
- Переконатися що `constants.py` з MANUAL_FLAG_MAP є на сервері

**Статус:** ✅ Виправлено

---

### 3. ❌ Проблема зі шрифтами PDF (ВИПРАВЛЕНО)

**Проблема:**

- Кирилиця відображалась як квадратики в PDF
- Відсутні шрифти Roboto в `static/fonts/`

**Рішення:**

- Реалізовано систему пошуку системних шрифтів з підтримкою кирилиці:
  - Arial Unicode
  - Arial
  - DejaVu Sans
  - Liberation Sans
- Додано кешування зареєстрованих шрифтів
- Fallback на Helvetica якщо нічого не знайдено

**Статус:** ✅ Виправлено

---

## Потенційні проблеми та рекомендації

### 🔴 Високий пріоритет

#### 1. Відсутність API versioning

**Проблема:**

- Всі routes без версії: `/api/attendance`, `/api/report/pdf`
- При необхідності змін breaking changes неможливі без downtime

**Рекомендація:**

```python
# Додати версію в URL
@reports_bp.route('/v1/report/pdf')
# Або через header
# API-Version: 1.0
```

**Ризики:**

- Неможливість паралельного існування старої і нової версій API
- Проблеми при оновленні frontend/mobile клієнтів

---

#### 2. Відсутність rate limiting

**Проблема:**

```python
@reports_bp.route('/monthly-report', methods=['GET'])
def get_monthly_report():
    # Важкий query без обмежень
    query = AttendanceRecord.query.filter(...)
```

**Рекомендація:**

- Додати Flask-Limiter

```python
from flask_limiter import Limiter

limiter = Limiter(
    app,
    key_func=lambda: current_user.id,
    default_limits=["200 per hour", "50 per minute"]
)

@limiter.limit("10 per minute")
@reports_bp.route('/monthly-report/pdf')
def export_monthly_report_pdf():
    ...
```

**Ризики:**

- DOS атаки через генерацію PDF/Excel
- Перевантаження бази даних

---

#### 3. Відсутність валідації вхідних даних

**Проблема:**

```python
@attendance_bp.route('/users/<path:user_key>')
def api_user_detail(user_key: str):
    # Немає перевірки формату user_key
    query, normalized_key = _apply_user_key_filter(base_query, user_key)
```

**Рекомендація:**

- Використати Marshmallow/Pydantic для валідації

```python
from marshmallow import Schema, fields, validate

class UserKeySchema(Schema):
    user_key = fields.Str(required=True, validate=validate.Length(min=1, max=255))
```

**Ризики:**

- SQL injection (хоча використовується ORM)
- Некоректні дані в логах
- 500 помилки замість 400 Bad Request

---

#### 4. Неконсистентна обробка помилок

**Проблема:**

```python
# В одних місцях
return jsonify({'error': 'Not found'}), 404

# В інших
abort(404)

# А деінде просто exception
raise ValueError("Invalid data")
```

**Рекомендація:**

```python
# Створити централізований error handler
@api_bp.errorhandler(ValueError)
def handle_validation_error(e):
    return jsonify({'error': str(e), 'type': 'validation_error'}), 400

@api_bp.errorhandler(404)
def handle_not_found(e):
    return jsonify({'error': 'Resource not found', 'type': 'not_found'}), 404
```

---

### 🟡 Середній пріоритет

#### 5. Дублювання коду між old і new API

**Проблема:**

```python
# Full backup 30_11/dashboard_app/api.py все ще існує
# Може виникнути плутанина що використовувати
```

**Рекомендація:**

- Видалити старий `api.py` після повного тестування
- Створити git tag для backup версії
- Документувати міграцію в CHANGELOG.md

---

#### 6. Відсутність документації API

**Проблема:**

- Немає OpenAPI/Swagger документації
- Frontend розробники мають гадати про формати

**Рекомендація:**

```python
# Додати flask-restx або flasgger
from flask_restx import Api, Resource, fields

api = Api(api_bp, version='1.0', title='YaWare Dashboard API',
          description='Attendance tracking and reporting')

user_model = api.model('User', {
    'user_name': fields.String,
    'user_email': fields.String,
    ...
})
```

---

#### 7. N+1 query проблеми

**Проблема:**

```python
# В _serialize_attendance_record() для кожного record
schedule = _get_schedule_for_record(record)  # Може робити додатковий query

# При ітерації по 100+ records = 100+ queries
for record in records:
    _serialize_attendance_record(record)
```

**Рекомендація:**

```python
# Використати joinedload або eager loading
from sqlalchemy.orm import joinedload

records = query.options(
    joinedload(AttendanceRecord.user_schedule)
).all()
```

---

#### 8. Відсутність кешування для важких операцій

**Проблема:**

```python
@reports_bp.route('/monthly-report')
def get_monthly_report():
    # Кожен запит робить повний скан AttendanceRecord таблиці
    query = AttendanceRecord.query.filter(...)
```

**Рекомендація:**

```python
from functools import lru_cache
from flask_caching import Cache

cache = Cache(app, config={'CACHE_TYPE': 'redis'})

@cache.memoize(timeout=300)  # 5 хвилин
def get_monthly_data(month_str, filters_hash):
    ...
```

---

### 🟢 Низький пріоритет

#### 9. Відсутність типізації у деяких функціях

**Проблема:**

```python
def _build_excel_rows(items: list[dict]) -> list[dict[str, object]]:
    # object - занадто загальний тип
```

**Рекомендація:**

```python
from typing import TypedDict

class ExcelRow(TypedDict):
    values: list[str | int | float]
    role: str
    index: int | None

def _build_excel_rows(items: list[dict]) -> list[ExcelRow]:
    ...
```

---

#### 10. Magic strings у коді

**Проблема:**

```python
if role == 'summary_period':
    ...
elif role == 'summary_team':
    ...
elif role == 'week_total':
    ...
```

**Рекомендація:**

```python
from enum import Enum

class ExcelRowRole(Enum):
    SUMMARY_PERIOD = 'summary_period'
    SUMMARY_TEAM = 'summary_team'
    WEEK_TOTAL = 'week_total'
    USER_HEADER = 'user_header'
    DATA = 'data'
```

---

#### 11. Відсутність логування для критичних операцій

**Проблема:**

```python
@reports_bp.route('/report/pdf')
def export_report_pdf():
    try:
        # Генерація PDF
        records, week_start = _get_filtered_items()
        # Немає логів скільки records, хто запросив, які фільтри
```

**Рекомендація:**

```python
@reports_bp.route('/report/pdf')
def export_report_pdf():
    logger.info(f"PDF export requested by user_id={current_user.id}, "
                f"filters={request.args.to_dict()}")
    try:
        records, week_start = _get_filtered_items()
        logger.info(f"Generated PDF with {len(records)} records")
```

---

#### 12. Hard-coded значення

**Проблема:**

```python
# В reports.py
-w 4  # Gunicorn workers
--timeout 120  # Timeout

# В коді
base_widths_mm = [30, 13, 12, 13, 13, 13, 13, 13, 13, 30]
```

**Рекомендація:**

- Винести в `config.py` або environment variables

```python
# config.py
class Config:
    PDF_COLUMN_WIDTHS = [30, 13, 12, 13, 13, 13, 13, 13, 13, 30]
    GUNICORN_WORKERS = int(os.getenv('WORKERS', 4))
    REQUEST_TIMEOUT = int(os.getenv('TIMEOUT', 120))
```

---

## Позитивні зміни після рефакторингу

### ✅ Що покращилось:

1. **Модульність**

   - Легше знайти код: attendance логіка в `attendance.py`
   - Простіше тестувати окремі модулі

2. **Separation of Concerns**

   - Utils винесені окремо
   - Services layer для бізнес-логіки

3. **Читабельність**

   - 500-900 рядків на файл замість 5330
   - Зрозуміліша структура імпортів

4. **Легше онбордити нових розробників**
   - Не треба читати 5k рядків коду
   - Чітка структура папок

---

## Рекомендації щодо deployment

### 🔧 Перед деплоєм завжди перевіряти:

1. **Імпорти**

```bash
# Перевірити чи всі константи існують
ssh user@server 'cd ~/www/YaWare_Bot && .venv/bin/python -c "from dashboard_app.constants import MANUAL_FLAG_MAP; print(MANUAL_FLAG_MAP)"'
```

2. **Database migrations**

```bash
# Якщо є зміни в models.py
flask db migrate -m "Description"
flask db upgrade
```

3. **Backup перед deployment**

```bash
# Завжди робити backup
ssh user@server 'cd ~/www/YaWare_Bot && tar czf ../backup_$(date +%Y%m%d_%H%M%S).tar.gz .'
```

4. **Graceful restart**

```bash
# Використовувати HUP сигнал замість kill
pkill -HUP -f "gunicorn.*master"
# Або
supervisorctl restart gunicorn
```

---

## Checklist для майбутніх рефакторингів

- [ ] Створити unit tests для критичних функцій
- [ ] Додати integration tests для API endpoints
- [ ] Налаштувати CI/CD pipeline
- [ ] Додати pre-commit hooks для type checking (mypy)
- [ ] Створити staging environment
- [ ] Документувати всі breaking changes
- [ ] Версіонувати API
- [ ] Додати monitoring (Sentry/DataDog)
- [ ] Налаштувати alerting для помилок
- [ ] Code review process

---

## Висновки

### Критичні ризики усунуті ✅

1. Дублювання роутів PDF export - виправлено
2. MANUAL_FLAG_MAP імпорт - виправлено
3. Кирилиця в PDF - виправлено

### Середні ризики (потребують уваги) ⚠️

1. Rate limiting - додати
2. Валідація вхідних даних - додати
3. API documentation - створити
4. N+1 queries - оптимізувати

### Низькі ризики (nice to have) 💡

1. Строга типізація - покращити
2. Magic strings - замінити на Enum
3. Логування - розширити
4. Hard-coded values - винести в config

**Загальна оцінка рефакторингу:** 8/10

- ✅ Покращена структура
- ✅ Легше підтримувати
- ⚠️ Потрібно додати тести
- ⚠️ Потрібно додати документацію

---

**Автор аналізу:** GitHub Copilot  
**Дата:** 2 січня 2026
