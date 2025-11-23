# PeopleForce API - Документація

## 📋 Загальна інформація

**Base URL:** `https://evadav.peopleforce.io/api/v2`  
**Версія:** v2  
**Аутентифікація:** API Key в заголовку `X-API-KEY: YOUR_API_KEY`

## 🔧 Налаштування

```python
from tracker_alert.client.peopleforce_api import PeopleForceClient

client = PeopleForceClient()
```

Конфігурація в `tracker_alert.config.settings`:

```python
peopleforce_api_key = "YOUR_API_KEY"
peopleforce_base_url = "https://evadav.peopleforce.io/api/v2"
```

---

## 📡 Доступні Endpoints

### 1. `/employees` - Список співробітників

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
    "full_name": "Abdurazzakov Abdulaziz",
    "first_name": "Abdulaziz",
    "middle_name": "",
    "last_name": "Abdurazzakov",
    "avatar_url": "https://cdn.peopleforce.io/...",
    "email": "abdulaziz@evadav.com",
    "personal_email": "personal@example.com",
    "date_of_birth": "1995-05-24",
    "probation_ends_on": null,
    "hired_on": "2021-02-11",
    "gender": {
      "id": 8809,
      "name": "male"
    },
    "position": {
      "id": 197719,
      "name": "TL AdEx"
    },
    "job_level": {
      "id": 17677,
      "name": "Team Lead"
    },
    "location": {
      "id": 50061,
      "name": "Remote Ukraine"
    },
    "employment_type": {
      "id": 14794,
      "name": "Full time"
    },
    "division": {
      "id": 33076,
      "name": "AD NETWORK"
    },
    "department": {
      "id": 78455,
      "name": "RTB"
    },
    "reporting_to": {
      "id": 297353,
      "first_name": "Maksim",
      "last_name": "Lazarenko",
      "email": "m.lazarenko@evadav.com"
    },
    "created_at": "2024-04-11T14:30:23.986Z",
    "updated_at": "2025-10-06T15:15:39.983Z"
  }
]
```

**Приклад використання:**

```python
# Отримати всіх співробітників
employees = client.get_employees()

print(f"Всього співробітників: {len(employees)}")

# Фільтрувати активних
active = [emp for emp in employees if emp["status"] == "employed"]
print(f"Активних: {len(active)}")

# Групувати по локаціях
from collections import defaultdict
by_location = defaultdict(list)

for emp in employees:
    location = emp.get("location", {}).get("name", "Unknown")
    by_location[location].append(emp["full_name"])

for location, names in sorted(by_location.items()):
    print(f"\n{location}: {len(names)} співробітників")
```

**Статуси співробітників:**

- `employed` - працює
- `probation` - на випробувальному терміні
- `dismissed` - звільнений
- `on_leave` - у відпустці

**Локації (приклади):**

- `Remote Ukraine` - віддалено з України
- `Remote other countries` - віддалено з інших країн
- `Prague office` - офіс у Празі
- `Warsaw, Poland` - офіс у Варшаві
- `Germany` - Німеччина

**Особливості:**

- ✅ Кешування (5 хвилин) для швидкодії
- ✅ Автоматична пагінація (до 50 сторінок по 100 записів)
- ✅ Повертає всіх співробітників (навіть неактивних)
- ⚠️ Базова відповідь не включає деталі про майно (assets)

---

### 2. `/employees/{id}` - Детальна інформація про співробітника

**Метод:** Прямий запит через `client._get(f"/employees/{employee_id}")`

**Опис:** Повертає детальну інформацію про конкретного співробітника.

**Параметри:**

- `employee_id` (int): ID співробітника в PeopleForce

**Що повертає:**

```json
{
  "data": {
    "id": 297352,
    "status": "employed",
    "full_name": "Abdurazzakov Abdulaziz",
    "email": "abdulaziz@evadav.com"
    // ... всі поля як в /employees
    // Можливо додаткові поля
  }
}
```

**Приклад використання:**

```python
# Отримати детальну інформацію
employee_id = 297352
data = client._get(f"/employees/{employee_id}")
employee = data.get("data", {})

