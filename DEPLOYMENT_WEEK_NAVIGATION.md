# Deployment: Week Navigation Feature

## Зміни в проекті

### 1. База даних
- Додано колонку `record_type` (VARCHAR(16), default='daily', indexed) в таблицю `attendance_records`
- Типи: 'daily', 'week_total', 'leave', 'absent'

### 2. Backend (dashboard_app/api.py)
- `_apply_filters()` - додано параметр `week_offset`, розрахунок поточного тижня, збереження week_start в flask.g
- `_build_items()` - додано динамічний розрахунок week_total з підтримкою DB записів
- `_collect_recent_records()` - ПОВНІСТЮ переписано з копіюванням логіки _build_items() для динамічного week_total
- `api_user_detail()` - використання week_start з flask.g
- POST `/api/week-notes` - створення AttendanceRecord з record_type='week_total'
- Імпорт: додано `g` з flask

### 3. Frontend
**dashboard.html**:
- Додано кнопки навігації по тижнях (попередній/поточний/наступний)
- Додано span для відображення діапазону дат тижня

**user_detail.html**:
- Додано такі ж кнопки навігації по тижнях

**static/js/report.js**:
- Змінні: currentWeekOffset, кнопки навігації
- Функції: getWeekDates(), updateWeekDisplay(), navigateWeek()
- buildParams() - додає week_offset в URL params
- Event listeners для кнопок

**static/js/user_detail.js**:
- Аналогічні зміни як в report.js
- renderRecords() - фільтрує та відображає week_total окремо

## Кроки деплою на сервер

### Крок 1: Backup критичних даних
```bash
# На сервері
ssh deploy@65.21.51.165
cd ~/www/YaWare_Bot

# Бекап БД
cp instance/dashboard.db instance/dashboard.db.backup_$(date +%Y%m%d_%H%M%S)

# Бекап week notes (ВАЖЛИВО!)
cp instance/week_notes.json instance/week_notes.json.backup_$(date +%Y%m%d_%H%M%S)
```

### Крок 2: Pull коду з Git
```bash
# На сервері
cd ~/www/YaWare_Bot
git pull origin main
```

### Крок 3: Міграція БД
```bash
# На сервері
cd ~/www/YaWare_Bot
python3 scripts/add_record_type_column.py
```

Очікуваний вивід:
```
Додаємо колонку record_type...
Створюємо індекс...
✓ Колонка record_type успішно додана

Всього записів: XXXX
Всі записи отримали record_type='daily' за замовчуванням
```

### Крок 4: Перезапуск Flask
```bash
# Знайти процес
ps aux | grep web_dashboard

# Вбити процес
kill -9 <PID>

# Запустити знову (якщо використовуєте systemd)
sudo systemctl restart yaware-dashboard

# АБО якщо запускається вручну
nohup python3 web_dashboard.py > logs/web_dashboard.log 2>&1 &
```

### Крок 5: Перевірка
1. Відкрити головну сторінку
2. Перевірити навігацію по тижнях (попередній/поточний/наступний)
3. Перевірити відображення Week Total
4. Відкрити сторінку користувача
5. Перевірити навігацію та Week Total на сторінці користувача
6. Зберегти коментар через модальне вікно Week Total
7. Перевірити що коментар відображається

## Перевірка що все працює

### SQL запити для перевірки:
```sql
-- Перевірити що колонка додана
PRAGMA table_info(attendance_records);

-- Перевірити індекс
SELECT * FROM sqlite_master WHERE type='index' AND tbl_name='attendance_records' AND name='idx_record_type';

-- Кількість записів по типам
SELECT record_type, COUNT(*) FROM attendance_records GROUP BY record_type;

-- Week total записи
SELECT record_date, user_name, total_minutes, notes 
FROM attendance_records 
WHERE record_type='week_total' 
ORDER BY record_date DESC 
LIMIT 10;
```

## Rollback план (якщо щось пішло не так)

### 1. Відновити БД
```bash
cp instance/dashboard.db.backup_YYYYMMDD_HHMMSS instance/dashboard.db
```

### 2. Відновити код
```bash
git reset --hard HEAD~1
```

### 3. Перезапустити Flask
```bash
sudo systemctl restart yaware-dashboard
```

## Важливі нотатки

1. **Week notes зберігаються в instance/week_notes.json** - НЕ перезаписувати при деплої!
2. **Daily notes в БД** - вже там, нічого не треба
3. **Week_total створюється** коли контрол-менеджер зберігає коментар ДО тижня
4. **Динамічний week_total** рахується з daily records якщо немає в БД
5. **Week_start** передається з backend через flask.g для правильного week_offset

## Тестові сценарії

1. ✅ Навігація по тижнях на головній
2. ✅ Навігація по тижнях на сторінці користувача
3. ✅ Відображення динамічного Week Total
4. ✅ Збереження Week Total в БД через модальне вікно
5. ✅ Відображення збереженого Week Total
6. ✅ Сортування записів (понеділок → п'ятниця → Week Total)
