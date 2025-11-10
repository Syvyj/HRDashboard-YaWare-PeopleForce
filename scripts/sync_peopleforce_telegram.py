#!/usr/bin/env python3
"""
Скрипт для ручного запуску синхронізації telegram та manager з PeopleForce.
Використовується для тестування або разового оновлення даних.
"""
import sys
from pathlib import Path

# Додаємо кореневу директорію в path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flask import Flask
from dashboard_app.tasks import _sync_peopleforce_metadata
from dashboard_app.extensions import db

def main():
    """Запуск синхронізації PeopleForce."""
    print("=" * 80)
    print("СИНХРОНІЗАЦІЯ TELEGRAM ТА MANAGER З PEOPLEFORCE")
    print("=" * 80)
    print()
    
    # Створюємо мінімальний Flask app для контексту
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{project_root}/instance/dashboard.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    db.init_app(app)
    
    with app.app_context():
        print("Запускаю синхронізацію...\n")
        try:
            _sync_peopleforce_metadata(app)
            print("\n✅ Синхронізація успішно завершена!")
            print("\nПеревірте user_schedules.json - має з'явитися:")
            print("  - telegram_username (робочий телеграм з PeopleForce)")
            print("  - manager_name (Прізвище_Ім'я керівника)")
            print("  - manager_telegram (телеграм керівника)")
        except Exception as e:
            print(f"\n❌ Помилка під час синхронізації: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    print("\n" + "=" * 80)
    return 0


if __name__ == '__main__':
    sys.exit(main())