print(f"Співробітник: {employee['full_name']}")
print(f"Посада: {employee['position']['name']}")
print(f"Email: {employee['email']}")
```

---

### 3. `/leaves` - Відпустки та відсутності

**Метод:** `client.get_leave_requests(start_date, end_date)`

**Опис:** Повертає список заявок на відпустку/відсутність за період.

**Параметри:**

- `start_date` (str або datetime.date): Початкова дата періоду (формат: YYYY-MM-DD)
- `end_date` (str або datetime.date): Кінцева дата періоду (формат: YYYY-MM-DD)

**Що повертає:**

```json
[
  {
    "id": 12345,
    "employee": {
      "id": 297352,
      "first_name": "Abdulaziz",
      "last_name": "Abdurazzakov",
      "email": "abdulaziz@evadav.com"
    },
    "leave_type": {
      "id": 123,
      "name": "Vacation"
    },
    "start_date": "2025-10-14",
    "end_date": "2025-10-18",
    "status": "approved",
    "days_count": 5,
    "comment": "Annual vacation"
  }
]
```

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

**Приклад використання:**

```python
from datetime import date, timedelta

# Отримати відпустки за поточний тиждень
today = date.today()
start_of_week = today - timedelta(days=today.weekday())
end_of_week = start_of_week + timedelta(days=4)

leaves = client.get_leave_requests(start_of_week, end_of_week)

print(f"Відпустки за {start_of_week} - {end_of_week}:")
for leave in leaves:
    if leave["status"] == "approved":
        emp = leave["employee"]
        leave_type = leave["leave_type"]["name"]
        print(f"  • {emp['first_name']} {emp['last_name']}: {leave_type} ({leave['days_count']} днів)")
```

**Особливості:**

- ✅ Включає тільки затверджені заявки (`status: approved`)
- ✅ Підтримує довільні періоди
- ⚠️ Не включає автоматичні вихідні (субота/неділя)
- ⚠️ Кешування (5 хвилин) для одного періоду

---

### 4. `/assets` - Майно компанії (техніка)

**Метод:** Прямий запит через `client._get("/assets")`

**Опис:** Повертає список всього майна компанії (ноутбуки, телефони, тощо).

**Що повертає:**

```json
{
  "data": [
    {
      "id": 657160,
      "name": "Apple Mac Book M4 Pro 24gb/512gb",
      "code": "187P",
      "serial_number": "ABCD1234567",
      "description": "MacBook Pro для розробника",
      "price": 2500.0,
      "currency_code": "USD",
      "location_id": 50062,
      "asset_category_id": 32000,
      "created_at": "2025-04-16T15:04:31.222Z",
      "updated_at": "2025-04-16T15:04:31.226Z",
      "warranity_expires_on": "2027-04-16",
      "asset_assignments": [
        {
          "id": 639306,
          "user_id": 460753,
          "asset_id": 656993,
          "issued_on": "2025-04-15",
          "returned_on": null,
          "created_at": "2025-04-15T16:07:17.167Z",
          "updated_at": "2025-04-15T16:07:17.167Z"
        }
      ]
    }
  ]
}
```

**Поля asset_assignments:**

- `user_id` - ID співробітника в PeopleForce
- `issued_on` - дата видачі
- `returned_on` - дата повернення (null = все ще у користувача)

**Приклад використання:**

```python
# Отримати всі активи
data = client._get("/assets")
assets = data.get("data", [])

print(f"Всього майна: {len(assets)}")

# Знайти активи призначені співробітнику
employee_id = 460753
employee_assets = []

for asset in assets:
    for assignment in asset.get("asset_assignments", []):
        if assignment["user_id"] == employee_id and assignment["returned_on"] is None:
            employee_assets.append({
                "name": asset["name"],
                "code": asset["code"],
                "issued_on": assignment["issued_on"]
            })

print(f"\nТехніка співробітника {employee_id}:")
for asset in employee_assets:
    print(f"  • {asset['name']} (код: {asset['code']}), видано: {asset['issued_on']}")

