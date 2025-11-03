# YaWare API v2 - Документація

## 📋 Загальна інформація

**Base URL:** `https://api.yaware.com.ua/`  
**Версія:** v2  
**Аутентифікація:** API Token в заголовку `Authorization: Token YOUR_API_TOKEN`

## 🔧 Налаштування

```python
from tracker_alert.client.yaware_v2_api import YaWareV2Client

client = YaWareV2Client()
```

Конфігурація в `tracker_alert/config/settings.py`:

```python
yaware_api_token = "YOUR_API_TOKEN"
yaware_base_url = "https://api.yaware.com.ua/"
```

---

## 📡 Доступні Endpoints

### 1. `getSummaryByDay` - Отримати денний звіт

**Метод:** `client.get_summary_by_day(date)`

**Опис:** Повертає зведені дані про роботу всіх користувачів за конкретний день.

**Параметри:**

- `date` (str або datetime.date): Дата у форматі `YYYY-MM-DD` або об'єкт date

**Що повертає:**

```json
{
  "users": [
    {
      "id": 7667047,
      "full_name": "Leonid Chernov, eo_sup@evadav.com",
      "productive_time": 28800, // секунди
      "unproductive_time": 3600,
      "neutral_time": 1800,
      "offline_time": 0,
      "total_time": 34200,
      "lateness": 0, // хвилини запізнення
      "early_leave": 0, // хвилини раннього відходу
      "schedule": {
        "start_time": "09:00",
        "end_time": "18:00"
      }
    }
  ]
}
```

**Приклад використання:**

```python
from datetime import date

# Отримати дані за вчора
data = client.get_summary_by_day(date(2025, 10, 9))

# Обробити користувачів
for user in data.get("users", []):
    user_id = user["id"]
    full_name = user["full_name"]  # Формат: "Name Surname, email@example.com"
    lateness = user.get("lateness", 0)

    # Розділити ім'я та email
    if ", " in full_name:
        name, email = full_name.split(", ", 1)
    else:
        name = full_name
        email = None
```

**Особливості:**

- ✅ Працює для будь-якої дати (минулої, поточної)
- ✅ Повертає ВСІХ активних користувачів за цей день
- ✅ Включає інформацію про запізнення (lateness) та ранній відхід (early_leave)
- ✅ Формат `full_name`: "Name Surname, email@example.com"
- ⚠️ Якщо користувач не працював у цей день - його не буде в списку
- ⚠️ Час у секундах, запізнення у хвилинах

**Коли використовувати:**

- Щоденні звіти про присутність
- Аналіз запізнень
- Підрахунок робочих годин
- Отримання списку активних користувачів

---

### 2. `getWeekSummary` - Отримати тижневий звіт

**Метод:** `client.get_week_summary(start_date, end_date)`

**Опис:** Повертає зведені дані за тиждень або довільний період.

**Параметри:**

- `start_date` (str або datetime.date): Початкова дата періоду
- `end_date` (str або datetime.date): Кінцева дата періоду

**Що повертає:**

```json
{
  "users": [
    {
      "id": 7667047,
      "full_name": "Leonid Chernov, eo_sup@evadav.com",
      "days": [
        {
          "date": "2025-10-07",
          "productive_time": 28800,
          "unproductive_time": 3600,
          "total_time": 34200,
          "lateness": 15,
          "early_leave": 0
        },
        {
          "date": "2025-10-08",
          "productive_time": 30000,
          "unproductive_time": 2400,
          "total_time": 34200,
          "lateness": 0,
          "early_leave": 10
        }
      ],
      "week_totals": {
        "productive_time": 144000,
        "total_days": 5,
        "lateness_count": 2
      }
    }
  ]
}
```

**Приклад використання:**

```python
from datetime import date, timedelta

# Отримати дані за поточний тиждень
today = date.today()
start_of_week = today - timedelta(days=today.weekday())
end_of_week = start_of_week + timedelta(days=4)  # П'ятниця

data = client.get_week_summary(start_of_week, end_of_week)

for user in data.get("users", []):
    user_id = user["id"]
    days = user.get("days", [])

    total_lateness = sum(day.get("lateness", 0) for day in days)
    print(f"{user['full_name']}: {total_lateness} хвилин запізнення за тиждень")
```

**Особливості:**

