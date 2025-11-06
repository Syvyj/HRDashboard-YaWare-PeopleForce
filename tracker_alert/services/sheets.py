from __future__ import annotations
from typing import List, Any, Optional, Dict
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from ..config.settings import settings
import logging

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADERS = [["Date", "Fact Start", "Non Productive", "Not Categorized", "Productive"]]


def _service():
    creds = Credentials.from_service_account_file(settings.sa_path, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def ensure_sheet():
    svc = _service()
    meta = svc.spreadsheets().get(spreadsheetId=settings.spreadsheet_id).execute()
    titles = {s["properties"]["title"] for s in meta.get("sheets", [])}
    if settings.sheet_tab not in titles:
        body = {"requests": [{"addSheet": {"properties": {"title": settings.sheet_tab}}}]}
        svc.spreadsheets().batchUpdate(spreadsheetId=settings.spreadsheet_id, body=body).execute()
    try:
        res = svc.spreadsheets().values().get(
            spreadsheetId=settings.spreadsheet_id, range=f"{settings.sheet_tab}!A1:E1"
        ).execute()
        if not res.get("values"):
            svc.spreadsheets().values().update(
                spreadsheetId=settings.spreadsheet_id,
                range=f"{settings.sheet_tab}!A1",
                valueInputOption="USER_ENTERED",
                body={"values": HEADERS},
            ).execute()
    except HttpError:
        pass
    return svc


def append_rows(rows: List[List[Any]]):
    svc = _service()
    svc.spreadsheets().values().append(
        spreadsheetId=settings.spreadsheet_id,
        range=f"{settings.sheet_tab}!A:E",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": rows},
    ).execute()


def get_sheet_id_by_name(service, sheet_name: str) -> Optional[int]:
    """
    Получить sheet ID по названию.
    
    Args:
        service: Google Sheets service
        sheet_name: Название листа
        
    Returns:
        Sheet ID или None если не найден
    """
    try:
        meta = service.spreadsheets().get(spreadsheetId=settings.spreadsheet_id).execute()
        for sheet in meta.get("sheets", []):
            if sheet["properties"]["title"] == sheet_name:
                return sheet["properties"]["sheetId"]
    except Exception as e:
        logger.error(f"Ошибка получения sheet ID: {e}")
    return None


def create_weekly_sheet(sheet_name: str, data_rows: List[List[Any]]) -> bool:
    """
    Создать новый лист для недели и записать данные.
    
    Args:
        sheet_name: Название листа (например, "Week 41 (06-10 Oct 2025)")
        data_rows: Все строки с данными (включая заголовки)
        
    Returns:
        True если успешно создано
    """
    service = _service()
    
    try:
        # Проверяем существует ли лист
        sheet_id = get_sheet_id_by_name(service, sheet_name)
        
        if sheet_id is None:
            # Создаем новый лист
            logger.info(f"Создаем новый лист '{sheet_name}'...")
            body = {
                "requests": [{
                    "addSheet": {
                        "properties": {
                            "title": sheet_name,
                            "gridProperties": {
                                "rowCount": max(len(data_rows) + 50, 1100),  # С запасом
                                "columnCount": 13
                            }
                        }
                    }
                }]
            }
            response = service.spreadsheets().batchUpdate(
                spreadsheetId=settings.spreadsheet_id,
                body=body
            ).execute()
            
            # Получаем ID созданного листа
            sheet_id = response["replies"][0]["addSheet"]["properties"]["sheetId"]
            logger.info(f"✅ Лист создан, ID: {sheet_id}")
        else:
            logger.info(f"Лист '{sheet_name}' уже существует, будет перезаписан")
            # Очищаем существующий лист
            service.spreadsheets().values().clear(
                spreadsheetId=settings.spreadsheet_id,
                range=f"'{sheet_name}'!A:Z"
            ).execute()
        
        # Записываем данные
        logger.info(f"Записываем {len(data_rows)} строк...")
        service.spreadsheets().values().update(
            spreadsheetId=settings.spreadsheet_id,
            range=f"'{sheet_name}'!A1",
            valueInputOption="USER_ENTERED",
            body={"values": data_rows}
        ).execute()
        
        logger.info(f"✅ Данные записаны в '{sheet_name}'")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка создания листа: {e}")
        return False


def apply_weekly_formatting(sheet_name: str, total_rows: int, week_data: Dict[str, Any], week_days: List, peopleforce_data: Dict[str, Any] = None):
    """Применить форматирование к недельному листу.
    
    Args:
        sheet_name: Название листа
        total_rows: Общее количество строк
        week_data: Данные пользователей (dict с email как ключ)
        week_days: Список дат недели (для маппинга дней)
        peopleforce_data: Данные из PeopleForce (для покраски дней с отпусками)
    """
    from datetime import date
    
    users_count = len(week_data)
    service = _service()
    sheet_id = get_sheet_id_by_name(service, sheet_name)
    
    if sheet_id is None:
        logger.error(f"Лист '{sheet_name}' не найден")
        return
    
    logger.info(f"🎨 Применяем цветное форматирование для '{sheet_name}'...")
    
    requests = []
    
    # 🧹 Очищаем все старые цвета перед новой покраской
    # (чтобы при изменении количества пользователей не оставалось старое форматирование)
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,  # Начинаем со второй строки (пропускаем заголовки)
                "endRowIndex": total_rows + 100,  # +100 про запас для старых данных
                "startColumnIndex": 0,
                "endColumnIndex": 13
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 1, "green": 1, "blue": 1}  # Білий
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })
    
    # Кольори у форматі RGB (0-1)
    COLOR_USER_HEADER = {"red": 0.902, "green": 0.847, "blue": 0.816}  # #e6d8d0
    COLOR_NON_PRODUCTIVE = {"red": 0.957, "green": 0.8, "blue": 0.8}  # #f4cccc
    COLOR_NOT_CATEGORIZED = {"red": 1.0, "green": 0.98, "blue": 0.753}  # #fffac0
    COLOR_PRODUCTIVE = {"red": 0.851, "green": 0.918, "blue": 0.827}  # #d9ead3
    COLOR_TOTAL_COLUMN = {"red": 0.788, "green": 0.855, "blue": 0.973}  # #c9daf8
    COLOR_HEADER = {"red": 0.9, "green": 0.9, "blue": 0.9}  # Серый для заголовка таблицы
    COLOR_TOTAL_ROW = {"red": 0.95, "green": 0.95, "blue": 0.95}  # Светло-серый для Total недели
    
    # Индексы колонок (0-based)
    COL_NON_PRODUCTIVE = 7  # H
    COL_NOT_CATEGORIZED = 8  # I
    COL_PRODUCTIVE = 9  # J
    COL_TOTAL = 10  # K
    
    # 1. Заморозить первую строку (заголовки)
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {
                    "frozenRowCount": 1
                }
            },
            "fields": "gridProperties.frozenRowCount"
        }
    })
    
    # 2. Базовое форматирование заголовков таблицы (первая строка) - жирный текст
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": 13
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"bold": True},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE"
                }
            },
            "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)"
        }
    })
    
    # 2.1. Цветные заголовки (колонки с данными)
    # Non Productive (колонка E)
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": COL_NON_PRODUCTIVE,
                "endColumnIndex": COL_NON_PRODUCTIVE + 1
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": COLOR_NON_PRODUCTIVE
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })
    
    # Not Categorized (колонка F)
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": COL_NOT_CATEGORIZED,
                "endColumnIndex": COL_NOT_CATEGORIZED + 1
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": COLOR_NOT_CATEGORIZED
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })
    
    # Productive (колонка G)
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": COL_PRODUCTIVE,
                "endColumnIndex": COL_PRODUCTIVE + 1
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": COLOR_PRODUCTIVE
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })
    
    # Total (колонка H)
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": COL_TOTAL,
                "endColumnIndex": COL_TOTAL + 1
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": COLOR_TOTAL_COLUMN
                }
            },
            "fields": "userEnteredFormat.backgroundColor"
        }
    })
    
    # 3. Форматирование блоков пользователей
    # Структура блока: заголовок + 5 дней + Week total + разделитель = 8 строк
    current_row = 1  # Начинаем после заголовков
    
    for i in range(min(users_count, (total_rows - 1) // 8)):
        if current_row >= total_rows - 1:
            break
        
        # 3.1. Строка с именем пользователя (вся строка) - бежевый фон + жирный текст
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": current_row,
                    "endRowIndex": min(current_row + 1, total_rows),
                    "startColumnIndex": 0,
                    "endColumnIndex": 13
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": COLOR_USER_HEADER
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)"
            }
        })
        
        # 3.2. Строки с днями (5 строк)
        days_start = current_row + 1
        days_end = min(current_row + 6, total_rows)
        
        # Project/Department/Team: служебные строки (Location, Week total)
        # 1. Location (первая строка дней) — белый текст
        for row in range(days_start, days_end):
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row,
                        "endRowIndex": row+1,
                        "startColumnIndex": 1,
                        "endColumnIndex": 4
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {
                                "foregroundColor": {"red": 1, "green": 1, "blue": 1}
                            }
                        }
                    },
                    "fields": "userEnteredFormat.textFormat.foregroundColor"
                }
            })
        # 2. Week total (7-я строка блока) — серый текст
        total_row = current_row + 6
        if total_row < total_rows:
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": total_row,
                        "endRowIndex": total_row+1,
                        "startColumnIndex": 1,
                        "endColumnIndex": 4
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {
                                "foregroundColor": COLOR_TOTAL_ROW
                            }
                        }
                    },
                    "fields": "userEnteredFormat.textFormat.foregroundColor"
                }
            })
        
        # Non Productive (колонка E) - красный
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": days_start,
                    "endRowIndex": days_end,
                    "startColumnIndex": COL_NON_PRODUCTIVE,
                    "endColumnIndex": COL_NON_PRODUCTIVE + 1
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": COLOR_NON_PRODUCTIVE
                    }
                },
                "fields": "userEnteredFormat.backgroundColor"
            }
        })
        
        # Not Categorized (колонка F) - желтый
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": days_start,
                    "endRowIndex": days_end,
                    "startColumnIndex": COL_NOT_CATEGORIZED,
                    "endColumnIndex": COL_NOT_CATEGORIZED + 1
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": COLOR_NOT_CATEGORIZED
                    }
                },
                "fields": "userEnteredFormat.backgroundColor"
            }
        })
        
        # Productive (колонка G) - зеленый
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": days_start,
                    "endRowIndex": days_end,
                    "startColumnIndex": COL_PRODUCTIVE,
                    "endColumnIndex": COL_PRODUCTIVE + 1
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": COLOR_PRODUCTIVE
                    }
                },
                "fields": "userEnteredFormat.backgroundColor"
            }
        })
        
        # Total колонка (H) - синий
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": days_start,
                    "endRowIndex": days_end,
                    "startColumnIndex": COL_TOTAL,
                    "endColumnIndex": COL_TOTAL + 1
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": COLOR_TOTAL_COLUMN
                    }
                },
                "fields": "userEnteredFormat.backgroundColor"
            }
        })
        
        # 3.3. Строка Total недели (7-я строка блока: current_row+6) - серый фон + жирный текст
        total_row = current_row + 6
        if total_row < total_rows:
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": total_row,
                        "endRowIndex": min(total_row + 1, total_rows),
                        "startColumnIndex": 0,
                        "endColumnIndex": 13
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": COLOR_TOTAL_ROW
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor)"
                }
            })
        
        current_row += 8  # Переходим к следующему блоку (имя + 5 дней + Total + разделитель)
    
    # 4. Покраска дней с отпусками/больничными
    if peopleforce_data:
        leaves_by_email = peopleforce_data.get("leaves", {})
        sorted_users = sorted(week_data.values(), key=lambda x: x["full_name"])
        current_row = 1
        for user_data in sorted_users:
            if current_row >= total_rows - 1:
                break
            user_email = user_data.get("email", "")
            user_leaves = leaves_by_email.get(user_email, {})
            for day_index, week_day in enumerate(week_days):
                # Проверка совпадения дат: week_day может быть date, а ключи user_leaves — строки
                leave_info = None
                for k in user_leaves:
                    if str(k) == str(week_day) or k == week_day.strftime("%Y-%m-%d"):
                        leave_info = user_leaves[k]
                        break
                if leave_info:
                    leave_type = leave_info.get("leave_type", "").lower()
                    # Явное распределение цветов
                    if "отпуск" in leave_type or "vacation" in leave_type:
                        bg_color = COLOR_PRODUCTIVE  # Зеленый
                    elif "лікарняний" in leave_type or "sick" in leave_type:
                        bg_color = COLOR_NON_PRODUCTIVE  # Красный
                    elif "свой счет" in leave_type or "за свой счет" in leave_type or "unpaid" in leave_type:
                        bg_color = COLOR_NOT_CATEGORIZED  # Желтый
                    else:
                        bg_color = COLOR_HEADER  # Серый по умолчанию
                    day_row = current_row + 1 + day_index
                    # E-M (4-13): все рабочие колонки
                    requests.append({
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": day_row,
                                "endRowIndex": day_row + 1,
                                "startColumnIndex": 4,
                                "endColumnIndex": 13
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": bg_color
                                }
                            },
                            "fields": "userEnteredFormat.backgroundColor"
                        }
                    })
            current_row += 8
    
    # 5. Выравнивание по центру для всех колонок с данными (Plan Start, Data, Fact Start, Non Productive, Not Categorized, Productive, Total)
    # Колонки B, C, D, E, F, G, H (индексы 1-7)
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": total_rows,
                "startColumnIndex": 1,  # B (Plan Start)
                "endColumnIndex": 8  # H (Total) + 1
            },
            "cell": {
                "userEnteredFormat": {
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE"
                }
            },
            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)"
        }
    })
    
    # 6. Форматирование колонок (время/дата)
    # E (Plan Start) - время HH:MM
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": total_rows,
                "startColumnIndex": 4,
                "endColumnIndex": 5
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": "TIME",
                        "pattern": "[h]:mm"
                    }
                }
            },
            "fields": "userEnteredFormat.numberFormat"
        }
    })
    # F (Data) - дата dd.mm.yyyy
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": total_rows,
                "startColumnIndex": 5,
                "endColumnIndex": 6
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": "DATE",
                        "pattern": "dd.MM.yyyy"
                    }
                }
            },
            "fields": "userEnteredFormat.numberFormat"
        }
    })
    # G-K (Fact Start, Non Productive, Not Categorized, Prodactive, Total) - время
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "endRowIndex": total_rows,
                "startColumnIndex": 6,
                "endColumnIndex": 11
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": "TIME",
                        "pattern": "[h]:mm"
                    }
                }
            },
            "fields": "userEnteredFormat.numberFormat"
        }
    })
    
    # 7. Автоширина колонок
    for col in range(13):
        requests.append({
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": col,
                    "endIndex": col + 1
                }
            }
        })
    
    # Выполняем все запросы
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=settings.spreadsheet_id,
            body={"requests": requests}
        ).execute()
        logger.info(f"✅ Цветное форматирование применено")
    except Exception as e:
        logger.error(f"Ошибка применения форматирования: {e}")
