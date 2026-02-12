# YaWare Productivity Suite

Internal system for analyzing team attendance and productivity, built on top of YaWare TimeTracker. The project consists of an interactive web dashboard, Google Sheets export, Excel/PDF report generation, and related automation tools.

## 🔎 Key Features

### Web Dashboard

- **Filtered Dashboard** - attendance analysis by dates, projects, departments, teams
- **4-level hierarchy** - Division → Direction → Unit → Team
- **Automatic synchronized filtering** - dropdown lists adapt to selected values
- **Multi-select employees** - select multiple employees for detailed analysis
- **Report export** - Excel and PDF with full data structure
- **Note editing** - directly in the web interface with instant save

### Administration

- **Admin web panel** (`/admin`) - employee database management
- **PeopleForce synchronization** - automatic data updates (Division, Direction, Unit, Team, Position, Location)
- **Data adaptation via Level_Grade.json** - hierarchy normalization ("APPS Division" → "Apps")
- **Control Manager Management** - assignment with protection against overwriting manually set values
- **Date deletion** - cleanup of erroneous records for a specific date

### Integrations

- **YaWare TimeTracker API v2** - automatic productivity data collection
- **PeopleForce API** - organizational structure and HR data synchronization
- **Google Sheets Export** - daily and weekly export for analytics
- **Level_Grade.json** - reference guide for correct hierarchy mapping

## 🧱 Architecture

| Component | Directory | Description |
|-----------|-----------|-------------|
| Flask dashboard | `dashboard_app/`, `web_dashboard.py`, `templates/`, `static/` | UI, REST API, authentication, Excel/PDF generation |
| YaWare → Sheets exporters | `tracker_alert/` | YaWare API client, transformation and writing to Google Sheets |
| Telegram/automation | `tracker_alert/scripts/` | Helper CLI, migrations, alerts |
| Work schedule configuration | `config/user_schedules.json`, `config/work_schedules.json` | User and team directory used in filters |

## 🛠️ Tech Stack

- **Back-end:** Python 3.10+, Flask, Flask-Login, SQLAlchemy
- **Storage:** SQLite by default (PostgreSQL possible via `DASHBOARD_DATABASE_URL`)
- **Front-end:** HTML/Jinja, Bootstrap 5, custom vanilla JS (`static/js/report.js`)
- **Reports:** OpenPyXL (Excel), ReportLab (PDF)
- **Integrations:** requests + YaWare API v2, Google API Client (Google Sheets), pydantic, python-dotenv
- **Other utilities:** click (CLI), pathlib/json for references, ruff/black (recommended for lint/format)

Documentation for deployment, API, and integrations is in the `docs/` directory. For a quick overview of task schedules, data sources, and mappings, use `docs/AUTOMATION_OVERVIEW.md`, and topic guides (DEPLOYMENT, YAWARE_API_GUIDE, TELEGRAM_BOT_GUIDE, etc.) contain details for each direction.

## ⚙️ Requirements

- Python 3.10+
- Google Cloud Service Account with access to required tables (for export)
- YaWare API v2 token with access to the required account
- (Optional) PeopleForce API if schedule synchronization is used

All dependencies are listed in `requirements.txt`.

## 🚀 Quick Start (Dashboard)

1. **Create and activate virtual environment**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment variables** (can be done via `.env` and `python-dotenv`):

   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

   See `.env.example` for all supported variables.

3. **Prepare Service Account**

   - Save `gcp-sa.json` in the project root
   - Grant access to required Google Sheets

4. **Run web application**

   ```bash
   python web_dashboard.py  # runs in debug mode on http://localhost:5000
   ```

5. **Create first user**

   ```bash
   flask --app web_dashboard.py create-user admin@example.com "Admin" "StrongPassword" --admin
   ```

   You can also pass `--managers "1,2"` to limit access to specific managers' data.

6. **Prepare reference files**

   - `config/user_schedules.json` — employee database with 4-level hierarchy (see `config/user_schedules.json.example`)
   - `config/Level_Grade.json` — reference guide for data adaptation
   - `config/work_schedules.json` — global schedule settings

## 🤖 Telegram Attendance Bot

**Automatic employee attendance monitoring**

The bot sends daily reports at 10:02 Warsaw time about lateness and absences.

### Quick start bot

```bash
# 1. Add to .env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ADMIN_CHAT_IDS=123456789,987654321

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run bot
python scripts/run_attendance_bot.py
```

### Bot commands

- `/start` - Greeting
- `/help` - Help
- `/status` - System status
- `/report_today` - Report for today

**Detailed documentation:** [docs/TELEGRAM_BOT_GUIDE.md](docs/TELEGRAM_BOT_GUIDE.md)

## 📂 Repository Structure

```
YaWare_Bot/
├── dashboard_app/             # Flask app, REST API, models, scheduler
├── static/                    # JS/CSS for dashboard
├── templates/                 # HTML/Jinja templates
├── tracker_alert/             # CLI and integrations with YaWare/Google Sheets/Telegram
├── tasks/                     # Attendance updates, scheduler
├── config/                    # JSON reference files (see .example files)
├── docs/                      # Deployment, API, bot guides
├── scripts/                   # Launch/export utilities
├── web_dashboard.py           # Flask entry point (debug)
├── requirements.txt           # Dependencies
└── README.md                  # This file (Ukrainian)
```

## 📚 Additional Materials

- `docs/YAWARE_API_GUIDE.md` — YaWare API overview
- `docs/DEPLOYMENT.md` — application deployment tips
- `docs/AUTO_EXPORT_GUIDE.md` — automation and manual export scenarios
- `docs/TELEGRAM_BOT_GUIDE.md` — messenger notifications
- `docs/AVAILABLE_DATA.md` — prepared datasets description

## 🔒 Security Notes

- **Never commit** `.env`, `gcp-sa.json`, or `config/user_schedules.json` with real data
- Use `.env.example` and `config/*.example` files as templates
- All sensitive files are listed in `.gitignore`
- Change default `DASHBOARD_SECRET_KEY` before production use

## 📝 License

Internal / Proprietary

## 🤝 Support

For API questions, contact YaWare Support.