# Статистика
total_assigned = sum(1 for a in assets if a.get("asset_assignments"))
print(f"\nПризначено майна: {total_assigned} з {len(assets)}")
```

**Категорії майна (asset_category_id):**

- Ноутбуки
- Телефони
- Монітори
- Периферія (миші, клавіатури)
- Аксесуари

**Особливості:**

- ✅ Повертає ВСЕ майно компанії
- ✅ Включає історію призначень (assignments)
- ✅ Можна відстежити хто і коли отримав/повернув

---

## 🤖 Інтеграція з Telegram та дашбордом

### Автоматична синхронізація

- Працює щодня о **06:00** разом з іншими задачами PeopleForce (див. `dashboard_app/tasks.py::_sync_peopleforce_metadata`).
- Оновлює `telegram_username`, `manager_name`, `manager_telegram`, а також project/department/location/position/control_manager у `config/user_schedules.json`.
- Не перезаписує поля з manual overrides (адмінські правки в UI).

### UI та використання

- **Сторінка користувача** показує Telegram з клікабельним `@username` та блок “Руководитель” з посиланням на Telegram керівника.
- **Dashboard** має колонку Telegram (іконка + username) для швидкого відкриття чату.

### Ручний запуск

```bash
python3 scripts/sync_peopleforce_telegram.py
```

Скрипт створює локальний Flask-контекст, викликає `_sync_peopleforce_metadata` і відразу оновлює `user_schedules.json`, показуючи прогрес у консолі.

### Редагування адміністратором

1. Відкрити сторінку користувача.
2. Натиснути кнопку редагування біля Control manager / Telegram.
3. Ввести значення (`Прізвище_Ім'я` або `@username`).
4. Зберегти — у JSON стануть доступні нові дані та виставиться manual override.

### Джерела даних у PeopleForce

- Custom field “Рабочий телеграм” → `fields["1"].value`.
- `reporting_to` з `first_name`, `last_name`, `id` та власним полем Telegram (для керівника).
- Стандартні поля `division`, `department`, `location`, `position`.

### Кешування і логування

- `PeopleForceClient` кешує відповіді `/employees` та `/leave_requests` 5 хвилин.
- Деталі керівника кешуються в межах одного запуску, щоб не дублювати запити.
- Логи scheduler’а виглядають так:

```
[scheduler] Running PeopleForce metadata sync
[scheduler] Оновлено telegram для Kutkovskyi Mykhailo: @Kutkovskyi_Mykhailo
[scheduler] Оновлено manager_name для Kutkovskyi Mykhailo: Lazarenko_Maksim
```

### Обмеження та поради

1. Поле “Рабочий телеграм” має бути заповнене у PeopleForce, інакше в UI порожньо.
2. Керівник (`reporting_to`) повинен мати робочий Telegram, щоб `manager_telegram` відображався.
3. Якщо потрібен терміновий апдейт — запускайте CLI або редагуйте вручну (автосинк підхопить manual overrides).

### Troubleshooting

- **Telegram не відображається:** перевірте custom field, `peopleforce_id` користувача, запустіть `scripts/sync_peopleforce_telegram.py`.
- **Керівник відсутній:** переконайтеся, що `reporting_to` заданий і у керівника є Telegram.
- **API падає:** перевірте `PEOPLEFORCE_API_KEY`, мережевий доступ і логи (`dashboard_app/tasks.py`).
- ⚠️ Не має пагінації (поки що)
- ⚠️ Потребує додаткової обробки для зв'язку з користувачами

---

## 🔧 Допоміжні методи

### `get_employee_by_email(email)`

**Опис:** Знайти співробітника за email адресою.

**Параметри:**

- `email` (str): Email співробітника

**Повертає:** Словник з даними співробітника або `None`

**Приклад:**

```python
employee = client.get_employee_by_email("abdulaziz@evadav.com")

if employee:
    print(f"Знайдено: {employee['full_name']}")
    print(f"Локація: {employee['location']['name']}")
else:
    print("Співробітник не знайдений")
```

---

### `get_employees_on_leave(target_date)`

**Опис:** Отримати список співробітників у відпустці на конкретну дату.

**Параметри:**

- `target_date` (datetime.date): Дата для перевірки

**Повертає:** Список словників з інформацією про відсутність

**Приклад:**

