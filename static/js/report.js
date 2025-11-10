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
  const recordEditModalEl = document.getElementById('recordEditModal');
  const recordEditModal = recordEditModalEl ? new bootstrap.Modal(recordEditModalEl) : null;
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
    const params = new URLSearchParams();
    if (dateFromInput.value) {
      params.set('date_from', dateFromInput.value);
    }
    if (dateToInput.value) {
      params.set('date_to', dateToInput.value);
    }
    if (userInput.value) {
      params.set('user', userInput.value);
    }
    if (projectSelect.value) {
      params.set('project', projectSelect.value);
    }
    if (departmentSelect.value) {
      params.set('department', departmentSelect.value);
    }
    if (teamSelect.value) {
      params.set('team', teamSelect.value);
    }
    return params;
  }

  function createCell(text, className) {
    const td = document.createElement('td');
    td.textContent = text || '';
    if (className) {
      td.className = className;
    }
    return td;
  }

  function createNotesCell(row) {
    const td = document.createElement('td');
    td.className = 'notes-cell';
    const display = document.createElement('div');
    display.className = 'notes-display';
    display.textContent = row.notes_display || '';
    td.appendChild(display);

    if (row.leave_reason && row.notes) {
      const leaveInfo = document.createElement('div');
      leaveInfo.className = 'text-muted small';
      leaveInfo.textContent = row.leave_reason;
      td.appendChild(leaveInfo);
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

  function renderReport(data) {
    container.innerHTML = '';

    const filterMeta = data.filters || {};
    const filterOptions = filterMeta.options || {};
    const resolvedFilters = filterMeta.selected || {};

    populateSelect(projectSelect, filterOptions.projects || [], 'Все проекты');
    populateSelect(departmentSelect, filterOptions.departments || [], 'Все департаменты');
    populateSelect(teamSelect, filterOptions.teams || [], 'Все команды');

    if (resolvedFilters.project) {
      setSelectValue(projectSelect, resolvedFilters.project);
    } else if (!Array.from(projectSelect.options).some((option) => option.value === projectSelect.value)) {
      projectSelect.value = '';
    }

    if (resolvedFilters.department) {
      setSelectValue(departmentSelect, resolvedFilters.department);
    } else if (!Array.from(departmentSelect.options).some((option) => option.value === departmentSelect.value)) {
      departmentSelect.value = '';
    }

    if (resolvedFilters.team) {
      setSelectValue(teamSelect, resolvedFilters.team);
    } else if (!Array.from(teamSelect.options).some((option) => option.value === teamSelect.value)) {
      teamSelect.value = '';
    }

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
        tr.appendChild(createCell(row.total_display));
        tr.appendChild(createCell(row.corrected_total_display || ''));
        tr.appendChild(createNotesCell(row));
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
        const notesCell = document.createElement('td');
        notesCell.className = 'notes-cell';
        if (canEdit) {
          const editBtn = document.createElement('button');
          editBtn.type = 'button';
          editBtn.className = 'btn btn-link p-0 week-edit-btn';
          editBtn.dataset.weekEdit = userKeyRaw;
          editBtn.textContent = 'Редактировать';
          notesCell.appendChild(editBtn);
        }
        totalRow.appendChild(notesCell);
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
  }

  document.addEventListener('click', function (event) {
    const link = event.target.closest('.meta-link');
    if (!link) {
      return;
    }
    event.preventDefault();
    const type = link.dataset.filter;
    const value = decodeURIComponent(link.dataset.value || '');
    if (type === 'project') {
      setSelectValue(projectSelect, value);
    } else if (type === 'department') {
      setSelectValue(departmentSelect, value);
    } else if (type === 'team') {
      setSelectValue(teamSelect, value);
    }
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
})();
