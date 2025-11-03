from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
try:
    from pydantic_settings import BaseSettings
    from pydantic import Field
except ImportError:
    from pydantic import BaseSettings, Field

# Завантажуємо .env з кореня проєкту
ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = ROOT / '.env'
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()

class Settings(BaseSettings):
    # YaWare Direct API (v2) - працює!
    yaware_access_key: str = Field(..., env="YAWARE_ACCESS_KEY")
    yaware_base_url: str = Field("https://data1.yaware.com/export/account/json/v2", env="YAWARE_BASE_URL")
    yaware_user_id: Optional[str] = Field(None, env="YAWARE_USER_ID")
    yaware_email: Optional[str] = Field(None, env="YAWARE_EMAIL")
    
    # Legacy RapidAPI (не працює, залишено для історії)
    rapidapi_key: Optional[str] = Field(None, env="RAPIDAPI_KEY")
    rapidapi_host: str = Field("yaware-timetracker.p.rapidapi.com", env="RAPIDAPI_HOST")
    yaware_daily_path: Optional[str] = Field(None, env="YAWARE_DAILY_PATH")
    yaware_account_id: Optional[str] = Field(None, env="YAWARE_ACCOUNT_ID")
    yaware_company_id: Optional[str] = Field(None, env="YAWARE_COMPANY_ID")
    yaware_tz_offset: Optional[str] = Field(None, env="YAWARE_TZ_OFFSET")

    # Sheets
    spreadsheet_id: str = Field(..., env="SPREADSHEET_ID")
    spreadsheet_id_control_1: str = Field(..., env="SPREADSHEET_ID_CONTROL_1")
    spreadsheet_id_control_2: str = Field(..., env="SPREADSHEET_ID_CONTROL_2")
    sheet_tab: str = Field("by_user", env="SHEET_TAB")
    sa_path: str = Field("gcp-sa.json", env="SA_PATH")
    
    # PeopleForce API
    peopleforce_api_key: Optional[str] = Field(None, env="PEOPLEFORCE_API_KEY")
    peopleforce_base_url: str = Field("https://evrius.peopleforce.io/api/public/v3", env="PEOPLEFORCE_BASE_URL")

    # Telegram (поки опційно)
    telegram_bot_token: Optional[str] = Field(None, env="TELEGRAM_BOT_TOKEN")
    telegram_admin_chat_ids: Optional[str] = Field(None, env="TELEGRAM_ADMIN_CHAT_IDS")  # через кому
    telegram_manager_mapping: Optional[str] = Field(None, env="TELEGRAM_MANAGER_MAPPING")  # chat_id:1|2

    # DB
    db_path: str = Field("tracker.db", env="DB_PATH")

    class Config:
        case_sensitive = False

settings = Settings()  # глобальний інстанс
