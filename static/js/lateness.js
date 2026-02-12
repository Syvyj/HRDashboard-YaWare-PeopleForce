(function () {
  const accordion = document.getElementById('lateness-accordion');
  if (!accordion) {
    return;
  }

  const form = document.getElementById('lateness-form');
  const daysSelect = document.getElementById('lateness-days');
  const endDateInput = document.getElementById('lateness-end-date');

  const defaultDays = Number(window.defaultLatenessDays) || 7;
  if (daysSelect) {
    daysSelect.value = String(defaultDays);
  }
  if (endDateInput && !endDateInput.value) {
    endDateInput.value = new Date().toISOString().slice(0, 10);
  }

  function formatMinutes(value) {
    if (value === null || value === undefined) {
      return '—';
    }
    const minutesNum = Number(value);
    if (Number.isNaN(minutesNum)) {
      return '—';
    }
    const abs = Math.abs(minutesNum);
    const hours = Math.floor(abs / 60)
      .toString()
      .padStart(2, '0');
    const minutes = (abs % 60).toString().padStart(2, '0');
    return `${hours}:${minutes}`;
  }

  function statusLabel(row) {
    if (row.status === 'late') {
      return 'Опоздал';
    }
    const reason = (row.leave_reason || '').toLowerCase();
    if (reason.includes('vacation') || reason.includes('отпуск') || reason.includes('відпуст')) {
      return 'Отпуск';
    }
    if (reason.includes('sick') || reason.includes('больнич') || reason.includes('лікар')) {
      return 'Больничный';
    }
    if (reason.includes('day off') || reason.includes('выходн') || reason.includes('вихідн') || reason.includes('без оплаты') || reason.includes('без сохранения') || reason.includes('за свой') || reason.includes('own cost')) {
      return 'Отпуск за свой счёт';
    }
    if (reason.includes('matern') || reason.includes('декрет')) {
      return 'Декрет';
    }
    return 'Отсутствует';
  }

  function createTable(rows) {
    if (!rows.length) {
      return '<div class="text-muted small">Нет записей</div>';
    }
    const header = `
      <thead>
        <tr>
          <th>Сотрудник</th>
          <th>Проект</th>
          <th>Команда</th>
          <th>План</th>
          <th>Факт</th>
          <th>Опоздание</th>
          <th>Статус</th>
        </tr>
      </thead>
    `;
    const body = rows
      .map((row) => {
        const minutes = formatMinutes(row.minutes_late);
        const status = statusLabel(row);
        const leaveReasonText = (row.leave_reason || '').trim();
        const statusDisplay = leaveReasonText ? `${status}<div class="text-muted small">${leaveReasonText}</div>` : status;
        return `
          <tr>
            <td>
              <div class="fw-semibold">${row.name || '—'}</div>
              ${row.email ? `<div class="text-muted small">${row.email}</div>` : ''}
            </td>
            <td>${row.project || '—'}</td>
            <td>${row.team || row.department || '—'}</td>
            <td>${row.scheduled_start || '—'}</td>
            <td>${row.actual_start || '—'}</td>
            <td>${minutes}</td>
            <td>${statusDisplay}</td>
          </tr>
        `;
      })
      .join('');
    return `<div class="table-responsive"><table class="table table-sm align-middle">${header}<tbody>${body}</tbody></table></div>`;
  }

  function renderReports(reports) {
    if (!reports.length) {
      accordion.innerHTML = '<div class="text-center text-muted py-5">Данные отсутствуют</div>';
      return;
    }
    const items = reports
      .map((report, idx) => {
        const collapseId = `lateness-collapse-${idx}`;
        const headingId = `lateness-heading-${idx}`;
        const totalIssues = (report.late?.length || 0) + (report.absent?.length || 0);
        const badgeClass = totalIssues > 0 ? 'bg-danger' : 'bg-success';
        return `
          <div class="accordion-item">
            <h2 class="accordion-header" id="${headingId}">
              <button class="accordion-button ${idx === 0 ? '' : 'collapsed'}" type="button" data-bs-toggle="collapse" data-bs-target="#${collapseId}" aria-expanded="${idx === 0 ? 'true' : 'false'}" aria-controls="${collapseId}">
                <div class="d-flex justify-content-between w-100">
                  <span>${report.date} (${report.weekday})</span>
                  <span class="badge ${badgeClass}">
                    ${totalIssues > 0 ? `${totalIssues} проблем` : 'Без опозданий'}
                  </span>
                </div>
              </button>
            </h2>
            <div id="${collapseId}" class="accordion-collapse collapse ${idx === 0 ? 'show' : ''}" aria-labelledby="${headingId}" data-bs-parent="#lateness-accordion">
              <div class="accordion-body">
                <h6 class="text-danger">Опоздания (${report.late.length})</h6>
                ${createTable(report.late)}
                <hr />
                <h6 class="text-warning">Отсутствующие (${report.absent.length})</h6>
                ${createTable(report.absent)}
              </div>
            </div>
          </div>
        `;
      })
      .join('');
    accordion.innerHTML = items;
  }

  async function loadReports() {
    const params = new URLSearchParams();
    if (daysSelect && daysSelect.value) {
      params.set('days', daysSelect.value);
    }
    if (endDateInput && endDateInput.value) {
      params.set('end_date', endDateInput.value);
    }
    accordion.innerHTML = '<div class="text-center text-muted py-5">Загрузка...</div>';
    try {
      const response = await fetch(`/api/lateness?${params.toString()}`);
      if (!response.ok) {
        throw new Error('Не удалось получить данные');
      }
      const payload = await response.json();
      const reports = payload.reports || [];
      reports.forEach((report) => {
        report.late = report.late || [];
        report.absent = report.absent || [];
      });
      renderReports(reports);
    } catch (error) {
      console.error(error);
      accordion.innerHTML = `<div class="alert alert-danger">Ошибка: ${error.message || 'неизвестна'}</div>`;
    }
  }

  if (form) {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      loadReports();
    });
  }

  loadReports();
  
  // Admin sync controls
  const syncSingleInput = document.getElementById('sync-single-date');
  const syncRangeStart = document.getElementById('sync-range-start');
  const syncRangeEnd = document.getElementById('sync-range-end');
  const syncSingleBtn = document.getElementById('sync-single-btn');
  const syncRangeBtn = document.getElementById('sync-range-btn');
  const syncSkipWeekends = document.getElementById('sync-skip-weekends');
  const syncIncludeAbsent = document.getElementById('sync-include-absent');
  const syncStatus = document.getElementById('sync-status');
  const isAdmin = window.isLatenessAdmin === 1 || window.isLatenessAdmin === '1';

  function updateButtonsDisabled(disabled) {
    if (syncSingleBtn) syncSingleBtn.disabled = disabled;
    if (syncRangeBtn) syncRangeBtn.disabled = disabled;
  }

  function setStatus(message, state) {
    if (!syncStatus) return;
    let textClass = 'text-muted';
    if (state === 'error') textClass = 'text-danger';
    if (state === 'success') textClass = 'text-success';
    if (state === 'loading') textClass = 'text-primary';
    syncStatus.className = `small ms-auto ${textClass}`;
    if (state === 'loading') {
      syncStatus.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${message || ''}`;
    } else {
      syncStatus.textContent = message || '';
    }
  }

  function setDefaultDates() {
    const today = new Date().toISOString().slice(0, 10);
    if (syncSingleInput && !syncSingleInput.value) {
      syncSingleInput.value = today;
    }
    if (syncRangeStart && !syncRangeStart.value) {
      syncRangeStart.value = today;
    }
    if (syncRangeEnd && !syncRangeEnd.value) {
      syncRangeEnd.value = today;
    }
  }

  async function syncLateness(payload) {
    const response = await fetch('/api/lateness/sync', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || 'Не вдалося синхронізувати дані');
    }
    return data;
  }

  function buildDateRange(startStr, endStr) {
    const start = new Date(startStr);
    const end = new Date(endStr);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
      throw new Error('Некорректные даты');
    }
    const dates = [];
    for (let dt = new Date(start); dt <= end; dt.setDate(dt.getDate() + 1)) {
      dates.push(dt.toISOString().slice(0, 10));
    }
    return dates;
  }

  if (isAdmin && (syncSingleBtn || syncRangeBtn)) {
    setDefaultDates();
  }

  if (isAdmin && syncSingleBtn) {
    syncSingleBtn.addEventListener('click', async () => {
      const targetDate = syncSingleInput?.value;
      if (!targetDate) {
        setStatus('Укажите дату для синхронизации', 'error');
        return;
      }
      setStatus(`Синхронизация ${targetDate}...`, 'loading');
      updateButtonsDisabled(true);
      try {
        await syncLateness({
          date: targetDate,
          skip_weekends: syncSkipWeekends ? syncSkipWeekends.checked : false,
          include_absent: syncIncludeAbsent ? syncIncludeAbsent.checked : true,
        });
        setStatus(`Готово для ${targetDate}`, 'success');
        loadReports();
      } catch (error) {
        setStatus(error.message || 'Ошибка', 'error');
      } finally {
        updateButtonsDisabled(false);
      }
    });
  }

  if (isAdmin && syncRangeBtn) {
    syncRangeBtn.addEventListener('click', async () => {
      const startStr = syncRangeStart?.value;
      const endStr = syncRangeEnd?.value;
      if (!startStr || !endStr) {
        setStatus('Укажите начало и конец периода', 'error');
        return;
      }
      let dates;
      try {
        dates = buildDateRange(startStr, endStr);
      } catch (error) {
        setStatus(error.message, 'error');
        return;
      }
      if (!dates.length) {
        setStatus('Диапазон пустой', 'error');
        return;
      }
      setStatus(`Синхронизация ${dates.length} дней...`, 'loading');
      updateButtonsDisabled(true);
      try {
        await syncLateness({
          start_date: startStr,
          end_date: endStr,
          skip_weekends: syncSkipWeekends ? syncSkipWeekends.checked : false,
          include_absent: syncIncludeAbsent ? syncIncludeAbsent.checked : true,
        });
        setStatus(`Синхронизовано ${dates.length} дней`, 'success');
        loadReports();
      } catch (error) {
        setStatus(error.message || 'Ошибка синхронизации', 'error');
      } finally {
        updateButtonsDisabled(false);
      }
    });
  }
})();
