(() => {
  const body = document.body;
  const userKey = body.dataset.userKey;
  if (!userKey) {
    return;
  }

  const alertContainer = document.getElementById('alert-container');
  const profileNameEl = document.getElementById('profile-name');
  const profileMetaEl = document.getElementById('profile-meta');
  const profileIdentifierEl = document.getElementById('profile-identifier');
  const profileEmailEl = document.getElementById('profile-email');
  const profileLocationEl = document.getElementById('profile-location');
  const profilePlanStartEl = document.getElementById('profile-plan-start');
  const profileManagerValue = document.getElementById('profile-manager-value');
  const profilePeopleforceEl = document.getElementById('profile-peopleforce');
  const profileYawareEl = document.getElementById('profile-yaware');
  const managerEditBtn = document.getElementById('manager-edit-btn');
  const recordsBody = document.getElementById('records-body');
  const recordsCountEl = document.getElementById('records-count');
  const latenessContainer = document.getElementById('lateness-grid');
  const recordModalEl = document.getElementById('recordModal');
  const recordForm = document.getElementById('record-form');
  const managerModalEl = document.getElementById('managerModal');
  const managerModalForm = document.getElementById('manager-modal-form');
  const managerModalSelect = document.getElementById('manager-modal-select');
  const dateFromInput = document.getElementById('range-date-from');
  const dateToInput = document.getElementById('range-date-to');
  const rangeApplyBtn = document.getElementById('range-apply');
  const rangeResetBtn = document.getElementById('range-reset');
  const reportBtn = document.getElementById('report-btn');
  const reportModalEl = document.getElementById('reportModal');

  const formScheduledStart = document.getElementById('form-scheduled-start');
  const formActualStart = document.getElementById('form-actual-start');
  const formStatus = document.getElementById('form-status');
  const formMinutesLate = document.getElementById('form-minutes-late');
  const formNonProductive = document.getElementById('form-non-productive');
  const formNotCategorized = document.getElementById('form-not-categorized');
  const formProductive = document.getElementById('form-productive');
  const formTotal = document.getElementById('form-total');
  const formTotalCorrected = document.getElementById('form-total-corrected');
  const formNotes = document.getElementById('form-notes');
  const formLeaveReason = document.getElementById('form-leave-reason');
  const formRecordId = document.getElementById('record-id');

  const recordModal = recordModalEl ? new bootstrap.Modal(recordModalEl) : null;
  const managerModal = managerModalEl ? new bootstrap.Modal(managerModalEl) : null;
  const reportModal = reportModalEl ? new bootstrap.Modal(reportModalEl) : null;
  let currentStatusOptions = [];
  let managerOptions = [];
  let managerCurrentValue = '';
  let managerEditBound = false;
  let currentProfile = {};

  function showAlert(message, type = 'danger', timeout = 5000) {
    if (!alertContainer) {
      return;
    }
    const wrapper = document.createElement('div');
    wrapper.className = `alert alert-${type} alert-dismissible fade show`;
    wrapper.role = 'alert';
    wrapper.innerHTML = `
      ${message}
      <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    alertContainer.appendChild(wrapper);
    if (timeout > 0) {
      setTimeout(() => {
        const alert = bootstrap.Alert.getOrCreateInstance(wrapper);
        alert.close();
      }, timeout);
    }
  }

  function joinNonEmpty(values, separator = ' / ') {
    return values.filter((value) => value && value.trim()).join(separator) || '—';
  }

  function renderProfile(data, schedule) {
    if (!data) {
      return;
    }
    profileNameEl.textContent = data.name || schedule?.name || 'Неизвестный пользователь';
    profileMetaEl.textContent = joinNonEmpty([data.project, data.department, data.team], ' • ');
    profileIdentifierEl.textContent = data.user_id ? `YaWare ID: ${data.user_id}` : '';
    if (profileEmailEl) {
      profileEmailEl.textContent = data.email || '—';
    }
    if (profileLocationEl) {
      profileLocationEl.textContent = data.location || '—';
    }
    if (profilePlanStartEl) {
      profilePlanStartEl.textContent = data.plan_start || '—';
    }
    if (profilePeopleforceEl) {
      const pfId = schedule?.peopleforce_id;
      if (pfId) {
        profilePeopleforceEl.innerHTML = `<a href="https://evrius.peopleforce.io/employees/${pfId}" target="_blank" rel="noopener noreferrer" class="no-print">${pfId}</a>`;
      } else {
        profilePeopleforceEl.textContent = '—';
      }
    }
    if (profileYawareEl) {
      const yawareId = data.user_id;
      if (yawareId) {
        profileYawareEl.innerHTML = `<a href="https://app.yaware.com/reports/by-user/index/user/${yawareId}" target="_blank" rel="noopener noreferrer" class="no-print">${yawareId}</a>`;
      } else {
        profileYawareEl.textContent = '—';
      }
    }
    if (profileManagerValue) {
      profileManagerValue.textContent = (data.control_manager ?? '') === '' ? '—' : `#${data.control_manager}`;
    }
  }

  function configureManagerControl(options, currentValue, canChange) {
    managerOptions = options || [];
    managerCurrentValue = currentValue != null && currentValue !== '' ? String(currentValue) : '';
    if (profileManagerValue) {
      profileManagerValue.textContent = managerCurrentValue ? `#${managerCurrentValue}` : '—';
    }

    if (!managerEditBtn) {
      return;
    }

    if (canChange) {
      managerEditBtn.classList.remove('d-none');
      if (!managerEditBound) {
        managerEditBtn.addEventListener('click', openManagerModal);
        managerEditBound = true;
      }
    } else {
      managerEditBtn.classList.add('d-none');
    }
  }

  function createCell(text) {
    const td = document.createElement('td');
    td.textContent = text ?? '';
    return td;
  }

  function createNotesCell(record) {
    const td = document.createElement('td');
    const note = record.notes_display || record.notes || '';
    td.innerHTML = note ? `<span class="text-wrap">${note}</span>` : '<span class="text-muted">—</span>';
    if (record.leave_reason) {
      const info = document.createElement('div');
      info.className = 'small text-muted';
      info.textContent = record.leave_reason;
      td.appendChild(info);
    }
    return td;
  }

  function renderRecords(records, canEdit, statusOptions) {
    currentStatusOptions = statusOptions || [];
    recordsBody.innerHTML = '';
  recordsCountEl.textContent = `${records.length} записей`;

    if (!records.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 10;
      cell.className = 'text-center text-muted py-4';
      cell.textContent = 'Нет данных для отображения.';
      row.appendChild(cell);
      recordsBody.appendChild(row);
      return;
    }

    records.forEach((record) => {
      const row = document.createElement('tr');
      row.appendChild(createCell(`${record.date_display}`));
      row.appendChild(createCell(record.scheduled_start_hm || record.scheduled_start || '—'));
      row.appendChild(createCell(record.actual_start_hm || record.actual_start || '—'));
      row.appendChild(createCell(record.non_productive_display || '00:00'));
      row.appendChild(createCell(record.not_categorized_display || '00:00'));
      row.appendChild(createCell(record.productive_display || '00:00'));
      row.appendChild(createCell(record.total_display || '00:00'));
      row.appendChild(createCell(record.corrected_total_display || ''));
      row.appendChild(createNotesCell(record));

      const actions = document.createElement('td');
      actions.className = 'text-center';
      if (canEdit) {
        const btn = document.createElement('button');
        btn.className = 'btn btn-sm btn-outline-primary';
        btn.innerHTML = '<i class="bi bi-pencil"></i>';
        btn.addEventListener('click', () => openRecordModal(record));
        actions.appendChild(btn);
      }
      row.appendChild(actions);

      recordsBody.appendChild(row);
    });
  }

  function renderLateness(data) {
    if (!latenessContainer) {
      return;
    }

    latenessContainer.innerHTML = '';
    const labels = data?.labels || [];
    const values = data?.values || [];

    if (!labels.length) {
      const empty = document.createElement('span');
      empty.className = 'text-muted';
      empty.textContent = 'Нет опозданий за выбранный период.';
      latenessContainer.appendChild(empty);
      return;
    }

    const fragment = document.createDocumentFragment();

    const dayNames = {
      'ПН': 'Понедельник',
      'ВТ': 'Вторник',
      'СР': 'Среда',
      'ЧТ': 'Четверг',
      'ПТ': 'Пятница',
    };

    labels.forEach((label, index) => {
      const value = Number(values[index] || 0);
      const item = document.createElement('div');
      item.className = 'lateness-card';

      const dateLabel = document.createElement('div');
      dateLabel.className = 'lateness-date';
      const separatorIndex = typeof label === 'string' ? label.indexOf('.') : -1;
      if (separatorIndex > 0) {
        const abbr = label.slice(0, separatorIndex).trim();
        const datePart = label.slice(separatorIndex + 1).trim();
        const dayName = dayNames[abbr] || abbr;
        dateLabel.textContent = datePart ? `${dayName}, (${datePart})` : dayName;
      } else {
        dateLabel.textContent = label;
      }

      const valueLabel = document.createElement('div');
      valueLabel.className = 'lateness-time';
      const hours = Math.floor(value / 60);
      const minutes = value % 60;
      valueLabel.textContent = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;

      item.appendChild(dateLabel);
      item.appendChild(valueLabel);
      fragment.appendChild(item);
    });

    latenessContainer.appendChild(fragment);
  }

  function fillStatusOptions(currentStatus) {
    formStatus.innerHTML = '';
    const emptyOption = document.createElement('option');
    emptyOption.value = '';
    emptyOption.textContent = '—';
    formStatus.appendChild(emptyOption);
    currentStatusOptions.forEach((status) => {
      const option = document.createElement('option');
      option.value = status;
      option.textContent = STATUS_LABELS[status] || status;
      formStatus.appendChild(option);
    });
    formStatus.value = currentStatus || '';
    const hint = currentStatus ? STATUS_LABELS[currentStatus] : '';
    formStatus.setAttribute(
      'title',
      hint
        ? `${currentStatus}: ${hint}`
        : 'Статус дня: present — присутствовал, late — опоздал, absent — отсутствовал, leave — отпуск'
    );
  }

  function openRecordModal(record) {
    if (!recordModal) {
      return;
    }
    formRecordId.value = record.id;
    formScheduledStart.value = record.scheduled_start || '';
    formActualStart.value = record.actual_start || '';
    fillStatusOptions(record.status);
    formMinutesLate.value = record.minutes_late_display || ''; // модальное поле остается для редактирования
    formNonProductive.value = record.non_productive_display || '';
    formNotCategorized.value = record.not_categorized_display || '';
    formProductive.value = record.productive_display || '';
    formTotal.value = record.total_display || '';
    formTotalCorrected.value = record.corrected_total_display || '';
    formNotes.value = record.notes || '';
    formLeaveReason.value = record.leave_reason || '';
    recordModal.show();
  }

  function buildRangeParams() {
    const params = new URLSearchParams();
    if (dateFromInput && dateFromInput.value) {
      params.set('date_from', dateFromInput.value);
    }
    if (dateToInput && dateToInput.value) {
      params.set('date_to', dateToInput.value);
    }
    return params;
  }

  async function submitRecordForm(event) {
    event.preventDefault();
    const recordId = formRecordId.value;
    if (!recordId) {
      return;
    }
    const payload = {
      scheduled_start: formScheduledStart.value,
      actual_start: formActualStart.value,
      status: formStatus.value,
      minutes_late: formMinutesLate.value,
      non_productive_minutes: formNonProductive.value,
      not_categorized_minutes: formNotCategorized.value,
      productive_minutes: formProductive.value,
      total_minutes: formTotal.value,
      corrected_total_minutes: formTotalCorrected.value,
      notes: formNotes.value,
      leave_reason: formLeaveReason.value,
    };

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
      recordModal.hide();
      showAlert('Запись обновлена успешно', 'success', 3000);
      await loadData();
    } catch (error) {
      showAlert(error.message || 'Не удалось обновить запись');
    }
  }

  function openManagerModal() {
    if (!managerModal || !managerModalSelect) {
      return;
    }
    managerModalSelect.innerHTML = '<option value="">—</option>';
    managerOptions.forEach((value) => {
      const option = document.createElement('option');
      option.value = String(value);
      option.textContent = `Manager #${value}`;
      managerModalSelect.appendChild(option);
    });
    managerModalSelect.value = managerCurrentValue;
    managerModal.show();
  }

  async function submitManagerModalForm(event) {
    event.preventDefault();
    if (!managerModalSelect) {
      return;
    }
    const value = managerModalSelect.value;
    try {
      const response = await fetch(`/api/users/${encodeURIComponent(userKey)}/manager`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ control_manager: value }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Не удалось обновить менеджера');
      }
      if (managerModal) {
        managerModal.hide();
      }
      showAlert('Контроль-менеджера обновлен', 'success', 3000);
      await loadData();
    } catch (error) {
      showAlert(error.message || 'Не удалось обновить менеджера');
    }
  }

  async function loadData() {
    try {
      const rangeParams = buildRangeParams();
      const url = rangeParams.toString()
        ? `/api/users/${encodeURIComponent(userKey)}?${rangeParams.toString()}`
        : `/api/users/${encodeURIComponent(userKey)}`;
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error('Не удалось получить данные пользователя');
      }
      const payload = await response.json();
      currentProfile = payload.profile || {};
      renderProfile(currentProfile, payload.schedule || {});
      configureManagerControl(
        payload.manager_options || [],
        currentProfile.control_manager ?? null,
        Boolean(payload.permissions?.can_change_manager)
      );
      renderRecords(payload.recent_records || [], payload.permissions?.can_edit, payload.status_options || []);
      renderLateness(payload.lateness || {});
      if (payload.date_range) {
        if (dateFromInput) {
          dateFromInput.value = payload.date_range.date_from || '';
        }
        if (dateToInput) {
          dateToInput.value = payload.date_range.date_to || '';
        }
      }
    } catch (error) {
      recordsBody.innerHTML = '';
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 9;
      cell.className = 'text-center text-danger py-4';
      cell.textContent = error.message || 'Не удалось загрузить данные пользователя.';
      row.appendChild(cell);
      recordsBody.appendChild(row);
      showAlert(error.message || 'Не удалось загрузить данные пользователя.');
    }
  }

  if (recordForm) {
    recordForm.addEventListener('submit', submitRecordForm);
  }

  if (managerModalForm) {
    managerModalForm.addEventListener('submit', submitManagerModalForm);
  }

  if (rangeApplyBtn) {
    rangeApplyBtn.addEventListener('click', () => {
      loadData();
    });
  }

  if (rangeResetBtn) {
    rangeResetBtn.addEventListener('click', () => {
      if (dateFromInput) {
        dateFromInput.value = '';
      }
      if (dateToInput) {
        dateToInput.value = '';
      }
      loadData();
    });
  }

  if (reportBtn && reportModal && reportModalEl) {
    reportBtn.addEventListener('click', () => {
      reportModal.show();
    });

    reportModalEl.addEventListener('click', (event) => {
      const target = event.target.closest('[data-report-format]');
      if (!target) {
        return;
      }
      const format = target.getAttribute('data-report-format');
      const params = buildRangeParams();
      const filterValue = currentProfile.email || currentProfile.name || userKey;
      params.set('user', filterValue);
      const url = format === 'pdf'
        ? `/api/report/pdf?${params.toString()}`
        : `/api/export?${params.toString()}`;
      window.open(url, '_blank');
      reportModal.hide();
    });
  }

  loadData();
})();
