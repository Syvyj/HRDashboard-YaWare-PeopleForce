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

// Shared filter utilities for multi-select modals
function buildFilterParams(dateFromValue, dateToValue, userValue, selectedFilters, selectedEmployees) {
  const params = new URLSearchParams();
  if (dateFromValue) {
    params.set('date_from', dateFromValue);
  }
  if (dateToValue) {
    params.set('date_to', dateToValue);
  }
  if (userValue) {
    params.set('user', userValue);
  }
  // Support multiple selected employees
  if (selectedEmployees && selectedEmployees.size > 0) {
    Array.from(selectedEmployees).forEach(key => {
      params.append('user_key', key);
    });
  }
  // Support multiple filter values
  if (selectedFilters && selectedFilters.projects && selectedFilters.projects.size > 0) {
    Array.from(selectedFilters.projects).forEach(project => {
      params.append('project', project);
    });
  }
  if (selectedFilters && selectedFilters.departments && selectedFilters.departments.size > 0) {
    Array.from(selectedFilters.departments).forEach(department => {
      params.append('department', department);
    });
  }
  if (selectedFilters && selectedFilters.units && selectedFilters.units.size > 0) {
    Array.from(selectedFilters.units).forEach(unit => {
      params.append('unit', unit);
    });
  }
  if (selectedFilters && selectedFilters.teams && selectedFilters.teams.size > 0) {
    Array.from(selectedFilters.teams).forEach(team => {
      params.append('team', team);
    });
  }
  return params;
}

function updateFilterDisplay(displayElement, selectedFilters) {
  const parts = [];
  if (selectedFilters.projects && selectedFilters.projects.size > 0) {
    parts.push(`Проекты: ${Array.from(selectedFilters.projects).join(', ')}`);
  }
  if (selectedFilters.departments && selectedFilters.departments.size > 0) {
    parts.push(`Департаменты: ${Array.from(selectedFilters.departments).join(', ')}`);
  }
  if (selectedFilters.units && selectedFilters.units.size > 0) {
    parts.push(`Подразделения: ${Array.from(selectedFilters.units).join(', ')}`);
  }
  if (selectedFilters.teams && selectedFilters.teams.size > 0) {
    parts.push(`Команды: ${Array.from(selectedFilters.teams).join(', ')}`);
  }
  if (displayElement) {
    displayElement.textContent = parts.length > 0 ? parts.join(' | ') : '';
  }
}

function renderFilterCheckboxes(containerEl, filterValues, selectedSet, onChange) {
  if (!containerEl) {
    return;
  }
  containerEl.innerHTML = '';
  (filterValues || []).forEach(value => {
    const label = document.createElement('label');
    label.className = 'form-check mt-2';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'form-check-input';
    checkbox.checked = selectedSet.has(value);
    checkbox.addEventListener('change', (e) => {
      if (e.target.checked) {
        selectedSet.add(value);
      } else {
        selectedSet.delete(value);
      }
      if (onChange) onChange();
    });
    const span = document.createElement('span');
    span.className = 'form-check-label';
    span.textContent = value;
    label.appendChild(checkbox);
    label.appendChild(span);
    containerEl.appendChild(label);
  });
}

// Экспортируем для использования в других модулях
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { 
    STATUS_LABELS, 
    escapeHtml, 
    minutesToDuration, 
    formatISO,
    buildFilterParams,
    updateFilterDisplay,
    renderFilterCheckboxes
  };
}
