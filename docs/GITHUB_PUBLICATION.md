# Публікація проекту на GitHub

## 🔗 Репозиторій

**URL:** https://github.com/Syvyj/HRDashboard-YaWare-PeopleForce.git

---

## ✅ Перед публікацією

### Перевірка готовності

1. **Перевірити що всі зміни збережені:**
   ```bash
   git status
   ```

2. **Перевірити що чутливі файли виключені:**
   ```bash
   git check-ignore config/user_schedules.json instance/monthly_notes.json .env
   ```

3. **Перевірити що немає чутливих даних:**
   ```bash
   # Перевірити на IP адреси
   git grep "65.21.51.165" --cached
   
   # Перевірити на email адреси
   git grep "@evadav.com" --cached
   ```

---

## 🚀 Інструкції по публікації

### Варіант 1: Якщо репозиторій порожній (перша публікація)

```bash
cd /Users/admin/Documents/YaWare_Bot

# Додати remote (якщо ще не додано)
git remote add origin https://github.com/Syvyj/HRDashboard-YaWare-PeopleForce.git

# Перевірити remote
git remote -v

# Додати всі файли
git add .

# Перевірити що буде закомічено (переконатися що немає чутливих файлів)
git status

# Зробити перший коміт
git commit -m "Initial commit: YaWare Productivity Suite

- Web dashboard for attendance tracking
- Telegram bot for daily reports
- Integration with YaWare API v2 and PeopleForce API
- Google Sheets export functionality
- Monthly and weekly reports
- Admin panel for user management"

# Запушити на GitHub
git push -u origin main
```

### Варіант 2: Якщо репозиторій вже має файли

```bash
cd /Users/admin/Documents/YaWare_Bot

# Додати remote
git remote add origin https://github.com/Syvyj/HRDashboard-YaWare-PeopleForce.git

# Отримати зміни з GitHub (якщо є)
git fetch origin

# Перевірити гілку
git branch -M main

# Додати всі файли
git add .

# Зробити коміт
git commit -m "Add YaWare Productivity Suite project"

# Запушити (якщо є конфлікти - вирішити їх)
git push -u origin main
```

### Варіант 3: Якщо потрібно оновити існуючий remote

```bash
cd /Users/admin/Documents/YaWare_Bot

# Перевірити поточний remote
git remote -v

# Якщо потрібно змінити URL
git remote set-url origin https://github.com/Syvyj/HRDashboard-YaWare-PeopleForce.git

# Перевірити
git remote -v

# Додати зміни
git add .

# Зробити коміт
git commit -m "Update project files"

# Запушити
git push -u origin main
```

---

## ⚠️ Важливо перед push

### 1. Перевірити що буде закомічено

```bash
# Показати всі файли які будуть закомічені
git status

# Показати зміни
git diff --cached

# Перевірити що немає чутливих файлів
git ls-files | grep -E "(\.env|gcp-sa|user_schedules\.json|\.db$)"
```

### 2. Перевірити розмір файлів

```bash
# Перевірити великі файли
find . -type f -size +1M ! -path "./.git/*" ! -path "./.venv/*" ! -path "./All_Backup/*"
```

### 3. Перевірити .gitignore

```bash
# Перевірити що чутливі файли виключені
git check-ignore -v config/user_schedules.json instance/monthly_notes.json .env
```

---

## 🔍 Після публікації

### Перевірити на GitHub

1. Відкрити https://github.com/Syvyj/HRDashboard-YaWare-PeopleForce
2. Перевірити що всі файли завантажені
3. Перевірити що чутливі файли відсутні
4. Перевірити README.md відображається правильно

### Налаштування репозиторію на GitHub

1. **Додати опис репозиторію:**
   - Settings → General → Description
   - "Productivity tracking system with YaWare API v2, PeopleForce integration, and Telegram bot"

2. **Додати теми (topics):**
   - python, flask, telegram-bot, yaware, peopleforce, attendance-tracking, hr-dashboard

3. **Налаштувати GitHub Pages (опціонально):**
   - Settings → Pages
   - Source: main branch / docs folder

4. **Додати LICENSE файл (опціонально):**
   - Створити LICENSE файл з відповідною ліцензією

---

## 📝 Рекомендований порядок комітів

Якщо потрібно розбити на кілька комітів:

```bash
# 1. Основні файли проекту
git add dashboard_app/ tracker_alert/ tasks/ templates/ static/ web_dashboard.py requirements.txt
git commit -m "Add core application files"

# 2. Документація
git add docs/ README.md README_EN.md SECURITY.md
git commit -m "Add documentation"

# 3. Конфігурація та приклади
git add config/*.example instance/*.example .env.example .gitignore
git commit -m "Add configuration examples and gitignore"

# 4. Скрипти та утиліти
git add scripts/
git commit -m "Add utility scripts"

# 5. Інші файли
git add .
git commit -m "Add remaining files"
```

---

## 🚨 Якщо щось пішло не так

### Відмінити останній push

```bash
# Відмінити останній коміт (локально)
git reset --soft HEAD~1

# Або видалити файли з індексу
git reset HEAD <file>
```

### Видалити чутливі файли з історії (якщо випадково закомітили)

```bash
# Використати git filter-branch або BFG Repo-Cleaner
# УВАГА: Це змінює історію git!
```

---

## ✅ Чеклист після публікації

- [ ] Всі файли завантажені на GitHub
- [ ] README.md відображається правильно
- [ ] Чутливі файли відсутні в репозиторії
- [ ] Документація доступна
- [ ] Приклади конфігурації присутні
- [ ] .gitignore працює правильно

---

**Дата:** 2025-02-04
