(function () {
  const container = document.getElementById('report-container');
  if (!container) {
    return;
  }

  // Функція генерації telegram username з імені
  function generateTelegramUsername(fullName) {
    if (!fullName) return '';
    const parts = fullName.trim().split(/\s+/);
    if (parts.length < 2) return parts[0] || '';
    return `${parts[0]}_${parts[1]}`;
  }

  const form = document.getElementById('filters-form');
  const searchBtn = document.getElementById('search-btn');
  const reportBtn = document.getElementById('report-generate-btn');
  const reportModalEl = document.getElementById('reportModal');
  const reportModal = reportModalEl ? new bootstrap.Modal(reportModalEl) : null;

  const dateFromInput = document.getElementById('filter-date-from');
  const dateToInput = document.getElementById('filter-date-to');
  const userInput = document.getElementById('filter-user');
  const projectSelect = document.getElementById('filter-project');
  const departmentSelect = document.getElementById('filter-department');
  const teamSelect = document.getElementById('filter-team');
  const resetBtn = document.getElementById('reset-filters');
  const applySecondaryBtn = document.getElementById('filters-apply-secondary');
  const resetSecondaryBtn = document.getElementById('filters-reset-secondary');
  
  // Modal filter elements
  const filtersModalEl = document.getElementById('filtersModal');
  const openFiltersModalBtn = document.getElementById('open-filters-modal');
  const filterModalApplyBtn = document.getElementById('filter-modal-apply');
  const filterModalClearBtn = document.getElementById('filter-modal-clear');
  const selectedFiltersDisplay = document.getElementById('selected-filters-display');
  const filterProjectsList = document.getElementById('filter-projects-list');
  const filterDepartmentsList = document.getElementById('filter-departments-list');
  const filterUnitsList = document.getElementById('filter-units-list');
  const filterTeamsList = document.getElementById('filter-teams-list');
  
  let filtersModal = null; // Will be initialized when needed
  
  let currentFilterOptions = { projects: [], departments: [], units: [], teams: [] };
  let selectedFilters = { projects: new Set(), departments: new Set(), units: new Set(), teams: new Set() };
  
  const recordEditModalEl = document.getElementById('recordEditModal');
  const recordEditModal = recordEditModalEl ? new bootstrap.Modal(recordEditModalEl) : null;
  
  const weekNotesModalEl = document.getElementById('weekNotesModal');
  const weekNotesModal = weekNotesModalEl ? new bootstrap.Modal(weekNotesModalEl) : null;
  const weekNotesForm = document.getElementById('week-notes-form');
  const weekNotesText = document.getElementById('week-notes-text');
  const weekNotesUserLabel = document.getElementById('week-notes-username');
  const weekNotesSaveBtn = document.getElementById('week-notes-save');
  let weekNotesContext = null;
  
  const recordEditForm = document.getElementById('record-edit-form');
  const recordEditScheduled = document.getElementById('record-edit-scheduled');
  const recordEditActual = document.getElementById('record-edit-actual');
  const recordEditMinutesLate = document.getElementById('record-edit-minutes-late');
  const recordEditNonProductive = document.getElementById('record-edit-non-productive');
  const recordEditNotCategorized = document.getElementById('record-edit-not-categorized');
  const recordEditProductive = document.getElementById('record-edit-productive');
  const recordEditTotal = document.getElementById('record-edit-total');
  const recordEditTotalCorrected = document.getElementById('record-edit-total-corrected');
  const recordEditStatus = document.getElementById('record-edit-status');
  const recordEditUserLabel = document.getElementById('record-edit-username');
  const recordEditNotes = document.getElementById('record-edit-notes');
  const recordEditSaveBtn = document.getElementById('record-edit-save');
  const recordEditSelector = document.getElementById('record-edit-selector');
  const recordEditResetBtn = document.getElementById('record-edit-reset');

  let recordEditContext = null;
  const statusOptionsCache = new Map();
  const userRecordsMap = new Map();
  const isAdmin = document.body.dataset.isAdmin === '1';
  const canEdit = document.body.dataset.canEdit === '1';

  function ensureDefaultWeekRange() {
    if (dateFromInput.value && dateToInput.value) {
      return;
    }
    const today = new Date();
    const weekday = today.getDay(); // 0=Sun
    const diffToMonday = weekday === 0 ? -6 : 1 - weekday;
    const monday = new Date(today);
    monday.setDate(today.getDate() + diffToMonday);
    const friday = new Date(monday);
    friday.setDate(monday.getDate() + 4);
    dateFromInput.value = formatISO(monday);
    dateToInput.value = formatISO(friday);
  }

  function populateSelect(selectEl, values, placeholder) {
    const currentValue = selectEl.value;
    const options = [ `<option value="">${placeholder}</option>` ];
    values.forEach((value) => {
      options.push(`<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`);
    });
    selectEl.innerHTML = options.join('');
    if (currentValue && values.includes(currentValue)) {
      selectEl.value = currentValue;
    }
  }

  function setSelectValue(selectEl, value) {
    if (!value) {
      selectEl.value = '';
      return;
    }
    const hasOption = Array.from(selectEl.options).some((option) => option.value === value);
    if (!hasOption) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      selectEl.appendChild(option);
    }
    selectEl.value = value;
  }

  function buildParams() {
    return buildFilterParams(dateFromInput.value, dateToInput.value, userInput.value, selectedFilters);
  }

  function createCell(text, className) {
    const td = document.createElement('td');
    td.textContent = text || '';
    if (className) {
      td.className = className;
    }
    return td;
  }

  function createTotalCell(row) {
    const td = document.createElement('td');
    td.textContent = row.total_display || '';
    
    // Перевіряємо чи треба підсвітити червоним
    const divisionName = (row.division_name || '').toLowerCase();
    const totalMinutes = row.total_minutes || 0;
    
    let threshold = 0;
    if (divisionName === 'agency' || divisionName === 'apps') {
      threshold = 390; // 6.5 годин
    } else if (divisionName === 'adnetwork' || divisionName === 'consulting' || divisionName === 'cons') {
      threshold = 420; // 7 годин
    }
    
    if (threshold > 0 && totalMinutes < threshold) {
      td.style.color = '#dc3545'; // Bootstrap text-danger color
    }
    
    return td;
  }

  function createNotesCell(row, canEdit = false, userKey = null, isWeekTotal = false) {
    const td = document.createElement('td');
    td.className = 'notes-cell';
    td.style.position = 'relative';
    
    const contentWrapper = document.createElement('div');
    contentWrapper.style.paddingRight = canEdit && userKey ? '32px' : '0';
    contentWrapper.style.lineHeight = '1.3';
    contentWrapper.style.textAlign = 'left';
    
    const display = document.createElement('div');
    display.className = 'notes-display';
    display.style.lineHeight = '1.3';
    display.textContent = row.notes_display || '';
    contentWrapper.appendChild(display);

    if (row.leave_reason && row.notes) {
      const leaveInfo = document.createElement('div');
      leaveInfo.className = 'text-muted small';
      leaveInfo.style.lineHeight = '1.3';
      
      // Додаємо "(0.5 дня)" якщо це половина дня відпустки
      let leaveText = row.leave_reason;
      if (row.half_day_amount === 0.5) {
        leaveText += ' (0.5 дня)';
      }
      leaveInfo.textContent = leaveText;
      contentWrapper.appendChild(leaveInfo);
    }
    
    td.appendChild(contentWrapper);
    
    if (canEdit && userKey) {
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'btn btn-link p-0 text-primary';
      editBtn.style.position = 'absolute';
      editBtn.style.right = '8px';
      editBtn.style.top = '50%';
      editBtn.style.transform = 'translateY(-50%)';
      editBtn.style.minWidth = '24px';
      editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
      editBtn.title = 'Редактировать';
      
      if (isWeekTotal) {
        editBtn.dataset.weekNotesEdit = userKey;
      } else {
        editBtn.dataset.weekEdit = userKey;
      }
      
      td.appendChild(editBtn);
    }
    
    return td;
  }

  function fillStatusOptions(selectEl, options, currentValue) {
    if (!selectEl) {
      return;
    }
    selectEl.innerHTML = '';
    const emptyOption = document.createElement('option');
    emptyOption.value = '';
    emptyOption.textContent = '—';
    selectEl.appendChild(emptyOption);
    const normalized = new Set();
    (options || []).forEach((status) => {
      const option = document.createElement('option');
      option.value = status;
      option.textContent = STATUS_LABELS[status] || status;
      selectEl.appendChild(option);
      normalized.add(status);
    });
    if (currentValue && !normalized.has(currentValue)) {
      const option = document.createElement('option');
      option.value = currentValue;
      option.textContent = STATUS_LABELS[currentValue] || currentValue;
      selectEl.appendChild(option);
    }
    selectEl.value = currentValue || '';
    const hint = currentValue ? STATUS_LABELS[currentValue] : '';
    selectEl.setAttribute(
      'title',
      hint
        ? `${currentValue}: ${hint}`
        : 'Статус дня: present — присутствовал, late — опоздал, absent — отсутствовал, leave — отпуск'
    );
  }

  if (recordEditSelector) {
    recordEditSelector.addEventListener('change', (event) => {
      if (!recordEditContext) {
        return;
      }
      const index = Number(event.target.value);
      if (Number.isNaN(index)) {
        return;
      }
      loadRowToModal(index);
      updateStatusField();
    });
  }

  if (recordEditResetBtn) {
    recordEditResetBtn.addEventListener('click', async () => {
      if (!recordEditContext) {
        return;
      }
      const { userKey, recordId } = recordEditContext;
      recordEditResetBtn.disabled = true;
      try {
        const response = await fetch(`/api/users/${encodeURIComponent(userKey)}/records/${recordId}`, {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ reset_manual: true })
        });
        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(error.error || 'Не удалось скинуть правки');
        }
        if (recordEditModal) {
          recordEditModal.hide();
        }
        alert('Ручные правки скинуты. Данные обновятся после следующей синхронизации.');
        await loadData();
      } catch (error) {
        console.error(error);
        alert(error.message || 'Не удалось скинуть правки');
      } finally {
        recordEditResetBtn.disabled = false;
      }
    });
  }

  async function fetchStatusOptions(userKeyRaw) {
    if (!userKeyRaw) {
      return [];
    }
    if (statusOptionsCache.has(userKeyRaw)) {
      return statusOptionsCache.get(userKeyRaw);
    }
    const params = new URLSearchParams();
    if (dateFromInput && dateFromInput.value) {
      params.set('date_from', dateFromInput.value);
    }
    if (dateToInput && dateToInput.value) {
      params.set('date_to', dateToInput.value);
    }
    const query = params.toString();
    const response = await fetch(`/api/users/${encodeURIComponent(userKeyRaw)}${query ? `?${query}` : ''}`);
    if (!response.ok) {
      throw new Error('Не удалось получить статусы');
    }
    const payload = await response.json();
    const options = payload.status_options || [];
    statusOptionsCache.set(userKeyRaw, options);
    return options;
  }

  function populateRecordSelector(rows) {
    if (!recordEditSelector) {
      return;
    }
    recordEditSelector.innerHTML = '';
    rows.forEach((row, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      const labelParts = [row.date_display || row.date_iso || '', row.actual_start || row.actual_start_hm || ''];
      const label = labelParts.filter(Boolean).join(' • ');
      option.textContent = label || `Запис ${index + 1}`;
      recordEditSelector.appendChild(option);
    });
    recordEditSelector.value = '0';
  }

  function loadRowToModal(index) {
    if (!recordEditContext) {
      return;
    }
    const rows = recordEditContext.rows || [];
    const row = rows[index];
    if (!row) {
      return;
    }
    recordEditContext.index = index;
    recordEditContext.recordId = row.record_id;
    if (recordEditSelector) {
      recordEditSelector.value = String(index);
    }
    if (recordEditUserLabel) {
      recordEditUserLabel.textContent = recordEditContext.userName || row.user_name || recordEditContext.userKey;
    }
    recordEditScheduled.value = row.scheduled_start || row.scheduled_start_hm || '';
    recordEditActual.value = row.actual_start || row.actual_start_hm || '';
    recordEditMinutesLate.value = row.minutes_late_display || minutesToDuration(row.minutes_late) || '';
    recordEditNonProductive.value = row.non_productive_display || '';
    recordEditNotCategorized.value = row.not_categorized_display || '';
    recordEditProductive.value = row.productive_display || '';
    recordEditTotal.value = row.total_display || '';
    recordEditTotalCorrected.value = row.corrected_total_display || '';
    if (recordEditNotes) {
      recordEditNotes.value = row.notes || '';
    }
    if (recordEditStatus && (!statusOptionsCache.has(recordEditContext.userKey) || !(statusOptionsCache.get(recordEditContext.userKey) || []).length)) {
      recordEditStatus.value = row.status || '';
    }
  }

  function updateStatusField() {
    if (!recordEditContext || !recordEditStatus) {
      return;
    }
    const options = statusOptionsCache.get(recordEditContext.userKey) || [];
    const row = recordEditContext.rows[recordEditContext.index] || {};
    fillStatusOptions(recordEditStatus, options, row.status);
  }

  function openWeekNotesModal(userKey, userName, currentNotes) {
    if (!weekNotesModal || !weekNotesForm) {
      return;
    }
    weekNotesContext = {
      userKey: userKey,
      userName: userName || userKey
    };
    weekNotesUserLabel.textContent = userName || userKey;
    weekNotesText.value = currentNotes || '';
    weekNotesModal.show();
  }

  async function openUserEditModal(userKeyRaw, rows, userName) {
    if (!recordEditModal || !recordEditForm || !rows || !rows.length) {
      return;
    }
    recordEditContext = {
      userKey: userKeyRaw,
      rows,
      userName: userName || rows[0].user_name || userKeyRaw,
      index: 0,
      recordId: rows[0].record_id,
    };
    populateRecordSelector(rows);
    loadRowToModal(0);
    recordEditModal.show();
    if (recordEditResetBtn) {
      recordEditResetBtn.disabled = false;
    }
    try {
      await fetchStatusOptions(userKeyRaw);
    } catch (error) {
      console.error(error);
    }
    updateStatusField();
  }

  function updateSelectedFiltersDisplay() {
    updateFilterDisplay(selectedFiltersDisplay, selectedFilters);
  }

  function renderFilterModal() {
    renderFilterCheckboxes(filterProjectsList, currentFilterOptions.projects, selectedFilters.projects);
    renderFilterCheckboxes(filterDepartmentsList, currentFilterOptions.departments, selectedFilters.departments);
    renderFilterCheckboxes(filterUnitsList, currentFilterOptions.units, selectedFilters.units);
    renderFilterCheckboxes(filterTeamsList, currentFilterOptions.teams, selectedFilters.teams);
  }

  function renderReport(data) {
    container.innerHTML = '';

    const filterMeta = data.filters || {};
    const filterOptions = filterMeta.options || {};

    // Store filter options for modal
    currentFilterOptions = {
      projects: filterOptions.projects || [],
      departments: filterOptions.departments || [],
      units: filterOptions.units || [],
      teams: filterOptions.teams || []
    };

    // selectedFilters already contains the current selection from modal
    // Don't restore old single-value filters - keep what user selected
    updateSelectedFiltersDisplay();

    statusOptionsCache.clear();
    userRecordsMap.clear();

    if (!data.items || data.items.length === 0) {
      container.innerHTML = '<div class="alert alert-secondary">По заданным параметрам ничего не найдено.</div>';
      return;
    }

    data.items.forEach((item) => {
      const schedule = item.schedule || {};
      const planStart = item.plan_start || schedule.start_time || '';
      const location = item.location || schedule.location || '';

      const card = document.createElement('div');
      card.className = 'user-block bg-white';

      const metaPanel = document.createElement('div');
      metaPanel.className = 'user-meta-panel';
      const metaLines = [];
      const metaMainLine = [];
      
      // Відображаємо всі 4 рівні ієрархії: Division → Direction → Unit → Team
      if (item.project) {
        metaMainLine.push(
          `<a href="#" class="meta-link" data-filter="project" data-value="${encodeURIComponent(item.project)}">${escapeHtml(item.project)}</a>`
        );
      }
      if (item.department) {
        metaMainLine.push(
          `<a href="#" class="meta-link" data-filter="department" data-value="${encodeURIComponent(item.department)}">${escapeHtml(item.department)}</a>`
        );
      }
      // Додаємо Unit (якщо є в даних)
      if (schedule.unit_name) {
        metaMainLine.push(
          `<a href="#" class="meta-link" data-filter="unit" data-value="${encodeURIComponent(schedule.unit_name)}">${escapeHtml(schedule.unit_name)}</a>`
        );
      }
      if (item.team) {
        metaMainLine.push(
          `<a href="#" class="meta-link" data-filter="team" data-value="${encodeURIComponent(item.team)}">${escapeHtml(item.team)}</a>`
        );
      }

      if (metaMainLine.length) {
        metaLines.push(metaMainLine.join(' • '));
      }
      const metaLinksHtml = metaLines
        .map((line) => `<span class="meta-link-line">${line}</span>`)
        .join('');
      const userKeyRaw = schedule.email || item.user_id || item.user_name;
      userRecordsMap.set(userKeyRaw, { rows: item.rows || [], name: item.user_name });
      const userKey = encodeURIComponent(userKeyRaw);
      
      // Build logo links HTML
      let logoLinksHtml = '';
      if (item.user_id) {
        logoLinksHtml += `<a href="https://app.yaware.com/reports/by-user/index/user/${item.user_id}" target="_blank" rel="noopener noreferrer" class="no-print" title="YaWare Profile"><img src="/static/logo/yaware_logo.png" alt="YaWare" style="height: 40px; "></a>`;
      }
      if (schedule.peopleforce_id) {
        logoLinksHtml += `<a href="https://evrius.peopleforce.io/employees/${schedule.peopleforce_id}" target="_blank" rel="noopener noreferrer" class="no-print" title="PeopleForce Profile"><img src="/static/logo/pf_logo.webp" alt="PeopleForce" style="height: 40px;"></a>`;
      }
      // Telegram username з можливістю автогенерації
      const telegramUsername = schedule.telegram_username || generateTelegramUsername(item.user_name);
      if (telegramUsername) {
        // Видаляємо @ якщо є на початку
        const cleanTelegram = telegramUsername.replace(/^@/, '');
        logoLinksHtml += `<a href="https://t.me/${cleanTelegram}" target="_blank" rel="noopener noreferrer" class="no-print" title="Telegram"><img src="/static/logo/tg_logo.png" alt="Telegram" style="height: 40px;"></a>`;
      }
      
      metaPanel.innerHTML = `
        <div class="meta-name">
          <a href="/users/${userKey}">${escapeHtml(item.user_name)}</a>
        </div>
        <div class="meta-links">${metaLinksHtml}</div>
        <div>
          <div class="meta-loc-block">
            <div class="meta-label">Plan start:</div>
            <div class="meta-plan">${planStart || '--'}</div>
          </div>
          <div class="meta-loc-block">
            <div class="meta-label">Location:</div>
            <div class="meta-location">${location || '--'}</div>
          </div>
        </div>
        ${logoLinksHtml ? `<span class="ms-2">${logoLinksHtml}</span>` : ''}
      `;
      card.appendChild(metaPanel);

      const reportWrapper = document.createElement('div');
      reportWrapper.className = 'reports-wrapper';
      card.appendChild(reportWrapper);

      const table = document.createElement('table');
      table.className = 'table table-sm table-bordered report-table';
      const thead = document.createElement('thead');
      const headRow = document.createElement('tr');
      const headLabels = ['Date', 'Fact Start', 'Non Productive', 'Not Categorized', 'Productive', 'Total', 'Total cor', 'Notes'];
      headLabels.forEach((title) => {
        const th = document.createElement('th');
        th.textContent = title;
        if (title === 'Non Productive') {
          th.classList.add('cell-non');
        } else if (title === 'Not Categorized') {
          th.classList.add('cell-not');
        } else if (title === 'Productive') {
          th.classList.add('cell-prod');
        } else if (title === 'Total') {
          th.classList.add('cell-total');
        } else if (title === 'Total cor') {
          th.classList.add('cell-total');
        }
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      const tbody = document.createElement('tbody');
      item.rows.forEach((row) => {
        const tr = document.createElement('tr');
        tr.appendChild(createCell(row.date_display));
        tr.appendChild(createCell(row.actual_start));
        tr.appendChild(createCell(row.non_productive_display));
        tr.appendChild(createCell(row.not_categorized_display));
        tr.appendChild(createCell(row.productive_display));
        tr.appendChild(createTotalCell(row)); // Використовуємо createTotalCell замість createCell
        tr.appendChild(createCell(row.corrected_total_display || ''));
        tr.appendChild(createNotesCell(row, canEdit, userKeyRaw));
        tbody.appendChild(tr);
      });

      if (item.week_total) {
        const totalRow = document.createElement('tr');
        totalRow.className = 'row-total';
        totalRow.appendChild(createCell(''));
        totalRow.appendChild(createCell('Week total'));
        totalRow.appendChild(createCell(item.week_total.non_productive_display));
        totalRow.appendChild(createCell(item.week_total.not_categorized_display));
        totalRow.appendChild(createCell(item.week_total.productive_display));
        totalRow.appendChild(createCell(item.week_total.total_display));
        totalRow.appendChild(createCell(item.week_total.corrected_total_display || ''));
        // Створюємо фейковий об'єкт з notes_display для Week total
        const weekTotalRow = { notes_display: item.week_total.notes || '' };
        totalRow.appendChild(createNotesCell(weekTotalRow, canEdit, userKeyRaw, true));
        tbody.appendChild(totalRow);
      }

      table.appendChild(tbody);
      reportWrapper.appendChild(table);
      container.appendChild(card);
    });
  }

  async function loadData() {
    const params = buildParams();
    try {
      const response = await fetch(`/api/attendance?${params.toString()}`);
      if (!response.ok) {
        throw new Error('Не удалось получить данные');
      }
      const payload = await response.json();
      renderReport(payload);
    } catch (error) {
      console.error(error);
      container.innerHTML = '<div class="alert alert-danger">Не удалось загрузить данные.</div>';
    }
  }

  function submitFilters(event) {
    if (event) {
      event.preventDefault();
    }
    loadData();
  }

  function resetFilters() {
    dateFromInput.value = '';
    dateToInput.value = '';
    userInput.value = '';
    projectSelect.value = '';
    departmentSelect.value = '';
    teamSelect.value = '';
    ensureDefaultWeekRange();
  }

  form.addEventListener('submit', submitFilters);

  if (searchBtn) {
    searchBtn.addEventListener('click', submitFilters);
  }

  if (applySecondaryBtn) {
    applySecondaryBtn.addEventListener('click', submitFilters);
  }

  function handleReset(event) {
    event.preventDefault();
    resetFilters();
    loadData();
  }

  resetBtn.addEventListener('click', handleReset);

  if (resetSecondaryBtn) {
    resetSecondaryBtn.addEventListener('click', handleReset);
  }

  if (reportBtn && reportModal) {
    reportBtn.addEventListener('click', () => {
      reportModal.show();
    });

    reportModalEl.addEventListener('click', (event) => {
      const target = event.target.closest('[data-report-format]');
      if (!target) {
        return;
      }
      const format = target.getAttribute('data-report-format');
      const params = buildParams();
      const url = format === 'pdf'
        ? `/api/report/pdf?${params.toString()}`
        : `/api/export?${params.toString()}`;
      window.open(url, '_blank');
      reportModal.hide();
    });
  }

  if (canEdit) {
    // Обробка кліку по звичайних рядках (окремі дні)
    container.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-week-edit]');
      if (!btn) {
        return;
      }
      event.preventDefault();
      const userKey = btn.dataset.weekEdit;
      const info = userRecordsMap.get(userKey);
      if (!info || !info.rows || !info.rows.length) {
        alert('Нет записей для редактирования.');
        return;
      }
      openUserEditModal(userKey, info.rows, info.name).catch((error) => {
        console.error(error);
        alert('Не удалось открыть окно редактирования.');
      });
    });

    // Обробка кліку по Week total (коментар до тижня)
    container.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-week-notes-edit]');
      if (!btn) {
        return;
      }
      event.preventDefault();
      const userKey = btn.dataset.weekNotesEdit;
      const info = userRecordsMap.get(userKey);
      if (!info) {
        alert('Нет данных пользователя.');
        return;
      }
      openWeekNotesModal(userKey, info.name, info.week_total?.notes || '');
    });
  }

  document.addEventListener('click', function (event) {
    const link = event.target.closest('.meta-link');
    if (!link) {
      return;
    }
    event.preventDefault();
    const type = link.dataset.filter;
    const value = decodeURIComponent(link.dataset.value || '');
    
    // Відкриваємо модальне вікно і встановлюємо фільтр
    if (type === 'project') {
      selectedFilters.projects.clear();
      selectedFilters.projects.add(value);
    } else if (type === 'department') {
      selectedFilters.departments.clear();
      selectedFilters.departments.add(value);
    } else if (type === 'unit') {
      selectedFilters.units.clear();
      selectedFilters.units.add(value);
    } else if (type === 'team') {
      selectedFilters.teams.clear();
      selectedFilters.teams.add(value);
    }
    
    // Оновлюємо візуальне відображення та завантажуємо дані
    updateSelectedFiltersDisplay();
    loadData();
  });

  // Не підставляємо дати за замовчуванням - backend покаже останні 5 робочих днів
  loadData();

  async function submitRecordEdit(event) {
    event.preventDefault();
    if (!recordEditContext) {
      return;
    }
    const { userKey, recordId } = recordEditContext;
    const payload = {
      scheduled_start: recordEditScheduled.value,
      actual_start: recordEditActual.value,
      minutes_late: recordEditMinutesLate.value,
      non_productive_minutes: recordEditNonProductive.value,
      not_categorized_minutes: recordEditNotCategorized.value,
      productive_minutes: recordEditProductive.value,
      total_minutes: recordEditTotal.value,
      corrected_total_minutes: recordEditTotalCorrected.value,
    };
    if (recordEditStatus) {
      payload.status = recordEditStatus.value;
    }
    if (recordEditNotes) {
      payload.notes = recordEditNotes.value.trim();
    }

    if (recordEditSaveBtn) {
      recordEditSaveBtn.disabled = true;
    }

    try {
      const response = await fetch(`/api/users/${encodeURIComponent(userKey)}/records/${recordId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Не удалось обновить запись');
      }
      if (recordEditModal) {
        recordEditModal.hide();
      }
      alert('Запись обновлена успешно');
      await loadData();
    } catch (error) {
      console.error(error);
      alert(error.message || 'Не удалось обновить запись');
    } finally {
      if (recordEditSaveBtn) {
        recordEditSaveBtn.disabled = false;
      }
    }
  }

  async function submitWeekNotes(event) {
    event.preventDefault();
    if (!weekNotesContext) {
      return;
    }
    
    const { userKey } = weekNotesContext;
    const notes = weekNotesText.value.trim();
    
    if (weekNotesSaveBtn) {
      weekNotesSaveBtn.disabled = true;
    }
    
    try {
      // Тут потрібно створити API endpoint для збереження week notes
      // Поки що просто закриваємо модалку - API буде додано далі
      alert('Функція збереження коментарів до тижня буде реалізована найближчим часом');
      
      if (weekNotesModal) {
        weekNotesModal.hide();
      }
      
      // Після додання API розкоментувати:
      // const response = await fetch(`/api/users/${encodeURIComponent(userKey)}/week-notes`, {
      //   method: 'PATCH',
      //   headers: { 'Content-Type': 'application/json' },
      //   body: JSON.stringify({ notes: notes })
      // });
      // if (!response.ok) {
      //   throw new Error('Failed to save week notes');
      // }
      // await loadData(); // Перезавантажити дані
      // if (weekNotesModal) {
      //   weekNotesModal.hide();
      // }
    } catch (error) {
      console.error(error);
      alert('Не удалось сохранить комментарий: ' + error.message);
    } finally {
      if (weekNotesSaveBtn) {
        weekNotesSaveBtn.disabled = false;
      }
    }
  }

  if (weekNotesForm) {
    weekNotesForm.addEventListener('submit', submitWeekNotes);
  }

  if (weekNotesModalEl) {
    weekNotesModalEl.addEventListener('hidden.bs.modal', () => {
      weekNotesContext = null;
      if (weekNotesForm) {
        weekNotesForm.reset();
      }
      if (weekNotesUserLabel) {
        weekNotesUserLabel.textContent = '';
      }
    });
  }

  if (recordEditForm) {
    recordEditForm.addEventListener('submit', submitRecordEdit);
  }

  if (recordEditModalEl) {
    recordEditModalEl.addEventListener('hidden.bs.modal', () => {
      recordEditContext = null;
      if (recordEditForm) {
        recordEditForm.reset();
      }
      if (recordEditSelector) {
        recordEditSelector.innerHTML = '';
      }
      if (recordEditUserLabel) {
        recordEditUserLabel.textContent = '';
      }
    });
  }

  // Modal filter handlers
  if (openFiltersModalBtn) {
    openFiltersModalBtn.addEventListener('click', () => {
      console.log('=== Opening filters modal ===');
      console.log('Modal element exists:', !!filtersModalEl);
      console.log('Modal element:', filtersModalEl);
      
      renderFilterModal();
      
      // Initialize modal if not already done
      if (!filtersModal && filtersModalEl) {
        console.log('Initializing new bootstrap Modal...');
        filtersModal = new bootstrap.Modal(filtersModalEl);
        console.log('Modal initialized:', !!filtersModal);
      }
      
      if (filtersModal) {
        console.log('Calling modal.show()...');
        filtersModal.show();
        console.log('Modal show() called');
      } else {
        console.error('ERROR: Could not initialize modal');
        alert('Ошибка: не удалось открыть модальное окно');
      }
    });
  }

  if (filterModalApplyBtn) {
    filterModalApplyBtn.addEventListener('click', () => {
      updateSelectedFiltersDisplay();
      submitFilters();
    });
  }

  if (filterModalClearBtn) {
    filterModalClearBtn.addEventListener('click', () => {
      selectedFilters = { projects: new Set(), departments: new Set(), teams: new Set() };
      renderFilterModal();
      updateSelectedFiltersDisplay();
    });
  }

  if (document.getElementById('clear-project-filters')) {
    document.getElementById('clear-project-filters').addEventListener('click', () => {
      selectedFilters = { projects: new Set(), departments: new Set(), units: new Set(), teams: new Set() };
      renderFilterModal(); // Оновлюємо чекбокси в модальному вікні
      updateSelectedFiltersDisplay();
      submitFilters();
    });
  }
})();