- ✅ Може охоплювати будь-який період (не обов'язково тиждень)
- ✅ Включає деталізацію по кожному дню
- ✅ Зведені підсумки за період
- ⚠️ Великі періоди (>30 днів) можуть працювати повільно
- ⚠️ Користувачі які не працювали жодного дня - не включаються

**Коли використовувати:**

- Тижневі звіти
- Аналіз трендів
- Експорт в Google Sheets
- Порівняння продуктивності

---

### 3. Інші можливі endpoints (не перевірені)

**Примітка:** YaWare API v2 має обмежену документацію. Наступні endpoints можуть існувати:

- `/v2/users` - список всіх користувачів
- `/v2/reports/detailed` - детальні звіти
- `/v2/schedules` - розклади роботи
- `/v2/departments` - відділи/департаменти

**Як перевірити:**

```python
# Спробувати запит до endpoint
try:
    data = client._get("/v2/users")
    print("Endpoint працює:", data)
except Exception as e:
    print("Endpoint не працює:", e)
```

---

## 🎯 Практичні приклади

### Приклад 1: Щоденний звіт про запізнення

```python
from datetime import date, timedelta
from tracker_alert.client.yaware_v2_api import YaWareV2Client

client = YaWareV2Client()
yesterday = date.today() - timedelta(days=1)

# Отримати дані
data = client.get_summary_by_day(yesterday)

# Знайти тих хто запізнився
late_users = []
for user in data.get("users", []):
    lateness = user.get("lateness", 0)
    if lateness > 0:
        name = user["full_name"].split(", ")[0]
        late_users.append({
            "name": name,
            "lateness": lateness,
            "email": user["full_name"].split(", ")[1] if ", " in user["full_name"] else None
        })

# Вивести результат
print(f"📊 Запізнення за {yesterday}:")
for user in sorted(late_users, key=lambda x: x["lateness"], reverse=True):
    print(f"  • {user['name']}: {user['lateness']} хв")
```

### Приклад 2: Тижневий звіт з експортом

```python
from datetime import date, timedelta
from tracker_alert.client.yaware_v2_api import YaWareV2Client
import json

client = YaWareV2Client()

# Визначити тиждень
today = date.today()
start = today - timedelta(days=today.weekday())
end = start + timedelta(days=4)

# Отримати дані
weekly_data = client.get_week_summary(start, end)

# Сформувати звіт
report = {
    "period": f"{start} - {end}",
    "users": []
}

for user in weekly_data.get("users", []):
    name, email = user["full_name"].split(", ", 1) if ", " in user["full_name"] else (user["full_name"], None)

    user_report = {
        "name": name,
        "email": email,
        "total_days": len(user.get("days", [])),
        "total_lateness": sum(day.get("lateness", 0) for day in user.get("days", [])),
        "total_hours": sum(day.get("total_time", 0) for day in user.get("days", [])) / 3600
    }

    report["users"].append(user_report)

# Зберегти в файл
with open("weekly_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=2)

print(f"✅ Звіт за {start} - {end} збережено")
```

### Приклад 3: Оновлення бази користувачів

```python
from datetime import date
from tracker_alert.client.yaware_v2_api import YaWareV2Client
import json

client = YaWareV2Client()

# Отримати активних користувачів за сьогодні
today_data = client.get_summary_by_day(date.today())

# Завантажити базу
with open("config/user_schedules.json", "r", encoding="utf-8") as f:
    database = json.load(f)

# Оновити user_id та email
updated = 0
for user in today_data.get("users", []):
    user_id = user["id"]
    full_name = user["full_name"]

    # Розділити ім'я та email
    if ", " in full_name:
        name, email = full_name.split(", ", 1)
    else:
        name = full_name
        email = None

    # Спробувати знайти в базі (різні формати імені)
    name_variants = [
        name,  # "Name Surname"
        " ".join(reversed(name.split())),  # "Surname Name"
    ]

    for name_variant in name_variants:
        if name_variant in database["users"]:
            if not database["users"][name_variant].get("user_id"):
                database["users"][name_variant]["user_id"] = user_id
                updated += 1

            if email and not database["users"][name_variant].get("email"):
                database["users"][name_variant]["email"] = email
                updated += 1
            break

# Зберегти
if updated > 0:
    with open("config/user_schedules.json", "w", encoding="utf-8") as f:
        json.dump(database, f, ensure_ascii=False, indent=2)
    print(f"✅ Оновлено {updated} записів")
else:
    print("ℹ️ Нічого не потрібно оновлювати")
```

---

## 🔍 Корисні деталі

### Формат даних користувача

YaWare повертає `full_name` у форматі: **"Name Surname, email@example.com"**

**Приклади:**

- `"Anton Popovych, a.popovych@evadav.com"`
- `"Leonid Chernov, eo_sup@evadav.com"`
- `"Abdulaziz Abdurazzakov, abdulaziz@evadav.com"`

**Як парсити:**

```python
full_name = "Anton Popovych, a.popovych@evadav.com"

if ", " in full_name:
    name, email = full_name.split(", ", 1)
else:
    name = full_name
    email = None
```

### Час та одиниці виміру

| Параметр            | Одиниця виміру | Приклад             |
| ------------------- | -------------- | ------------------- |
| `productive_time`   | секунди        | `28800` = 8 годин   |
| `unproductive_time` | секунди        | `3600` = 1 година   |
| `total_time`        | секунди        | `34200` = 9.5 годин |
| `lateness`          | хвилини        | `15` = 15 хвилин    |
| `early_leave`       | хвилини        | `10` = 10 хвилин    |

**Конвертація:**

```python
# Секунди -> Години
hours = seconds / 3600

# Секунди -> Хвилини
minutes = seconds / 60

# Хвилини -> Години:Хвилини
hours = minutes // 60
mins = minutes % 60
formatted = f"{hours}:{mins:02d}"
```

### User ID

- **user_id** - унікальний числовий ідентифікатор в YaWare
- Приклад: `7667047`
- Використовується для зв'язку з базою даних
- Можна отримати тільки коли користувач активний (працює в цей день)

### Lateness Detection

YaWare автоматично визначає запізнення якщо:

1. У користувача є розклад (schedule)
2. Користувач почав працювати пізніше за `schedule.start_time`

**Приклад:**

- Розклад: 09:00 - 18:00
- Користувач увійшов: 09:15
- Lateness: 15 хвилин

---

## ⚠️ Обмеження та особливості

### ✅ Що працює:

- `getSummaryByDay` - денні звіти
- `getWeekSummary` - тижневі звіти (довільний період)
- Автоматичне визначення запізнень
- Email та user_id в відповіді

### ⚠️ Особливості:

- API повертає лише користувачів які працювали в цей день
- Неактивні користувачі відсутні в відповіді
- Формат імені може відрізнятися від бази даних
- Великі періоди (>30 днів) можуть бути повільними

### ❌ Що НЕ працює / Невідомо:

- Список ВСІХ користувачів (незалежно від активності)
- Отримання розкладів окремо
- Детальна активність (які програми використовувалися)
- API для керування користувачами

### 🔒 Rate Limits:

- Не задокументовано
- Рекомендується робити паузи між запитами
- Використовувати кешування для часто використовуваних даних

---

## 🛠️ Рекомендації

### 1. Кешування

Зберігайте дані локально щоб зменшити кількість запитів:

```python
import json
from datetime import date

cache_file = f"cache/yaware_{date.today()}.json"

# Спробувати завантажити з кешу
try:
    with open(cache_file, "r") as f:
        data = json.load(f)
except FileNotFoundError:
    # Якщо кешу немає - запросити API
    data = client.get_summary_by_day(date.today())
    with open(cache_file, "w") as f:
        json.dump(data, f)
```

### 2. Обробка помилок

Завжди обробляйте можливі помилки:

```python
from requests.exceptions import RequestException

try:
    data = client.get_summary_by_day(date.today())
except RequestException as e:
    print(f"Помилка API: {e}")
    # Відправити сповіщення, використати резервні дані тощо
```

### 3. Smart Matching

Використовуйте розумне співставлення імен:

```python
def normalize_name(name):
    """Нормалізує ім'я для пошуку."""
    return name.lower().strip()

def smart_match(yaware_name, database_names):
    """Знайти співпадіння в базі з урахуванням різних форматів."""
    normalized = normalize_name(yaware_name)

    # Спробувати точне співпадіння
    for db_name in database_names:
        if normalize_name(db_name) == normalized:
            return db_name

    # Спробувати зворотний порядок слів
    words = yaware_name.split()
    if len(words) == 2:
        reversed_name = f"{words[1]} {words[0]}"
        for db_name in database_names:
            if normalize_name(db_name) == normalize_name(reversed_name):
                return db_name

    return None
```

---

## 📞 Підтримка

- **Клас:** `tracker_alert.client.yaware_v2_api.YaWareV2Client`
- **Налаштування:** `tracker_alert.config.settings`
- **Документація проекту:** `README.md`, `PROJECT_STRUCTURE.md`

**Корисні файли:**

- `tracker_alert/scripts/export_daily_v2.py` - щоденний експорт
- `tracker_alert/scripts/export_weekly.py` - тижневий експорт
- `tracker_alert/scripts/update_yesterday.py` - оновлення даних за вчора
- `config/user_schedules.json` - база користувачів

---

**Останнє оновлення:** 10 жовтня 2025  
**Версія документу:** 1.0
