"""Створення бази користувачів з їх графіками на основі CSV звітів"""
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import json

def parse_time(time_str):
    """Парсить час у форматі HH:MM:SS або HH:MM"""
    if not time_str or time_str.strip() == '':
        return None
    
    time_str = time_str.strip()
    
    if time_str.count(':') == 2:
        return datetime.strptime(time_str, "%H:%M:%S").time()
    elif time_str.count(':') == 1:
        return datetime.strptime(time_str, "%H:%M").time()
    
    return None

def time_to_minutes(time_obj):
    """Конвертує time в хвилини від початку дня"""
    if not time_obj:
        return None
    return time_obj.hour * 60 + time_obj.minute

def extract_users_from_time_report(csv_path):
    """
    Витягує користувачів та їх графіки з 'Отчет по времени'.
    
    Логіка:
    - Якщо є поле 'Опоздание', то початок = 'Первое действие' - 'Опоздание'
    - Якщо немає 'Опоздание', то користувач не запізнився = використовуємо 'Первое действие' як є
    """
    
    users = {}
    
    encodings = ['windows-1251', 'cp1251', 'utf-8']
    
    for encoding in encodings:
        try:
            with open(csv_path, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f, delimiter=';')
                
                for row in reader:
                    employee_full = row.get('Сотрудник', '').strip()
                    first_action = row.get('Первое действие', '').strip()
                    lateness = row.get('Опоздание', '').strip()
                    group = row.get('Группа', '').strip()
                    
                    if not employee_full or not first_action:
                        continue
                    
                    # Парсимо email з формату "Name Surname, email@example.com"
                    if ', ' not in employee_full:
                        continue
                    
                    name, email = employee_full.split(', ', 1)
                    
                    # Парсимо час
                    first_time = parse_time(first_action)
                    if not first_time:
                        continue
                    
                    first_minutes = time_to_minutes(first_time)
                    
                    # Визначаємо початок роботи
                    if lateness and lateness.strip():
                        # Є запізнення - рахуємо
                        lateness_time = parse_time(lateness)
                        if lateness_time:
                            lateness_minutes = time_to_minutes(lateness_time)
                            expected_minutes = first_minutes - lateness_minutes
                        else:
                            # Не можемо розпарсити запізнення
                            expected_minutes = first_minutes
                    else:
                        # Немає запізнення - беремо першу дію
                        # Округляємо до найближчої години (9:00, 10:00, 11:00)
                        hour = first_time.hour
                        if first_time.minute <= 15:
                            expected_minutes = hour * 60
                        else:
                            expected_minutes = (hour + 1) * 60
                    
                    expected_hour = expected_minutes // 60
                    expected_minute = expected_minutes % 60
                    expected_start = f"{expected_hour:02d}:{expected_minute:02d}"
                    
                    # Зберігаємо або оновлюємо
                    if email not in users:
                        users[email] = {
                            'name': name,
                            'email': email,
                            'expected_start': expected_start,
                            'group': group,
                            'samples': []
                        }
                    
                    users[email]['samples'].append({
                        'first_action': first_action,
                        'lateness': lateness or None,
                        'calculated_start': expected_start
                    })
                
                break  # Успішно прочитали
                
        except UnicodeDecodeError:
            continue
    
    return users

def build_user_database():
    """Створює базу користувачів з усіх CSV звітів"""
    
    csv_dir = Path("/Users/User-001/Documents/YaWare_Bot/tracker_alert/csv_expo")
    
    print(f"\n{'='*80}")
    print(f"🔨 Створення бази користувачів з графіками")
    print(f"{'='*80}\n")
    
    # Збираємо дані з усіх звітів
    all_users = {}
    
    time_reports = list(csv_dir.glob("Отчет по времени*.csv"))
    
    print(f"📁 Знайдено {len(time_reports)} звітів по времени")
    print()
    
    for report in time_reports:
        print(f"📄 Обробка: {report.name}")
        users = extract_users_from_time_report(report)
        
        for email, data in users.items():
            if email not in all_users:
                all_users[email] = {
                    'name': data['name'],
                    'email': email,
                    'group': data['group'],
                    'start_times': []
                }
            
            # Додаємо всі зразки часу початку
            for sample in data['samples']:
                all_users[email]['start_times'].append(sample['calculated_start'])
        
        print(f"   ✅ Оброблено {len(users)} користувачів")
    
    print(f"\n{'='*80}")
    print(f"📊 Визначення найбільш вірогідного часу початку")
    print(f"{'='*80}\n")
    
    # Для кожного користувача визначаємо найчастіший час
    user_schedules = {}
    
    for email, data in all_users.items():
        # Рахуємо частоту кожного часу
        time_counts = defaultdict(int)
        for start_time in data['start_times']:
            time_counts[start_time] += 1
        
        # Беремо найчастіший
        most_common_time = max(time_counts.items(), key=lambda x: x[1])
        start_time = most_common_time[0]
        frequency = most_common_time[1]
        
        user_schedules[email] = {
            'name': data['name'],
            'email': email,
            'group': data['group'],
            'start_time': start_time,
            'confidence': f"{frequency}/{len(data['start_times'])}",
            'all_samples': list(time_counts.keys())
        }
    
    print(f"✅ Визначено графік для {len(user_schedules)} користувачів")
    
    # Статистика по часу початку
    print(f"\n{'='*80}")
    print(f"📊 Розподіл по часу початку")
    print(f"{'='*80}\n")
    
    start_time_stats = defaultdict(list)
    for email, data in user_schedules.items():
        start_time_stats[data['start_time']].append(data['name'])
    
    for start_time, users in sorted(start_time_stats.items()):
        print(f"⏰ {start_time} - {len(users)} осіб")
    
    # Зберігаємо у JSON
    output_path = Path("/Users/User-001/Documents/YaWare_Bot/config/user_schedules.json")
    
    output_data = {
        '_metadata': {
            'generated_at': datetime.now().isoformat(),
            'total_users': len(user_schedules),
            'source': 'CSV reports from YaWare admin panel'
        },
        'users': user_schedules
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*80}")
    print(f"✅ База збережена: {output_path}")
    print(f"{'='*80}\n")
    
    # Показуємо приклади
    print(f"\n📋 Приклади записів:\n")
    
    for i, (email, data) in enumerate(list(user_schedules.items())[:5], 1):
        print(f"{i}. {data['name']}")
        print(f"   Email: {email}")
        print(f"   Відділ: {data['group']}")
        print(f"   Початок роботи: {data['start_time']}")
        print(f"   Впевненість: {data['confidence']} зразків")
        if len(data['all_samples']) > 1:
            print(f"   Інші варіанти: {', '.join(data['all_samples'])}")
        print()
    
    return user_schedules

if __name__ == "__main__":
    build_user_database()
