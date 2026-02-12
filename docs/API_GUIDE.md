# API Integration Guide

Документація по інтеграції з YaWare API v2 та PeopleForce API.

## 📋 Зміст

- [YaWare API v2](#yaware-api-v2)
- [PeopleForce API](#peopleforce-api)
- [Практичні приклади](#практичні-приклади)

---

## YaWare API v2

### Загальна інформація

**Base URL:** `https://api.yaware.com.ua/`  
**Версія:** v2  
**Аутентифікація:** API Token в заголовку `Authorization: Token YOUR_API_TOKEN`

### Налаштування

```python
from tracker_alert.client.yaware_v2_api import YaWareV2Client

client = YaWareV2Client()
```

Конфігурація в `tracker_alert/config/settings.py`:

```python
yaware_api_token = "YOUR_API_TOKEN"
yaware_base_url = "https://api.yaware.com.ua/"
```

### Доступні Endpoints

#### 1. `getSummaryByDay` - Отримати денний звіт

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
      "full_name": "Example User, user@example.com",
      "productive_time": 28800,
      "unproductive_time": 3600,
      "neutral_time": 1800,
      "offline_time": 0,
      "total_time": 34200,
      "lateness": 0,
      "early_leave": 0,
      "schedule": {
        "start_time": "09:00",
        "end_time": "18:00"
      }
    }
  ]
}
```

**Особливості:**
- ✅ Працює для будь-якої дати (минулої, поточної)
- ✅ Повертає ВСІХ активних користувачів за цей день
- ✅ Включає інформацію про запізнення (lateness) та ранній відхід (early_leave)
- ✅ Формат `full_name`: "Name Surname, email@example.com"
- ⚠️ Якщо користувач не працював у цей день - його не буде в списку
- ⚠️ Час у секундах, запізнення у хвилинах

#### 2. `getWeekSummary` - Отримати тижневий звіт

**Метод:** `client.get_week_summary(start_date, end_date)`

**Опис:** Повертає зведені дані за тиждень або довільний період.

**Параметри:**
- `start_date` (str або datetime.date): Початкова дата періоду
- `end_date` (str або datetime.date): Кінцева дата періоду

**Особливості:**
- ✅ Може охоплювати будь-який період (не обов'язково тиждень)
- ✅ Включає деталізацію по кожному дню
- ✅ Зведені підсумки за період
- ⚠️ Великі періоди (>30 днів) можуть працювати повільно

### Формат даних

YaWare повертає `full_name` у форматі: **"Name Surname, email@example.com"**

**Приклади:**
- `"Example User, user@example.com"`
- `"John Doe, john.doe@example.com"`
- `"Jane Smith, jane.smith@example.com"`

**Як парсити:**

```python
full_name = "Example User, user@example.com"

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

---

## PeopleForce API

### Загальна інформація

**Base URL:** `https://example.peopleforce.io/api/v2`  
**Версія:** v2  
**Аутентифікація:** API Key в заголовку `X-API-KEY: YOUR_API_KEY`

### Налаштування

```python
from tracker_alert.client.peopleforce_api import PeopleForceClient

client = PeopleForceClient()
```

Конфігурація в `tracker_alert.config.settings`:

```python
peopleforce_api_key = "YOUR_API_KEY"
peopleforce_base_url = "https://example.peopleforce.io/api/v2"
```

### Доступні Endpoints

#### 1. `/employees` - Список співробітників

**Метод:** `client.get_employees(force_refresh=False)`

**Опис:** Повертає список всіх співробітників компанії з їх даними.

**Параметри:**
- `force_refresh` (bool): Примусово оновити кеш (за замовчуванням False)

**Підтримує пагінацію:**

```python
# Автоматична пагінація (отримує всі сторінки)
employees = client.get_employees()
```

**Що повертає:**

```json
[
  {
    "id": 297352,
    "status": "employed",
    "access": true,
    "full_name": "Example User",
    "first_name": "Example",
    "last_name": "User",
    "email": "user@example.com",
    "position": {
      "id": 197719,
      "name": "Software Engineer"
    },
    "location": {
      "id": 50061,
      "name": "Remote Ukraine"
    },
    "division": {
      "id": 33076,
      "name": "Apps"
    },
    "department": {
      "id": 78455,
      "name": "Product Team"
    },
    "reporting_to": {
      "id": 297353,
      "first_name": "Manager",
      "last_name": "Name",
      "email": "manager@example.com"
    }
  }
]
```

**Статуси співробітників:**
- `employed` - працює
- `probation` - на випробувальному терміні
- `dismissed` - звільнений
- `on_leave` - у відпустці

**Особливості:**
- ✅ Кешування (5 хвилин) для швидкодії
- ✅ Автоматична пагінація (до 50 сторінок по 100 записів)
- ✅ Повертає всіх співробітників (навіть неактивних)

#### 2. `/employees/{id}` - Детальна інформація про співробітника

**Метод:** Прямий запит через `client._get(f"/employees/{employee_id}")`

**Опис:** Повертає детальну інформацію про конкретного співробітника.

#### 3. `/leaves` - Відпустки та відсутності

