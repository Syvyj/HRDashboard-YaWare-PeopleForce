"""Тестування та генерація звітів про присутність"""
import sys
from datetime import datetime, timedelta
from tracker_alert.services.attendance_reports import report_generator


def generate_report(date: str = None, detailed: bool = True):
    """Згенерувати та вивести звіт за дату."""
    
    print("\n🔄 Генеруємо звіт...\n")
    
    # Генеруємо звіт
    report = report_generator.generate_daily_report(date)
    
    # Форматуємо і виводимо
    text_report = report_generator.format_report_text(report, detailed=detailed)
    print(text_report)
    
    # Додаткова статистика
    print("\n\n" + "="*80)
    print("📊 ДОДАТКОВА АНАЛІТИКА")
    print("="*80 + "\n")
    
    # Топ-10 продуктивних
    if report["top_productive"]:
        print("🏆 ТОП-10 НАЙПРОДУКТИВНІШИХ:\n")
        for i, user in enumerate(report["top_productive"][:10], 1):
            productive_hours = user["productive_seconds"] / 3600
            total_hours = user["total_seconds"] / 3600
            efficiency = (user["productive_seconds"] / user["total_seconds"] * 100) if user["total_seconds"] > 0 else 0
            
            print(f"  {i}. {user['name']}")
            print(f"     Продуктивно: {user['productive_formatted']} ({efficiency:.1f}%)")
            print(f"     Загалом: {user['total_formatted']}")
            print()
    
    # Статистика по локаціях
    location_stats = {}
    for schedule_data in report["by_schedule"].values():
        for user in report["late_users"] + report["on_leave"]:
            loc = user.get("location") or "Unknown"
            if loc not in location_stats:
                location_stats[loc] = {"total": 0, "late": 0}
            location_stats[loc]["total"] += 1
            if user in report["late_users"]:
                location_stats[loc]["late"] += 1
    
    if location_stats:
        print("\n📍 СТАТИСТИКА ПО ЛОКАЦІЯХ:\n")
        for location, stats in sorted(location_stats.items(), key=lambda x: x[1]["total"], reverse=True):
            print(f"  📍 {location}")
            print(f"     Запізнилися: {stats['late']} з {stats['total']}")
            print()


def compare_days(days: int = 7):
    """Порівняти запізнення за останні N днів."""
    
    print(f"\n📈 ДИНАМІКА ЗАПІЗНЕНЬ ЗА ОСТАННІ {days} ДНІВ")
    print("="*80 + "\n")
    
    today = datetime.now()
    
    daily_stats = []
    
    for i in range(days):
        date = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        day_name = (today - timedelta(days=i)).strftime("%A")
        
        try:
            report = report_generator.generate_daily_report(date)
            
            stats = {
                "date": date,
                "day": day_name,
                "total": report["summary"]["total_users"],
                "worked": report["summary"]["users_worked"],
                "late": report["summary"]["users_late"],
                "on_leave": report["summary"]["users_on_leave"]
            }
            
            daily_stats.append(stats)
            
            late_percent = (stats["late"] / stats["worked"] * 100) if stats["worked"] > 0 else 0
            
            print(f"📅 {date} ({day_name})")
            print(f"   Працювали: {stats['worked']}/{stats['total']}")
            print(f"   Запізнилися: {stats['late']} ({late_percent:.1f}%)")
            print(f"   У відпустці: {stats['on_leave']}")
            print()
            
        except Exception as e:
            print(f"❌ Помилка для {date}: {e}")
            print()
    
    # Загальна статистика
    if daily_stats:
        total_late = sum(s["late"] for s in daily_stats)
        total_worked = sum(s["worked"] for s in daily_stats)
        avg_late = total_late / len(daily_stats)
        avg_late_percent = (total_late / total_worked * 100) if total_worked > 0 else 0
        
        print("="*80)
        print("📊 ПІДСУМОК:")
        print("="*80)
        print(f"\n  Середньо запізнень на день: {avg_late:.1f}")
        print(f"  Загальний відсоток запізнень: {avg_late_percent:.1f}%")
        print(f"  Всього запізнень за {days} днів: {total_late}")
        print()


def main():
    """Головна функція."""
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "today":
            # Звіт за сьогодні
            generate_report()
            
        elif command == "yesterday":
            # Звіт за вчора
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            generate_report(yesterday)
            
        elif command == "date" and len(sys.argv) > 2:
            # Звіт за конкретну дату
            date = sys.argv[2]
            generate_report(date)
            
        elif command == "week":
            # Динаміка за тиждень
            compare_days(7)
            
        elif command == "brief":
            # Короткий звіт за сьогодні
            generate_report(detailed=False)
            
        else:
            print("❌ Невідома команда")
            print("\nДоступні команди:")
            print("  python3 -m tracker_alert.scripts.generate_attendance_report today")
            print("  python3 -m tracker_alert.scripts.generate_attendance_report yesterday")
            print("  python3 -m tracker_alert.scripts.generate_attendance_report date YYYY-MM-DD")
            print("  python3 -m tracker_alert.scripts.generate_attendance_report week")
            print("  python3 -m tracker_alert.scripts.generate_attendance_report brief")
    else:
        # За замовчуванням - звіт за сьогодні
        generate_report()


if __name__ == "__main__":
    main()
