# 🚀 Публікація на GitHub - Швидкий гайд

## Репозиторій
**URL:** https://github.com/Syvyj/HRDashboard-YaWare-PeopleForce.git

---

## ⚠️ Важливо перед публікацією

### 1. Перевірка чутливих файлів

```bash
# Перевірити що чутливі файли виключені
git check-ignore config/user_schedules.json instance/monthly_notes.json instance/dashboard.db .env

# Перевірити що чутливі файли НЕ в git
git ls-files | grep -E "(user_schedules|\.db|\.env|gcp-sa)"

# Якщо якийсь файл НЕ виключений - він буде закомічений!
# Якщо файли вже в git - видалити їх: git rm --cached <file>
```

### 2. Перевірка що буде закомічено

```bash
# Показати всі файли які будуть закомічені
git status

# Перевірити що немає чутливих файлів в списку
git status | grep -E "(user_schedules\.json|\.db|\.env|gcp-sa)"
```

---

## 📋 Кроки публікації

### Крок 1: Додати GitHub remote

```bash
cd /Users/admin/Documents/YaWare_Bot

# Додати GitHub remote (назваємо 'github' щоб не конфліктувати з існуючим 'origin')
git remote add github https://github.com/Syvyj/HRDashboard-YaWare-PeopleForce.git

# Перевірити
git remote -v
```

### Крок 2: Перевірити зміни

```bash
# Показати всі зміни
git status

# Перевірити що чутливі файли НЕ в списку
git status | grep -v "user_schedules.json\|\.db\|\.env"
```

### Крок 3: Додати файли

```bash
# Додати всі файли (чутливі автоматично виключені через .gitignore)
git add .

# Перевірити що додано
git status
```

### Крок 4: Зробити коміт

```bash
git commit -m "Initial commit: YaWare Productivity Suite

Features:
- Web dashboard for attendance tracking and reporting
- Telegram bot for daily attendance reports
- Integration with YaWare API v2 and PeopleForce API
- Google Sheets export functionality
- Monthly and weekly reports generation
- Admin panel for user management
- Automated data synchronization

Documentation:
- Complete documentation in English and Ukrainian
- API guides for YaWare and PeopleForce
- Deployment guides
- Security guidelines"
```

### Крок 5: Запушити на GitHub

```bash
# Запушити на GitHub
git push -u github main

# Якщо репозиторій порожній і це перший push
# Можливо знадобиться:
git push -u github main --force
# (тільки якщо репозиторій точно порожній!)
```

---

## 🔍 Перевірка після публікації

1. Відкрити https://github.com/Syvyj/HRDashboard-YaWare-PeopleForce
2. Перевірити що:
   - ✅ README.md відображається
   - ✅ Всі файли завантажені
   - ✅ Немає `config/user_schedules.json` в репозиторії
   - ✅ Немає `instance/dashboard.db` в репозиторії
   - ✅ Немає `.env` в репозиторії
   - ✅ Присутні `.example` файли

---

## 🛠️ Якщо потрібно оновити remote

Якщо хочете змінити існуючий `origin` на GitHub:

```bash
# Видалити старий origin
git remote remove origin

# Додати GitHub як origin
git remote add origin https://github.com/Syvyj/HRDashboard-YaWare-PeopleForce.git

# Або змінити URL існуючого origin
git remote set-url origin https://github.com/Syvyj/HRDashboard-YaWare-PeopleForce.git
```

---

## 📝 Додаткові налаштування на GitHub

### 1. Додати опис репозиторію
- Settings → General → Description
- "Productivity tracking system with YaWare API v2, PeopleForce integration, and Telegram bot"

### 2. Додати теми (Topics)
- python, flask, telegram-bot, yaware, peopleforce, attendance-tracking, hr-dashboard, productivity-tracking

### 3. Додати README опис
- Можна додати badges, screenshots тощо

---

## ✅ Чеклист

- [ ] Перевірено що чутливі файли виключені
- [ ] Додано GitHub remote
- [ ] Перевірено список файлів для коміту
- [ ] Зроблено коміт
- [ ] Запушено на GitHub
- [ ] Перевірено на GitHub що все правильно

---

**Детальні інструкції:** `docs/GITHUB_PUBLICATION.md`