**Метод:** `client.get_leave_requests(start_date, end_date)`

**Опис:** Повертає список заявок на відпустку/відсутність за період.

**Параметри:**
- `start_date` (str або datetime.date): Початкова дата періоду (формат: YYYY-MM-DD)
- `end_date` (str або datetime.date): Кінцева дата періоду (формат: YYYY-MM-DD)

**Типи відсутності:**
- `Vacation` - відпустка
- `Sick Leave` - лікарняний
- `Day Off` - вихідний
- `Remote Work` - віддалена робота
- `Business Trip` - відрядження

**Статуси:**
- `approved` - затверджено
- `pending` - очікує розгляду
- `rejected` - відхилено
- `cancelled` - скасовано

#### 4. `/assets` - Майно компанії (техніка)

**Метод:** Прямий запит через `client._get("/assets")`

**Опис:** Повертає список всього майна компанії (ноутбуки, телефони, тощо).

### Допоміжні методи

#### `get_employee_by_email(email)`

**Опис:** Знайти співробітника за email адресою.

**Приклад:**

```python
employee = client.get_employee_by_email("user@example.com")

if employee:
    print(f"Знайдено: {employee['full_name']}")
    print(f"Локація: {employee['location']['name']}")
else:
    print("Співробітник не знайдений")
```

#### `get_employees_on_leave(target_date)`

**Опис:** Отримати список співробітників у відпустці на конкретну дату.

**Приклад:**

```python
from datetime import date

# Хто у відпустці сьогодні?
on_leave_today = client.get_employees_on_leave(date.today())

print(f"У відпустці сьогодні: {len(on_leave_today)} співробітників")
```

---

## Практичні приклади

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

### Приклад 2: Співставлення локацій для експорту

```python
from tracker_alert.client.peopleforce_api import PeopleForceClient
from tracker_alert.client.yaware_v2_api import YaWareV2Client
from datetime import date

pf_client = PeopleForceClient()
yw_client = YaWareV2Client()

# Отримати дані з YaWare
yaware_data = yw_client.get_summary_by_day(date.today())

# Отримати співробітників PeopleForce
pf_employees = pf_client.get_employees()

# Створити словник email -> location
location_map = {}
for emp in pf_employees:
    if emp.get("email"):
        location_map[emp["email"]] = emp.get("location", {}).get("name", "Unknown")

# Додати локації до даних YaWare
for user in yaware_data.get("users", []):
    full_name = user["full_name"]
    if ", " in full_name:
        email = full_name.split(", ")[1]
        user["location"] = location_map.get(email, "Unknown")
```

### Приклад 3: Перевірка хто у відпустці цього тижня

```python
from tracker_alert.client.peopleforce_api import PeopleForceClient
from datetime import date, timedelta

client = PeopleForceClient()

# Визначити тиждень
today = date.today()
start_of_week = today - timedelta(days=today.weekday())
end_of_week = start_of_week + timedelta(days=4)

# Отримати відпустки
leaves = client.get_leave_requests(start_of_week, end_of_week)

print(f"📅 Відпустки {start_of_week} - {end_of_week}:")
for leave in leaves:
    if leave["status"] == "approved":
        emp = leave["employee"]
        leave_type = leave["leave_type"]["name"]
        print(f"  • {emp['first_name']} {emp['last_name']}: {leave_type} ({leave['days_count']} днів)")
```

---

## ⚠️ Обмеження та особливості

### YaWare API

**✅ Що працює:**
- `getSummaryByDay` - денні звіти
- `getWeekSummary` - тижневі звіти (довільний період)
- Автоматичне визначення запізнень

**⚠️ Особливості:**
- API повертає лише користувачів які працювали в цей день
- Неактивні користувачі відсутні в відповіді
- Великі періоди (>30 днів) можуть бути повільними

### PeopleForce API

**✅ Що працює:**
- `/employees` - список всіх співробітників
- `/employees/{id}` - деталі конкретного співробітника
- `/leaves` - відпустки та відсутності
- `/assets` - майно компанії
- Пагінація для employees
- Кешування для швидкодії

**⚠️ Особливості:**
- Кеш може повертати застарілі дані (force_refresh=True для оновлення)
- Майно (assets) не включене в профіль співробітника (окремий endpoint)

---

## 🛠️ Рекомендації

### Кешування

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

### Обробка помилок

Завжди обробляйте можливі помилки:

```python
from requests.exceptions import RequestException

try:
    data = client.get_summary_by_day(date.today())
except RequestException as e:
    print(f"Помилка API: {e}")
    # Відправити сповіщення, використати резервні дані тощо
```

---

## 📞 Підтримка

- **YaWare API:** Звертайтесь до YaWare Support
- **PeopleForce API:** Документація доступна в адмін-панелі PeopleForce

**Корисні файли:**
- `tracker_alert/client/yaware_v2_api.py` - YaWare API клієнт
- `tracker_alert/client/peopleforce_api.py` - PeopleForce API клієнт
- `tracker_alert/config/settings.py` - Налаштування

---

**Останнє оновлення:** 2025-02-04