```python
from datetime import date

# Хто у відпустці сьогодні?
on_leave_today = client.get_employees_on_leave(date.today())

print(f"У відпустці сьогодні: {len(on_leave_today)} співробітників")

for leave in on_leave_today:
    emp = leave["employee"]
    leave_type = leave["leave_type"]["name"]
    print(f"  • {emp['first_name']} {emp['last_name']}: {leave_type}")
```

---

## 🎯 Практичні приклади

### Приклад 1: Співставлення локацій для експорту

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

# Експортувати
print("Користувачі з локаціями:")
for user in yaware_data["users"]:
    name = user["full_name"].split(", ")[0]
    location = user.get("location", "Unknown")
    print(f"  • {name}: {location}")
```

### Приклад 2: Перевірка хто у відпустці цього тижня

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

# Згрупувати по днях
from collections import defaultdict
by_day = defaultdict(list)

for leave in leaves:
    if leave["status"] != "approved":
        continue

    # Розрахувати дні відпустки
    start = date.fromisoformat(leave["start_date"])
    end = date.fromisoformat(leave["end_date"])

    current = max(start, start_of_week)
    end_date = min(end, end_of_week)

    while current <= end_date:
        emp = leave["employee"]
        by_day[current].append({
            "name": f"{emp['first_name']} {emp['last_name']}",
            "type": leave["leave_type"]["name"]
        })
        current += timedelta(days=1)

# Вивести результат
print(f"📅 Відпустки {start_of_week} - {end_of_week}:\n")
current_date = start_of_week
while current_date <= end_of_week:
    day_name = current_date.strftime("%A")
    leaves_today = by_day.get(current_date, [])

    print(f"{current_date} ({day_name}):")
    if leaves_today:
        for leave in leaves_today:
            print(f"  • {leave['name']}: {leave['type']}")
    else:
        print("  Всі на місці")
    print()

    current_date += timedelta(days=1)
```

### Приклад 3: Отримати email з PeopleForce для користувачів без email

```python
from tracker_alert.client.peopleforce_api import PeopleForceClient
import json

client = PeopleForceClient()

# Завантажити базу користувачів
with open("config/user_schedules.json", "r", encoding="utf-8") as f:
    database = json.load(f)

# Отримати всіх співробітників PF
pf_employees = client.get_employees()

# Знайти користувачів без email
without_email = [
    name for name, data in database["users"].items()
    if not data.get("email")
]

print(f"Шукаємо email для {len(without_email)} користувачів...\n")

found = 0
for db_name in without_email:
    # Спробувати знайти в PF (різні варіанти імені)
    name_parts = db_name.split()

    for emp in pf_employees:
        emp_first = emp.get("first_name", "").lower()
        emp_last = emp.get("last_name", "").lower()

        # Перевірити різні комбінації
        if len(name_parts) == 2:
            if (name_parts[0].lower() == emp_first and name_parts[1].lower() == emp_last) or \
               (name_parts[1].lower() == emp_first and name_parts[0].lower() == emp_last):

                email = emp.get("email")
                if email:
                    print(f"✅ {db_name} → {email}")
                    database["users"][db_name]["email"] = email
                    found += 1
                    break

print(f"\n📊 Знайдено email для {found} користувачів")

# Зберегти оновлену базу
if found > 0:
    with open("config/user_schedules.json", "w", encoding="utf-8") as f:
        json.dump(database, f, ensure_ascii=False, indent=2)
    print("✅ База оновлена")
```

### Приклад 4: Звіт про техніку по співробітникам

```python
from tracker_alert.client.peopleforce_api import PeopleForceClient

client = PeopleForceClient()

# Отримати співробітників та майно
employees = client.get_employees()
assets_data = client._get("/assets")
assets = assets_data.get("data", [])

# Створити мапу user_id -> employee
emp_map = {emp["id"]: emp for emp in employees}

# Згрупувати майно по користувачах
user_assets = {}

for asset in assets:
    for assignment in asset.get("asset_assignments", []):
        # Тільки активні призначення
        if assignment["returned_on"] is not None:
            continue

        user_id = assignment["user_id"]

        if user_id not in user_assets:
            user_assets[user_id] = []

        user_assets[user_id].append({
            "name": asset["name"],
            "code": asset["code"],
            "issued_on": assignment["issued_on"]
        })

# Вивести звіт
print("📊 ЗВІТ ПРО ВИДАНУ ТЕХНІКУ\n")
print(f"{'Співробітник':<40} {'Техніка':<50} {'Код':<10} {'Видано'}")
print("=" * 120)

for user_id, assets_list in sorted(user_assets.items()):
    emp = emp_map.get(user_id)
    if not emp:
        continue

    emp_name = emp["full_name"]

    for i, asset in enumerate(assets_list):
        if i == 0:
            print(f"{emp_name:<40} {asset['name']:<50} {asset['code']:<10} {asset['issued_on']}")
        else:
            print(f"{'':<40} {asset['name']:<50} {asset['code']:<10} {asset['issued_on']}")

    print()

print(f"\n📊 Всього: {len(user_assets)} співробітників з виданою технікою")
```

