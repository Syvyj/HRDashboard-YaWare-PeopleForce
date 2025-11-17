(() => {
  const body = document.body;
  const userKey = body.dataset.userKey;
  if (!userKey) {
    return;
  }

  // Функція генерації telegram username з імені
  function generateTelegramUsername(fullName) {
    if (!fullName) return '';
    const parts = fullName.trim().split(/\s+/);
    if (parts.length < 2) return parts[0] || '';
    return `${parts[0]}_${parts[1]}`;
  }

  const alertContainer = document.getElementById('alert-container');
  const profileNameEl = document.getElementById('profile-name');
  const profileIdentifierEl = document.getElementById('profile-identifier');
  const profileEmailEl = document.getElementById('profile-email');
  const profilePlanStartEl = document.getElementById('profile-plan-start');
  const profileManagerValue = document.getElementById('profile-manager-value');
  const profilePeopleforceEl = document.getElementById('profile-peopleforce');
  const profileYawareEl = document.getElementById('profile-yaware');
  const profileTelegramEl = document.getElementById('profile-telegram');
  const profilePositionEl = document.getElementById('profile-position');
  const profileDivisionEl = document.getElementById('profile-division');
  const profileDirectionEl = document.getElementById('profile-direction');
  const profileUnitEl = document.getElementById('profile-unit');
  const profileTeamEl = document.getElementById('profile-team');
  const profileTeamLeadEl = document.getElementById('profile-team-lead');
  const profileLocationEl = document.getElementById('profile-location');
  const managerEditBtn = document.getElementById('manager-edit-btn');
  const recordsBody = document.getElementById('records-body');
  const recordsCountEl = document.getElementById('records-count');
  const latenessContainer = document.getElementById('lateness-grid');
  const recordModalEl = document.getElementById('recordModal');
  const recordForm = document.getElementById('record-form');
  const managerModalEl = document.getElementById('managerModal');
  const managerModalForm = document.getElementById('manager-modal-form');
  const managerModalSelect = document.getElementById('manager-modal-select');
  const telegramModalInput = document.getElementById('telegram-modal-input');
  const telegramEditGroup = document.getElementById('telegram-edit-group');
  const planStartModalEl = document.getElementById('planStartModal');
  const planStartModalForm = document.getElementById('plan-start-modal-form');
  const planStartModalInput = document.getElementById('plan-start-modal-input');
  const planStartEditBtn = document.getElementById('plan-start-edit-btn');
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
  const planStartModal = planStartModalEl ? new bootstrap.Modal(planStartModalEl) : null;
  const reportModal = reportModalEl ? new bootstrap.Modal(reportModalEl) : null;
  let currentStatusOptions = [];
  let managerOptions = [];
  let managerCurrentValue = '';
  let managerEditBound = false;
  let planStartEditBound = false;
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
    // Відображаємо локацію в правому верхньому куті
    console.log('Schedule object:', schedule);
    const location = schedule?.location || data.location || '—';
    console.log('Location value:', location);
    profileIdentifierEl.textContent = `Локация: ${location}`;
    if (profileEmailEl) {
      profileEmailEl.textContent = data.email || '—';
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
    if (profileTelegramEl) {
      const telegramUsername = data.telegram_username || generateTelegramUsername(data.name);
      if (telegramUsername) {
        // Видаляємо @ якщо є на початку
        const cleanTelegram = telegramUsername.replace(/^@/, '');
        profileTelegramEl.innerHTML = `<a href="https://t.me/${cleanTelegram}" target="_blank" rel="noopener noreferrer">@${cleanTelegram}</a>`;
      } else {
        profileTelegramEl.textContent = '—';
      }
    }
    
    // Відображаємо нові поля ієрархії
    if (profilePositionEl) {
      profilePositionEl.textContent = schedule?.position || '—';
    }
    if (profileDivisionEl) {
      profileDivisionEl.textContent = schedule?.division_name || '—';
    }
    if (profileLocationEl) {
      profileLocationEl.textContent = schedule?.location || data.location || '—';
    }
    if (profileDirectionEl) {
      profileDirectionEl.textContent = schedule?.direction_name || '—';
    }
    if (profileUnitEl) {
      profileUnitEl.textContent = schedule?.unit_name || '—';
    }
    if (profileTeamEl) {
      profileTeamEl.textContent = schedule?.team_name || '—';
    }
    
    // Відображаємо team_lead - тільки телеграм лінк
    if (profileTeamLeadEl) {
      const teamLeadTelegram = schedule?.manager_telegram;
      
      if (teamLeadTelegram) {
        const cleanTelegram = teamLeadTelegram.replace(/^@/, '');
        profileTeamLeadEl.innerHTML = `<a href="https://t.me/${cleanTelegram}" target="_blank" rel="noopener noreferrer">@${cleanTelegram}</a>`;
      } else {
        profileTeamLeadEl.textContent = '—';
      }
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

  function configurePlanStartControl(canChange) {
    if (!planStartEditBtn) {
      return;
    }

    if (canChange) {
      planStartEditBtn.classList.remove('d-none');
      if (!planStartEditBound) {
        planStartEditBtn.addEventListener('click', openPlanStartModal);
        planStartEditBound = true;
      }
    } else {
      planStartEditBtn.classList.add('d-none');
    }
  }

  function createCell(text) {
    const td = document.createElement('td');
    td.textContent = text ?? '';
    return td;
  }

  function createTotalCell(record) {
    const td = document.createElement('td');
    td.textContent = record.total_display || '00:00';
    
    // Перевіряємо чи треба підсвітити червоним
    const divisionName = (record.division_name || '').toLowerCase();
    const totalMinutes = record.total_minutes || 0;
    
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

  function createNotesCell(record) {
    const td = document.createElement('td');
    td.style.textAlign = 'left';
    const note = record.notes_display || record.notes || '';
    td.innerHTML = note ? `<span class="text-wrap">${note}</span>` : '<span class="text-muted">—</span>';
    if (record.leave_reason) {
      const info = document.createElement('div');
      info.className = 'small text-muted';
      
      // Додаємо "(0.5 дня)" якщо це половина дня відпустки
      let leaveText = record.leave_reason;
      if (record.half_day_amount === 0.5) {
        leaveText += ' (0.5 дня)';
      }
      info.textContent = leaveText;
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
      row.appendChild(createTotalCell(record)); // Використовуємо createTotalCell замість createCell
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

      const hours = Math.floor(value / 60);
      const minutes = value % 60;
      const timeString = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;

      const separatorIndex = typeof label === 'string' ? label.indexOf('.') : -1;
      let fullText = label;
      if (separatorIndex > 0) {
        const abbr = label.slice(0, separatorIndex).trim();
        const datePart = label.slice(separatorIndex + 1).trim();
        const dayName = dayNames[abbr] || abbr;
        fullText = datePart ? `${dayName}, (${datePart})` : dayName;
      }

      const textLabel = document.createElement('div');
      textLabel.className = 'lateness-date';
      textLabel.textContent = `${fullText} - ${timeString}`;

      item.appendChild(textLabel);
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
    
    // Якщо поля дат порожні, використовуємо поточний місяць
    const hasDateFrom = dateFromInput && dateFromInput.value;
    const hasDateTo = dateToInput && dateToInput.value;
    
    if (!hasDateFrom && !hasDateTo) {
      // За замовчуванням: з 1-го числа поточного місяця до сьогодні
      const now = new Date();
      const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
      const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      
      const formatDate = (date) => {
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
      };
      
      params.set('date_from', formatDate(firstDay));
      params.set('date_to', formatDate(today));
    } else {
      if (hasDateFrom) {
        params.set('date_from', dateFromInput.value);
      }
      if (hasDateTo) {
        params.set('date_to', dateToInput.value);
      }
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
    
    // Показуємо поле Telegram тільки для адмінів
    const isAdmin = document.body.dataset.isAdmin === '1';
    if (isAdmin && telegramEditGroup && telegramModalInput) {
      telegramEditGroup.classList.remove('d-none');
      const currentTelegram = currentProfile.telegram_username || generateTelegramUsername(currentProfile.name);
      telegramModalInput.value = currentTelegram || '';
    } else if (telegramEditGroup) {
      telegramEditGroup.classList.add('d-none');
    }
    
    managerModal.show();
  }

  async function submitManagerModalForm(event) {
    event.preventDefault();
    if (!managerModalSelect) {
      return;
    }
    const value = managerModalSelect.value;
    const isAdmin = document.body.dataset.isAdmin === '1';
    
    try {
      // Оновлюємо control manager
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
      
      // Оновлюємо Telegram якщо адмін та поле видиме
      if (isAdmin && telegramModalInput && !telegramEditGroup.classList.contains('d-none')) {
        const telegramValue = telegramModalInput.value.trim();
        const telegramResponse = await fetch(`/api/users/${encodeURIComponent(userKey)}/telegram`, {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ telegram_username: telegramValue }),
        });
        if (!telegramResponse.ok) {
          const error = await telegramResponse.json().catch(() => ({}));
          throw new Error(error.error || 'Не удалось обновить Telegram');
        }
      }
      
      if (managerModal) {
        managerModal.hide();
      }
      showAlert('Данные обновлены', 'success', 3000);
      await loadData();
    } catch (error) {
      showAlert(error.message || 'Не удалось обновить данные');
    }
  }

  function openPlanStartModal() {
    if (!planStartModal || !planStartModalInput) {
      return;
    }
    const currentPlanStart = currentProfile.plan_start || '';
    planStartModalInput.value = currentPlanStart;
    planStartModal.show();
  }

  async function submitPlanStartModalForm(event) {
    event.preventDefault();
    if (!planStartModalInput) {
      return;
    }
    const value = planStartModalInput.value.trim();
    const action = event.submitter?.value || 'global';
    
    // Якщо застосовуємо до місяця, показуємо попередження
    if (action === 'apply_month') {
      const confirmed = confirm(
        'Применить новый плановый старт ко всем рабочим дням текущего месяца?\n\n' +
        'Будут обновлены только дни без ручных изменений scheduled_start.'
      );
      if (!confirmed) {
        return;
      }
    }
    
    try {
      const response = await fetch(`/api/users/${encodeURIComponent(userKey)}/plan_start`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          plan_start: value,
          apply_to_month: action === 'apply_month'
        }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || 'Не удалось обновить плановый старт');
      }
      
      const result = await response.json();
      if (planStartModal) {
        planStartModal.hide();
      }
      
      let message = 'Плановый старт обновлен';
      if (result.updated_days !== undefined) {
        message += ` (обновлено дней: ${result.updated_days})`;
      }
      showAlert(message, 'success', 3000);
      await loadData();
    } catch (error) {
      showAlert(error.message || 'Не удалось обновить плановый старт');
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
      configurePlanStartControl(Boolean(payload.permissions?.can_edit));
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

  if (planStartModalForm) {
    planStartModalForm.addEventListener('submit', submitPlanStartModalForm);
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

  // Графіки місячної статистики
  let notCategorizedChart = null;
  let productiveChart = null;
  let nonProductiveChart = null;
  let totalChart = null;

  function minutesToHoursString(minutes) {
    if (!minutes || minutes === 0) return '00:00';
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}`;
  }

  function createDoughnutChart(canvasId, minutes, label, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const ctx = canvas.getContext('2d');
    const timeString = minutesToHoursString(minutes);

    return new Chart(ctx, {
      type: 'doughnut',
      data: {
        datasets: [{
          data: [minutes, Math.max(0, 10000 - minutes)], // 10000 як максимальне значення для візуалізації
          backgroundColor: [color, '#e9ecef'],
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        cutout: '70%',
        plugins: {
          legend: {
            display: false
          },
          tooltip: {
            enabled: false
          }
        }
      },
      plugins: [{
        id: 'centerText',
        beforeDraw: function(chart) {
          const width = chart.width;
          const height = chart.height;
          const ctx = chart.ctx;
          ctx.restore();
          
          const fontSize = (height / 114).toFixed(2);
          ctx.font = `bold ${fontSize}em sans-serif`;
          ctx.textBaseline = 'middle';
          ctx.fillStyle = '#333';
          
          const text = timeString;
          const textX = Math.round((width - ctx.measureText(text).width) / 2);
          const textY = height / 2;
          
          ctx.fillText(text, textX, textY);
          ctx.save();
        }
      }]
    });
  }

  async function loadMonthlyStats() {
    try {
      const now = new Date();
      const year = now.getFullYear();
      const month = now.getMonth() + 1;
      
      // Визначаємо перший та останній день місяця
      const firstDay = new Date(year, month - 1, 1);
      const lastDay = new Date(year, month, 0);
      
      // Форматуємо дати для заголовка
      const formatDate = (date) => {
        const day = String(date.getDate()).padStart(2, '0');
        const mon = String(date.getMonth() + 1).padStart(2, '0');
        const yr = String(date.getFullYear()).slice(-2);
        return `${day}.${mon}.${yr}`;
      };
      
      // Оновлюємо заголовок
      const titleEl = document.getElementById('monthly-stats-title');
      if (titleEl) {
        titleEl.textContent = `Статистика за месяц: с ${formatDate(firstDay)} по ${formatDate(lastDay)}`;
      }
      
      const response = await fetch(`/api/users/${encodeURIComponent(userKey)}/monthly_category_stats?year=${year}&month=${month}`);
      if (!response.ok) {
        console.error('Failed to load monthly stats');
        return;
      }

      const data = await response.json();
      
      // Знищуємо старі графіки якщо існують
      if (notCategorizedChart) notCategorizedChart.destroy();
      if (productiveChart) productiveChart.destroy();
      if (nonProductiveChart) nonProductiveChart.destroy();
      if (totalChart) totalChart.destroy();

      // Створюємо нові графіки
      notCategorizedChart = createDoughnutChart(
        'notCategorizedChart',
        data.not_categorized || 0,
        'Not Categorized',
        '#6c757d'
      );

      productiveChart = createDoughnutChart(
        'productiveChart',
        data.productive || 0,
        'Productive',
        '#28a745'
      );

      nonProductiveChart = createDoughnutChart(
        'nonProductiveChart',
        data.non_productive || 0,
        'Non Productive',
        '#dc3545'
      );

      totalChart = createDoughnutChart(
        'totalChart',
        data.total || 0,
        'Total',
        '#007bff'
      );

      // Оновлюємо відображення місячних запізнень
      updateMonthlyLatenessBar(data.monthly_lateness || 0);

    } catch (error) {
      console.error('Error loading monthly stats:', error);
    }
  }

  function updateMonthlyLatenessBar(latenessMinutes) {
    const bar = document.getElementById('monthly-lateness-bar');
    const timeEl = document.getElementById('monthly-lateness-time');
    
    if (!bar || !timeEl) return;

    // Конвертуємо хвилини в формат HH:MM
    const timeString = minutesToHoursString(latenessMinutes);
    timeEl.textContent = timeString;

    // Розраховуємо відсоток запізнення (максимум 8 годин = 480 хвилин для візуалізації)
    const maxMinutes = 480; // 8 годин
    const percentage = Math.min((latenessMinutes / maxMinutes) * 100, 100);

    // Оновлюємо градієнт: червоний зліва на відсоток запізнення, зелений - решта
    bar.style.background = `linear-gradient(to right, #dc3545 0%, #dc3545 ${percentage}%, #28a745 ${percentage}%, #28a745 100%)`;
  }

  loadData();
  loadMonthlyStats();
})();
