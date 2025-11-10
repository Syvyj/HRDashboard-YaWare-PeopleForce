# Інтеграція PeopleForce: Telegram та Керівник

## Огляд

Система автоматично синхронізує дані з PeopleForce:

- **Робочий телеграм** співробітника
- **Дані про керівника** (ім'я та телеграм)

## Автоматична синхронізація

Синхронізація виконується **щодня о 6:00 ранку** разом з іншими оновленнями з PeopleForce.

### Що синхронізується:

1. **telegram_username** - робочий телеграм з PeopleForce (поле "Рабочий телеграм" з custom fields)
2. **manager_name** - ім'я керівника у форматі `Прізвище_Ім'я` (з поля `reporting_to`)
3. **manager_telegram** - робочий телеграм керівника

## Відображення в інтерфейсі

### Сторінка користувача (`/user_detail`)

**Поле Telegram:**

- Показує робочий телеграм з посиланням `@username`
- Клік відкриває чат в Telegram
- Адміністратори можуть редагувати через модалку

**Поле Руководитель:**

- Показується тільки якщо є дані про керівника
- Відображає ім'я керівника (Прізвище Ім'я)
- Клік відкриває чат з керівником в Telegram
- Іконка Telegram поруч з ім'ям

### Головна сторінка (`/dashboard`)

**Колонка Telegram:**

- Показує посилання на робочий телеграм
- Іконка Telegram + @username
- Клік відкриває чат

## Ручна синхронізація

Якщо потрібно оновити дані негайно:

```bash
python3 scripts/sync_peopleforce_telegram.py
```

Скрипт:

- Отримує дані з PeopleForce для всіх користувачів
- Оновлює telegram та manager поля в `user_schedules.json`
- Показує прогрес та результати

## Редагування адміністратором

Адміністратори можуть вручну редагувати telegram username через модалку "Изменить контроль-менеджера" на сторінці користувача.

**Як редагувати:**

1. Відкрити сторінку користувача
2. Натиснути кнопку редагування (олівець) біля Control manager
3. Ввести новий telegram username у форматі `Прізвище_Ім'я`
4. Зберегти зміни

Зміни зберігаються в `config/user_schedules.json` та синхронізуються через git.

## Технічні деталі

### API Endpoints

**GET `/api/users/<user_key>`**

- Повертає дані користувача включно з `telegram_username`, `manager_name`, `manager_telegram`

**PATCH `/api/users/<user_key>/telegram`**

- Оновлює telegram_username
- Доступно тільки адміністраторам
- Зберігає в `user_schedules.json`

### PeopleForce API

**Endpoint:** `GET /employees/{id}`

**Custom fields:**

- `fields.1.value` - Робочий телеграм

**Reporting to:**

- `reporting_to.first_name` - Ім'я керівника
- `reporting_to.last_name` - Прізвище керівника
- `reporting_to.id` - ID керівника (для отримання його telegram)

### Структура даних (user_schedules.json)

```json
{
  "users": {
    "Kutkovskyi Mykhailo": {
      "name": "Kutkovskyi Mykhailo",
      "email": "m.kutkovskyi@evadav.com",
      "peopleforce_id": 297365,
      "telegram_username": "@Kutkovskyi_Mykhailo",
      "manager_name": "Lazarenko_Maksim",
      "manager_telegram": "@Lazarenko_Maksim",
      "start_time": "10:00",
      "location": "UA",
      "department": "RTB Team",
      ...
    }
  }
}
```

## Кешування

- PeopleForce API відповіді кешуються на 5 хвилин
- Детальні дані керівників кешуються в межах одного запуску синхронізації
- Зменшує кількість запитів до API

## Обмеження та примітки

1. **Робочий телеграм** має бути заповнений в PeopleForce у полі "Рабочий телеграм"
2. **Керівник** має бути призначений у полі "Руководитель" (reporting_to)
3. Якщо даних немає в PeopleForce - поля не будуть відображатися
4. Синхронізація не перезаписує вручну введені дані адміністратором

## Логування

Всі операції синхронізації логуються:

```
[scheduler] Running PeopleForce metadata sync
[scheduler] Оновлено telegram для Kutkovskyi Mykhailo: @Kutkovskyi_Mykhailo
[scheduler] Оновлено manager_name для Kutkovskyi Mykhailo: Lazarenko_Maksim
[scheduler] Updated schedule metadata from PeopleForce (including telegram and manager)
```

## Troubleshooting

**Telegram не показується:**

- Перевірте наявність поля "Рабочий телеграм" в PeopleForce
- Перевірте peopleforce_id в user_schedules.json
- Запустіть ручну синхронізацію

**Керівник не показується:**

- Перевірте призначення керівника в PeopleForce (поле "Руководитель")
- Перевірте що у керівника заповнений робочий телеграм
- Запустіть ручну синхронізацію

**Помилки API:**

- Перевірте налаштування PEOPLEFORCE_API_KEY в .env
- Перевірте доступність API PeopleForce
- Перегляньте логи для деталей помилок
