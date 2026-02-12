# Fixed holidays (month, day) excluded from work-day count in monthly report.
# Jan 1 is non-working for everyone; without this, January would show 22 work days instead of 21.
FIXED_HOLIDAYS_MD = frozenset([
    (1, 1),   # New Year
    (1, 7),   # Christmas (Orthodox)
])

SEVEN_DAY_WORK_WEEK_IDS = {
    297356,  # Iliin Eugeniy
    297357,  # Chernov Leonid
    297358,  # Demidov Viktor
    297365,  # Shpak Andrew
    551929,  # Zbutevich Illia
    297362,  # Andriy Pankov
    297363,  # Kiliovyi Evhen
    297364,  # Larina Olena
    356654,  # Pankov Oleksandr
    374722,  # Stopochkin Nykyta
    433837,  # Alina Serdiuk
    406860,  # Zdorovets Yuliia
    372364,  # Shubska Oleksandra
}

WEEK_TOTAL_USER_ID_SUFFIX = '__week_total'

MANUAL_FLAG_MAP = {
    'scheduled_start': 'manual_scheduled_start',
    'actual_start': 'manual_actual_start',
    'minutes_late': 'manual_minutes_late',
    'non_productive_minutes': 'manual_non_productive_minutes',
    'not_categorized_minutes': 'manual_not_categorized_minutes',
    'productive_minutes': 'manual_productive_minutes',
    'total_minutes': 'manual_total_minutes',
    'corrected_total_minutes': 'manual_corrected_total_minutes',
    'status': 'manual_status',
    'notes': 'manual_notes',
    'leave_reason': 'manual_leave_reason',
}
MANUAL_TRACKED_FIELDS = tuple(MANUAL_FLAG_MAP.keys())