---

## 🔍 Структура даних

### Співробітник (Employee)

```python
{
    # Основна інформація
    "id": int,                    # Унікальний ID
    "status": str,                # employed, probation, dismissed
    "access": bool,               # Чи має доступ до системи
    "full_name": str,             # "Прізвище Ім'я"
    "first_name": str,            # Ім'я
    "middle_name": str,           # По батькові
    "last_name": str,             # Прізвище
    "avatar_url": str,            # URL фото

    # Контакти
    "email": str,                 # Корпоративна пошта
    "personal_email": str,        # Особиста пошта
    "date_of_birth": str,         # YYYY-MM-DD

    # Робоча інформація
    "position": {                 # Посада
        "id": int,
        "name": str
    },
    "job_level": {                # Рівень
        "id": int,
        "name": str               # Team Lead, Senior, Junior
    },
    "location": {                 # Локація
        "id": int,
        "name": str               # Remote Ukraine, Prague office
    },
    "employment_type": {          # Тип зайнятості
        "id": int,
        "name": str               # Full time, Part time
    },
    "division": {                 # Дивізіон
        "id": int,
        "name": str
    },
    "department": {               # Відділ
        "id": int,
        "name": str
    },
    "reporting_to": {             # Керівник
        "id": int,
        "first_name": str,
        "last_name": str,
        "email": str
    },

    # Дати
    "hired_on": str,              # Дата найму YYYY-MM-DD
    "probation_ends_on": str,     # Кінець випробувального терміну
    "created_at": str,            # ISO 8601
    "updated_at": str             # ISO 8601
}
```

### Відпустка (Leave)

```python
{
    "id": int,                    # Унікальний ID заявки
    "employee": {                 # Співробітник
        "id": int,
        "first_name": str,
        "last_name": str,
        "email": str
    },
    "leave_type": {               # Тип відсутності
        "id": int,
        "name": str               # Vacation, Sick Leave, Day Off
    },
    "start_date": str,            # YYYY-MM-DD
    "end_date": str,              # YYYY-MM-DD
    "status": str,                # approved, pending, rejected, cancelled
    "days_count": int,            # Кількість днів
    "comment": str                # Коментар
}
```

### Майно (Asset)

```python
{
    "id": int,                    # Унікальний ID активу
    "name": str,                  # Назва
    "code": str,                  # Внутрішній код
    "serial_number": str,         # Серійний номер
    "description": str,           # Опис
    "price": float,               # Вартість
    "currency_code": str,         # USD, EUR, тощо
    "location_id": int,           # ID локації
    "asset_category_id": int,     # ID категорії
    "warranity_expires_on": str,  # Дата закінчення гарантії
    "created_at": str,            # ISO 8601
    "updated_at": str,            # ISO 8601
    "asset_assignments": [        # Призначення
        {
            "id": int,
            "user_id": int,       # ID співробітника
            "asset_id": int,
            "issued_on": str,     # Дата видачі YYYY-MM-DD
            "returned_on": str,   # Дата повернення (null = у користувача)
            "created_at": str,
            "updated_at": str
        }
    ]
}
```

---

## ⚠️ Обмеження та особливості

### ✅ Що працює:

- `/employees` - список всіх співробітників
- `/employees/{id}` - деталі конкретного співробітника
- `/leaves` - відпустки та відсутності
- `/assets` - майно компанії
- Пагінація для employees
- Кешування для швидкодії

### 🔥 Важливі особливості:

