// Общие утилиты для работы с attendance
const STATUS_LABELS = {
  present: 'Присутствовал',
  late: 'Опоздал',
  absent: 'Отсутствовал',
  leave: 'Отпуск / отсутствие',
};

function escapeHtml(str) {
  return (str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function minutesToDuration(minutes) {
  if (minutes == null) {
    return '';
  }
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return `${hrs}:${mins.toString().padStart(2, '0')}`;
}

function formatISO(date) {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

// Экспортируем для использования в других модулях
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { STATUS_LABELS, escapeHtml, minutesToDuration, formatISO };
}
