(function () {
  const isMonthlyPage = window.isMonthlyReportPage === true;
  const container = document.getElementById('report-container');
  const monthlyContainer = document.getElementById('monthly-report-body');
  if (!container && !monthlyContainer) {
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
  let selectedEmployees = new Set();
  
  // Export selectedFilters and selectedEmployees to window for monthly report page
  window.selectedFilters = selectedFilters;
  window.selectedEmployees = selectedEmployees;

  let hideArchived = true;
  const archiveFilterSwitch = document.getElementById('archive-filter-switch');
  const modalArchiveSwitch = document.getElementById('modal-archive-switch');

  function applyArchiveParam(params) {
    if (!params || typeof params.set !== 'function') {
      return;
    }
    params.set('include_archived', hideArchived ? '0' : '1');
  }

  window.getIncludeArchivedParam = () => (hideArchived ? '0' : '1');

  window.addEventListener('monthly-filter-options', (event) => {
    const options = event.detail || {};
    currentFilterOptions = {
      projects: options.projects || [],
      departments: options.departments || [],
      units: options.units || [],
      teams: options.teams || []
    };
    renderFilterModal();
    updateSelectedFiltersDisplay();
  });
  
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
  
  // Week navigation
  let currentWeekOffset = 0;
  const prevWeekBtn = document.getElementById('prev-week-btn');
  const currentWeekBtn = document.getElementById('current-week-btn');
  const nextWeekBtn = document.getElementById('next-week-btn');
  const weekDisplay = document.getElementById('week-display');

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
    const dateFrom = dateFromInput ? dateFromInput.value : '';
    const dateTo = dateToInput ? dateToInput.value : '';
    const user = userInput ? userInput.value : '';
    const params = buildFilterParams(dateFrom, dateTo, user, selectedFilters, selectedEmployees);
    applyArchiveParam(params);
    
    // Add week_offset if no date filters are set and we're navigating weeks
    if (!dateFrom && !dateTo && currentWeekOffset !== 0) {
      params.set('week_offset', currentWeekOffset);
    }
    
    return params;
  }
  
  function getWeekDates(offset) {
    const today = new Date();
    const weekday = today.getDay(); // 0=Sun
    const diffToMonday = weekday === 0 ? -6 : 1 - weekday;
    const monday = new Date(today);
    monday.setDate(today.getDate() + diffToMonday + (offset * 7));
    const friday = new Date(monday);
    friday.setDate(monday.getDate() + 4);
    return { monday, friday };
  }
  
  function updateWeekDisplay() {
    if (!weekDisplay) return;
    
    if (currentWeekOffset === 0) {
      weekDisplay.textContent = '';
    } else {
      const { monday, friday } = getWeekDates(currentWeekOffset);
      const formatDate = (d) => `${d.getDate().toString().padStart(2, '0')}.${(d.getMonth() + 1).toString().padStart(2, '0')}.${d.getFullYear()}`;
      weekDisplay.textContent = `${formatDate(monday)} - ${formatDate(friday)}`;
    }
  }
  
  function navigateWeek(offset) {
    currentWeekOffset = offset;
    // Clear date filters when navigating by weeks
    if (dateFromInput) dateFromInput.value = '';
    if (dateToInput) dateToInput.value = '';
    updateWeekDisplay();
    loadData();
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
    applyArchiveParam(params);
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

  function calculateWeekStart(rows) {
    if (!rows || !rows.length) {
      return null;
    }
    const rawDate = rows[0].date_iso || rows[0].date || rows[0].date_display;
    if (!rawDate) {
      return null;
    }
    const dateObj = new Date(rawDate);
    if (Number.isNaN(dateObj.getTime())) {
      return null;
    }
    const day = dateObj.getDay();
    const monday = new Date(dateObj);
    monday.setDate(dateObj.getDate() - (day === 0 ? 6 : day - 1));
    return formatISO(monday);
  }

  function openWeekNotesModal(userKey, userName, currentNotes, weekStart) {
    if (!weekNotesModal || !weekNotesForm) {
      return;
    }
    weekNotesContext = {
      userKey: userKey,
      userName: userName || userKey,
      weekStart: weekStart || null
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
      userRecordsMap.set(userKeyRaw, {
        rows: item.rows || [],
        name: item.user_name,
        week_total: item.week_total,
        week_start: calculateWeekStart(item.rows || [])
      });
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

      // Wrapper for horizontal scroll on mobile
      const tableResponsive = document.createElement('div');
      tableResponsive.className = 'table-responsive';
      
      const table = document.createElement('table');
      table.className = 'table table-sm table-bordered report-table';
      const thead = document.createElement('thead');
      const headRow = document.createElement('tr');
      const headLabels = ['Date', 'Fact Start', 'Non Productive', 'Not Categorized', 'Productive', 'Total', 'Total cor', 'Notes', 'PF Status'];
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
        tr.appendChild(createCell(row.pf_status || ''));
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
        totalRow.appendChild(createCell('')); // PF Status пустий для Week total
        tbody.appendChild(totalRow);
      }

      table.appendChild(tbody);
      tableResponsive.appendChild(table);
      reportWrapper.appendChild(tableResponsive);
      container.appendChild(card);
    });
  }

  async function loadData() {
    if (!container && !monthlyContainer) {
      return;
    }
    if (isMonthlyPage) {
      // On monthly page, don't call loadData - monthly_report.js handles it
      return;
    }
    const params = buildParams();
    try {
      const response = await fetch(`/api/attendance?${params.toString()}`);
      if (!response.ok) {
        throw new Error('Не удалось получить данные');
      }
      const payload = await response.json();

      // Оновлюємо опції фільтрів навіть для сторінки місячного звіту
      const filterMeta = payload.filters || {};
      const filterOptions = filterMeta.options || {};
      currentFilterOptions = {
        projects: filterOptions.projects || [],
        departments: filterOptions.departments || [],
        units: filterOptions.units || [],
        teams: filterOptions.teams || []
      };
      updateSelectedFiltersDisplay();
      renderFilterModal();

      if (container) {
        renderReport(payload);
      } else if (monthlyContainer) {
        window.dispatchEvent(new CustomEvent('report-data-loaded', { detail: payload }));
      }
    } catch (error) {
      console.error(error);
      if (container) {
        container.innerHTML = '<div class="alert alert-danger">Не удалось загрузить данные.</div>';
      }
    }
  }

  function submitFilters(event) {
    if (event) {
      event.preventDefault();
    }
    loadData();
  }

  function notifyFiltersUpdated() {
    if (isMonthlyPage) {
      window.dispatchEvent(new CustomEvent('monthly-filters-updated'));
    } else {
      loadData();
    }
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

  if (form && !isMonthlyPage) {
    form.addEventListener('submit', submitFilters);
  }

  if (searchBtn && !isMonthlyPage) {
    searchBtn.addEventListener('click', submitFilters);
  }

  if (applySecondaryBtn && !isMonthlyPage) {
    applySecondaryBtn.addEventListener('click', submitFilters);
  }

  function handleReset(event) {
    event.preventDefault();
    resetFilters();
    loadData();
  }

  if (resetBtn && !isMonthlyPage) {
    resetBtn.addEventListener('click', handleReset);
  }
  
  // Week navigation event listeners
  if (prevWeekBtn && !isMonthlyPage) {
    prevWeekBtn.addEventListener('click', () => navigateWeek(currentWeekOffset - 1));
  }
  
  if (currentWeekBtn && !isMonthlyPage) {
    currentWeekBtn.addEventListener('click', () => navigateWeek(0));
  }
  
  if (nextWeekBtn && !isMonthlyPage) {
    nextWeekBtn.addEventListener('click', () => navigateWeek(currentWeekOffset + 1));
  }

  if (resetSecondaryBtn && !isMonthlyPage) {
    resetSecondaryBtn.addEventListener('click', handleReset);
  }

  if (reportBtn && reportModal) {
    reportBtn.addEventListener('click', () => {
      reportModal.show();
    });

    reportModalEl.addEventListener('click', (event) => {
      const target = event.target.closest('[data-report-format]');
      if (target) {
        const format = target.getAttribute('data-report-format');
        const params = buildParams();
        const url = format === 'pdf'
          ? `/api/report/pdf?${params.toString()}`
          : `/api/export?${params.toString()}`;
        window.open(url, '_blank');
        reportModal.hide();
        return;
      }
      
      // Handle monthly report button
      const monthlyBtn = event.target.closest('#monthly-report-btn');
      if (monthlyBtn) {
        window.location.href = '/monthly-report';
        reportModal.hide();
      }
    });
  }

  if (canEdit && container) {
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
      openWeekNotesModal(userKey, info.name, info.week_total?.notes || '', info.week_start);
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
    notifyFiltersUpdated();
  });

  // Не підставляємо дати за замовчуванням - backend покаже останні 5 робочих днів
  // Only load data on dashboard page, not on monthly report page
  if (!isMonthlyPage) {
    loadData();
  }

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
      // Get week_start from the first date in the data
      const dateFrom = dateFromInput ? dateFromInput.value : '';
      let weekStart = weekNotesContext.weekStart || dateFrom;
      
      // If no date specified, calculate Monday of current week
      if (!weekStart) {
        const today = new Date();
        const dayOfWeek = today.getDay();
        const monday = new Date(today);
        monday.setDate(today.getDate() - (dayOfWeek === 0 ? 6 : dayOfWeek - 1));
        weekStart = weekNotesContext.weekStart || formatISO(monday);
      }
      
      const response = await fetch('/api/week-notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          user_key: userKey, 
          week_start: weekStart,
          notes: notes 
        })
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.error || 'Failed to save week notes');
      }
      
      // Close modal first before reload
      if (weekNotesModal) {
        weekNotesModal.hide();
      }
      
      // Reload data to show updated notes
      await loadData();
      
    } catch (error) {
      console.error('Error saving week notes:', error);
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
      renderFilterModal();
      
      // Initialize modal if not already done
      if (!filtersModal && filtersModalEl) {
        filtersModal = new bootstrap.Modal(filtersModalEl);
      }
      
      if (filtersModal) {
        filtersModal.show();
      } else {
        console.error('ERROR: Could not initialize modal');
        alert('Ошибка: не удалось открыть модальное окно');
      }
    });
  }

  if (filterModalApplyBtn) {
    filterModalApplyBtn.addEventListener('click', () => {
      updateSelectedFiltersDisplay();
      notifyFiltersUpdated();
    });
  }

  if (filterModalClearBtn) {
    filterModalClearBtn.addEventListener('click', () => {
      selectedFilters = { projects: new Set(), departments: new Set(), units: new Set(), teams: new Set() };
      window.selectedFilters = selectedFilters;
      renderFilterModal();
      updateSelectedFiltersDisplay();
      // Don't call notifyFiltersUpdated here - wait for Apply button
    });
  }

  if (document.getElementById('clear-project-filters')) {
    document.getElementById('clear-project-filters').addEventListener('click', () => {
      // Очищаємо всі фільтри (проєкти, департаменти, юніти, команди)
      selectedFilters = { projects: new Set(), departments: new Set(), units: new Set(), teams: new Set() };
      window.selectedFilters = selectedFilters;
      
      // Очищаємо вибраних співробітників
      selectedEmployees.clear();
      
      // Очищаємо поле пошуку користувача
      if (userInput) userInput.value = '';
      
      // Оновлюємо UI
      renderFilterModal(); // Оновлюємо чекбокси в модальному вікні фільтрів
      updateSelectedFiltersDisplay();
      
      // Завантажуємо дані без фільтрів (але зі збереженням дат)
      notifyFiltersUpdated();
    });
  }

  // Multi-select employees modal
  const multiSelectModalEl = document.getElementById('multiSelectModal');
  const multiSelectModal = multiSelectModalEl ? new bootstrap.Modal(multiSelectModalEl) : null;
  const openMultiSelectBtn = document.getElementById('open-multi-select-modal');
  const multiSelectSearch = document.getElementById('multi-select-search');
  const multiSelectList = document.getElementById('multi-select-list');
  const selectAllBtn = document.getElementById('select-all-employees');
  const deselectAllBtn = document.getElementById('deselect-all-employees');
  const applyMultiSelectBtn = document.getElementById('apply-multi-select');
  const selectedCountBadge = document.getElementById('selected-count');
  const presetBadgesContainer = document.getElementById('preset-badges');
  const showSavePresetBtn = document.getElementById('show-save-preset');
  const savePresetForm = document.getElementById('save-preset-form');
  const presetNameInput = document.getElementById('preset-name-input');
  const confirmSavePresetBtn = document.getElementById('confirm-save-preset');
  const cancelSavePresetBtn = document.getElementById('cancel-save-preset');
  const presetError = document.getElementById('preset-error');
  const canManagePresets = multiSelectModalEl?.dataset.canManagePresets === '1';
  const canDeleteAnyPresets = multiSelectModalEl?.dataset.canDeleteAllPresets === '1';

  let allEmployees = [];
  let employeePresets = [];

  async function loadAllEmployees() {
    try {
      const params = new URLSearchParams();
      applyArchiveParam(params);
      
      // Load employees from last 30 days to ensure we get the list
      // даже если в текущем периоде нет данных
      const today = new Date();
      const lastMonth = new Date(today);
      lastMonth.setDate(today.getDate() - 30);
      params.set('date_from', lastMonth.toISOString().slice(0, 10));
      params.set('date_to', today.toISOString().slice(0, 10));
      
      // Use different endpoint for monthly page
      let endpoint = '/api/attendance';
      if (isMonthlyPage) {
        const filterMonth = document.getElementById('filter-month');
        const month = filterMonth ? filterMonth.value : new Date().toISOString().slice(0, 7);
        endpoint = '/api/monthly-report';
        params.set('month', month);
      }
      
      const response = await fetch(`${endpoint}?${params.toString()}`);
      const data = await response.json();
      
      // Перевіряємо що дані прийшли правильно
      const items = data.items || data.employees || [];
      if (!items || items.length === 0) {
        console.error('No employees found:', data);
        alert('Ошибка: не найдены сотрудники за последний месяц');
        return;
      }
      
      // Создаем уникальный список сотрудников
      const employeesMap = new Map();
      items.forEach(item => {
        const key = item.user_email || item.user_key || item.user_id || item.user_name;
        if (!employeesMap.has(key)) {
          employeesMap.set(key, {
            key: key,
            name: item.user_name || '',
            email: item.user_email || '',
            user_id: item.user_id || '',
            project: item.division || item.project || '',
            department: item.department || '',
            team: item.team || ''
          });
        }
      });
      
      allEmployees = Array.from(employeesMap.values()).sort((a, b) => 
        (a.name || a.email).localeCompare(b.name || b.email)
      );
      
      renderEmployeeList();
    } catch (error) {
      console.error('Failed to load employees:', error);
      alert('Ошибка загрузки списка сотрудников');
    }
  }

  function renderEmployeeList(searchQuery = '') {
    if (!multiSelectList) return;
    
    const query = searchQuery.toLowerCase();
    const filteredEmployees = allEmployees.filter(emp => {
      const searchStr = `${emp.name} ${emp.email} ${emp.project} ${emp.department}`.toLowerCase();
      return searchStr.includes(query);
    });
    
    const html = filteredEmployees.map(emp => {
      const isSelected = selectedEmployees.has(emp.key);
      const displayName = emp.name || emp.email || emp.user_id;
      const subtitle = emp.email && emp.name ? emp.email : '';
      const badge = emp.project ? `<span class="badge bg-secondary ms-2">${escapeHtml(emp.project)}</span>` : '';
      
      return `
        <label class="list-group-item list-group-item-action d-flex align-items-center" style="cursor: pointer;">
          <input 
            type="checkbox" 
            class="form-check-input me-3" 
            data-employee-key="${escapeHtml(emp.key)}"
            ${isSelected ? 'checked' : ''}
          >
          <div class="flex-grow-1">
            <div class="fw-semibold">${escapeHtml(displayName)}${badge}</div>
            ${subtitle ? `<small class="text-muted">${escapeHtml(subtitle)}</small>` : ''}
          </div>
        </label>
      `;
    }).join('');
    
    multiSelectList.innerHTML = html || '<div class="text-center text-muted py-3">Нет результатов</div>';
    updateSelectedCount();
  }

  function updateSelectedCount() {
    if (selectedCountBadge) {
      selectedCountBadge.textContent = `Выбрано: ${selectedEmployees.size}`;
    }
  }

  async function fetchEmployeePresets() {
    if (!canManagePresets) {
      return;
    }
    try {
      const response = await fetch('/api/presets');
      if (!response.ok) {
        throw new Error('Failed to load presets');
      }
      const data = await response.json();
      employeePresets = data.presets || [];
      renderPresetBadges();
    } catch (error) {
      console.error('Failed to load presets:', error);
    }
  }

  function renderPresetBadges() {
    if (!presetBadgesContainer) return;
    if (!employeePresets.length) {
      presetBadgesContainer.innerHTML =
        '<span class="text-muted small">Немає пресетів</span>';
      return;
    }
    const badges = employeePresets
      .map((preset) => {
        const canRemove = preset.is_owner || canDeleteAnyPresets;
        return `
          <span class="badge bg-secondary text-white d-inline-flex align-items-center gap-1 preset-badge" data-preset-id="${preset.id}">
            <span>${escapeHtml(preset.name)}</span>
            ${
              canRemove
                ? `<button type="button" class="btn-close btn-close-white btn-sm ms-1" data-delete-preset-id="${preset.id}" aria-label="Удалить пресет"></button>`
                : ''
            }
          </span>
        `;
      })
      .join('');
    presetBadgesContainer.innerHTML = badges;
  }

  function applyPreset(presetId) {
    const preset = employeePresets.find((item) => item.id === presetId);
    if (!preset) {
      return;
    }
    selectedEmployees.clear();
    (preset.employee_keys || []).forEach((key) => selectedEmployees.add(key));
    renderEmployeeList(multiSelectSearch?.value || '');
    updateSelectedCount();
  }

  function togglePresetForm(show) {
    if (!savePresetForm) return;
    if (show) {
      savePresetForm.classList.remove('d-none');
      presetNameInput?.focus();
    } else {
      savePresetForm.classList.add('d-none');
      if (presetNameInput) {
        presetNameInput.value = '';
      }
    }
    setPresetError('');
  }

  function setPresetError(message) {
    if (!presetError) return;
    if (message) {
      presetError.textContent = message;
      presetError.classList.remove('d-none');
    } else {
      presetError.textContent = '';
      presetError.classList.add('d-none');
    }
  }

  async function deletePreset(presetId) {
    try {
      const response = await fetch(`/api/presets/${presetId}`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw new Error('Failed to delete preset');
      }
      employeePresets = employeePresets.filter(
        (preset) => preset.id !== presetId
      );
      renderPresetBadges();
    } catch (error) {
      console.error('Failed to delete preset:', error);
      alert('Не удалось удалить пресет');
    }
  }

  if (openMultiSelectBtn) {
    openMultiSelectBtn.addEventListener('click', async () => {
      if (allEmployees.length === 0) {
        await loadAllEmployees();
      }
      renderEmployeeList();
      if (canManagePresets) {
        await fetchEmployeePresets();
      }
      multiSelectModal?.show();
    });
  }

  if (multiSelectSearch) {
    multiSelectSearch.addEventListener('input', (e) => {
      renderEmployeeList(e.target.value);
    });
  }

  if (multiSelectList) {
    multiSelectList.addEventListener('change', (e) => {
      if (e.target.type === 'checkbox') {
        const key = e.target.dataset.employeeKey;
        if (e.target.checked) {
          selectedEmployees.add(key);
        } else {
          selectedEmployees.delete(key);
        }
        updateSelectedCount();
      }
    });
  }

  if (selectAllBtn) {
    selectAllBtn.addEventListener('click', () => {
      const query = multiSelectSearch?.value || '';
      const filtered = allEmployees.filter(emp => {
        const searchStr = `${emp.name} ${emp.email} ${emp.project} ${emp.department}`.toLowerCase();
        return searchStr.includes(query.toLowerCase());
      });
      filtered.forEach(emp => selectedEmployees.add(emp.key));
      renderEmployeeList(query);
    });
  }

  if (deselectAllBtn) {
    deselectAllBtn.addEventListener('click', () => {
      selectedEmployees.clear();
      renderEmployeeList(multiSelectSearch?.value || '');
    });
  }

  if (applyMultiSelectBtn) {
    applyMultiSelectBtn.addEventListener('click', async () => {
      if (selectedEmployees.size === 0) {
        alert('Выберите хотя бы одного сотрудника');
        return;
      }
      
      multiSelectModal?.hide();
      if (isMonthlyPage) {
        window.dispatchEvent(new CustomEvent('monthly-filters-updated'));
        return;
      }
      
      // Формуємо запит для вибраних співробітників
      const params = new URLSearchParams();
      applyArchiveParam(params);
      if (dateFromInput.value) params.set('date_from', dateFromInput.value);
      if (dateToInput.value) params.set('date_to', dateToInput.value);
      
      // Додаємо фільтри по вибраних користувачах
      selectedEmployees.forEach(key => {
        params.append('user_key', key);
      });
      
      try {
        const response = await fetch(`/api/attendance?${params.toString()}`);
        const data = await response.json();
        if (data && data.items) {
          renderReport(data);
        }
      } catch (error) {
        console.error('Failed to load data for selected employees:', error);
        alert('Ошибка загрузки данных');
      }
    });
  }

  if (showSavePresetBtn) {
    showSavePresetBtn.addEventListener('click', () => {
      if (selectedEmployees.size === 0) {
        setPresetError('Спочатку виберіть співробітників');
        return;
      }
      togglePresetForm(true);
    });
  }

  if (cancelSavePresetBtn) {
    cancelSavePresetBtn.addEventListener('click', () => {
      togglePresetForm(false);
    });
  }

  if (confirmSavePresetBtn) {
    confirmSavePresetBtn.addEventListener('click', async () => {
      if (!canManagePresets) return;
      const name = (presetNameInput?.value || '').trim();
      if (!name) {
        setPresetError('Вкажіть назву пресету');
        return;
      }
      if (selectedEmployees.size === 0) {
        setPresetError('Спочатку виберіть співробітників');
        return;
      }
      setPresetError('');
      confirmSavePresetBtn.disabled = true;
      try {
        const response = await fetch('/api/presets', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            name,
            employee_keys: Array.from(selectedEmployees),
          }),
        });
        const data = await response.json();
        if (!response.ok) {
          setPresetError(data.error || 'Не вдалося зберегти пресет');
          return;
        }
        employeePresets = [data, ...employeePresets];
        renderPresetBadges();
        togglePresetForm(false);
      } catch (error) {
        console.error('Failed to save preset:', error);
        setPresetError('Не вдалося зберегти пресет');
      } finally {
        confirmSavePresetBtn.disabled = false;
      }
    });
  }

  if (presetBadgesContainer) {
    presetBadgesContainer.addEventListener('click', async (event) => {
      const deleteBtn = event.target.closest('[data-delete-preset-id]');
      if (deleteBtn) {
        event.stopPropagation();
        const presetId = Number(deleteBtn.dataset.deletePresetId);
        if (Number.isNaN(presetId)) return;
        if (confirm('Видалити пресет?')) {
          await deletePreset(presetId);
        }
        return;
      }
      const badge = event.target.closest('[data-preset-id]');
      if (!badge) return;
      const presetId = Number(badge.dataset.presetId);
      if (Number.isNaN(presetId)) return;
      applyPreset(presetId);
    });
  }

  function handleArchiveToggle(value, sourceElement) {
    const normalized = Boolean(value);
    if (hideArchived === normalized) {
      if (sourceElement && sourceElement.checked !== hideArchived) {
        sourceElement.checked = hideArchived;
      }
      return;
    }
    hideArchived = normalized;
    if (archiveFilterSwitch && archiveFilterSwitch !== sourceElement) {
      archiveFilterSwitch.checked = hideArchived;
    }
    if (modalArchiveSwitch && modalArchiveSwitch !== sourceElement) {
      modalArchiveSwitch.checked = hideArchived;
    }
    allEmployees = [];
    notifyFiltersUpdated();
    if (multiSelectModalEl && multiSelectModalEl.classList.contains('show')) {
      loadAllEmployees();
    }
  }

  if (archiveFilterSwitch) {
    archiveFilterSwitch.checked = hideArchived;
    archiveFilterSwitch.addEventListener('change', () => handleArchiveToggle(archiveFilterSwitch.checked, archiveFilterSwitch));
  }
  if (modalArchiveSwitch) {
    modalArchiveSwitch.checked = hideArchived;
    modalArchiveSwitch.addEventListener('change', () => handleArchiveToggle(modalArchiveSwitch.checked, modalArchiveSwitch));
  }
  
  // Initialize week display on page load
  if (!isMonthlyPage) {
    updateWeekDisplay();
  }

})();