- **Пагінація:** Endpoints `/employees` підтримує пагінацію (page, per_page)
- **Кешування:** Дані кешуються на 5 хвилин для зменшення навантаження
- **Формат дат:** Всі дати у форматі ISO (YYYY-MM-DD або ISO 8601)
- **Формат імен:** "Прізвище Ім'я" (відрізняється від YaWare)

### ⚠️ Потенційні проблеми:

- Без пагінації API повертає тільки перші 50 записів
- Кеш може повертати застарілі дані (force_refresh=True для оновлення)
- Майно (assets) не включене в профіль співробітника (окремий endpoint)
- Не всі співробітники мають корпоративну email

### 📊 Статистика (станом на 10.10.2025):

- Всього співробітників: **203**
- Активні (employed): **138**
- На випробувальному (probation): **65**
- Одиниць майна: **50**
- Призначено майна: **36**

---

## 🛠️ Рекомендації

### 1. Використання кешу

Кеш автоматично працює 5 хвилин:

```python
# Перший запит - йде в API
employees = client.get_employees()

# Наступні запити протягом 5 хвилин - з кешу
employees = client.get_employees()

# Примусово оновити кеш
employees = client.get_employees(force_refresh=True)
```

### 2. Пагінація

Клієнт автоматично обробляє пагінацію:

```python
# Отримає ВСІ сторінки (до 50 сторінок по 100 записів)
employees = client.get_employees()
```

Якщо потрібно вручну:

```python
page = 1
all_employees = []

while page <= 50:
    data = client._get("/employees", params={'page': page, 'per_page': 100})
    employees = data.get("data", [])

    if not employees:
        break

    all_employees.extend(employees)
    page += 1
```

### 3. Обробка помилок

```python
from requests.exceptions import RequestException

try:
    employees = client.get_employees()
except RequestException as e:
    print(f"Помилка PeopleForce API: {e}")
    # Fallback logic
```

### 4. Співставлення з YaWare

```python
def match_employee(yaware_name, yaware_email, pf_employees):
    """Знайти співробітника PF по даним з YaWare."""

    # Спочатку по email (найточніше)
    for emp in pf_employees:
        if emp.get("email") == yaware_email:
            return emp

    # Потім по імені (різні формати)
    name_parts = yaware_name.split()
    if len(name_parts) == 2:
        for emp in pf_employees:
            emp_first = emp.get("first_name", "").lower()
            emp_last = emp.get("last_name", "").lower()

            # YaWare: "Name Surname", PF: "Surname Name"
            if (name_parts[0].lower() == emp_first and name_parts[1].lower() == emp_last) or \
               (name_parts[1].lower() == emp_first and name_parts[0].lower() == emp_last):
                return emp

    return None
```

### 5. Робота з майном

```python
def get_employee_assets(employee_id, assets):
    """Отримати майно співробітника."""
    result = []

    for asset in assets:
        for assignment in asset.get("asset_assignments", []):
            # Тільки активні призначення
            if assignment["user_id"] == employee_id and assignment["returned_on"] is None:
                result.append({
                    "name": asset["name"],
                    "code": asset["code"],
                    "serial_number": asset.get("serial_number"),
                    "issued_on": assignment["issued_on"]
                })

    return result

# Використання
assets_data = client._get("/assets")
assets = assets_data.get("data", [])

employee_id = 297352
employee_assets = get_employee_assets(employee_id, assets)

for asset in employee_assets:
    print(f"- {asset['name']} ({asset['code']})")
```

---

## 📞 Підтримка

- **Клас:** `tracker_alert.client.peopleforce_api.PeopleForceClient`
- **Налаштування:** `tracker_alert.config.settings`
- **Документація проекту:** `README.md`, `PROJECT_STRUCTURE.md`

**Корисні файли:**

- `tracker_alert/client/peopleforce_api.py` - клієнт API
- `tracker_alert/scripts/export_weekly.py` - приклад використання
- `config/user_schedules.json` - база користувачів

---

## 🔗 Корисні посилання

- **PeopleForce:** https://evadav.peopleforce.io
- **API Endpoint:** https://evadav.peopleforce.io/api/v2

---

**Останнє оновлення:** 10 жовтня 2025  
**Версія документу:** 1.0
