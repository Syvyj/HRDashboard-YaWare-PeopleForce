// Monthly Report JavaScript
(function () {
  const reportBody = document.getElementById('monthly-report-body');
  const loadingSpinner = document.getElementById('loading-spinner');
  const filterMonth = document.getElementById('filter-month');
  
  if (!reportBody) {
    return;
  }

  // Modal elements
  const notesModalEl = document.getElementById('notesModal');
  const notesModal = notesModalEl ? new bootstrap.Modal(notesModalEl) : null;
  const notesUserKey = document.getElementById('notes-user-key');
  const notesText = document.getElementById('notes-text');
  const saveNotesBtn = document.getElementById('save-notes');

  // Edit all fields modal
  const editFieldsModalEl = document.getElementById('editFieldsModal');
  const editFieldsModal = editFieldsModalEl ? new bootstrap.Modal(editFieldsModalEl) : null;
  const saveAllFieldsBtn = document.getElementById('save-all-fields');

  let monthlyNotesCache = {};

  // Load report on page load
  loadMonthlyReport();

  // Event listeners - using same IDs as dashboard
  const filterForm = document.getElementById('filters-form');
  if (filterForm) {
    filterForm.addEventListener('submit', function (e) {
      e.preventDefault();
      loadMonthlyReport();
    });
  }

  const searchBtn = document.getElementById('search-btn');
  if (searchBtn) {
    searchBtn.addEventListener('click', function () {
      loadMonthlyReport();
    });
  }

  const resetBtn = document.getElementById('reset-filters');
  if (resetBtn) {
    resetBtn.addEventListener('click', function () {
      if (filterMonth) filterMonth.value = new Date().toISOString().slice(0, 7);
      const userInput = document.getElementById('filter-user');
      if (userInput) userInput.value = '';
      loadMonthlyReport();
    });
  }
  
  window.addEventListener('monthly-filters-updated', () => {
    loadMonthlyReport();
  });

  if (saveNotesBtn) {
    saveNotesBtn.addEventListener('click', function () {
      saveMonthlyNotes();
    });
  }

  if (saveAllFieldsBtn) {
    saveAllFieldsBtn.addEventListener('click', function () {
      saveAllFields();
    });
  }

  // Export button
  const exportBtn = document.getElementById('export-monthly-report-btn');
  const exportModalEl = document.getElementById('exportModal');
  if (exportBtn && exportModalEl) {
    const exportModal = new bootstrap.Modal(exportModalEl);
    
    exportBtn.addEventListener('click', function () {
      exportModal.show();
    });

    exportModalEl.addEventListener('click', function (e) {
      const target = e.target.closest('[data-export-format]');
      if (target) {
        const format = target.getAttribute('data-export-format');
        exportMonthlyReport(format);
        exportModal.hide();
      }
    });
  }

  // Load monthly report data
  function loadMonthlyReport() {
    const filters = getFilters();
    
    loadingSpinner.style.display = 'block';
    reportBody.innerHTML = '';

    // Build params with multiple filter support
    const params = new URLSearchParams();
    params.set('month', filters.month);
    if (filters.user) {
      params.set('user', filters.user);
    }

    // Add selected filters from report.js
    if (typeof window.selectedFilters !== 'undefined') {
      const sf = window.selectedFilters;
      if (sf.projects && sf.projects.size > 0) {
        Array.from(sf.projects).forEach(p => params.append('project', p));
      }
      if (sf.departments && sf.departments.size > 0) {
        Array.from(sf.departments).forEach(d => params.append('department', d));
      }
      if (sf.units && sf.units.size > 0) {
        Array.from(sf.units).forEach(u => params.append('unit', u));
      }
      if (sf.teams && sf.teams.size > 0) {
        Array.from(sf.teams).forEach(t => params.append('team', t));
      }
    }

    // Add selected employees from multi-select
    if (typeof window.selectedEmployees !== 'undefined' && window.selectedEmployees && window.selectedEmployees.size > 0) {
      Array.from(window.selectedEmployees).forEach(key => {
        params.append('user_key', key);
      });
    }

    if (typeof window.getIncludeArchivedParam === 'function') {
      params.set('include_archived', window.getIncludeArchivedParam());
    }

    // Load notes first
    loadMonthlyNotes(filters.month).then(() => {
      fetch('/api/monthly-report?' + params.toString())
        .then(response => response.json())
        .then(data => {
          loadingSpinner.style.display = 'none';
          console.log('Monthly report data:', data);
          console.log('First employee:', data.employees && data.employees[0]);
          if (data.filters && data.filters.options) {
            window.dispatchEvent(new CustomEvent('monthly-filter-options', { detail: data.filters.options }));
          }
          renderMonthlyReport(data);
        })
        .catch(error => {
          console.error('Error loading monthly report:', error);
          loadingSpinner.style.display = 'none';
          reportBody.innerHTML = `
            <tr>
              <td colspan="100%" class="text-center text-danger">
                Ошибка загрузки данных: ${error.message}
              </td>
            </tr>
          `;
        });
    });
  }

  // Load monthly notes from storage
  function loadMonthlyNotes(month) {
    return fetch('/api/monthly-notes?month=' + month)
      .then(response => response.json())
      .then(data => {
        if (data.notes) {
          monthlyNotesCache = data.notes;
        }
      })
      .catch(error => {
        console.error('Error loading notes:', error);
      });
  }

  // Get current filters - compatible with report.js filter structure
  function getFilters() {
    const filters = {
      month: filterMonth ? filterMonth.value : new Date().toISOString().slice(0, 7),
      user: document.getElementById('filter-user') ? document.getElementById('filter-user').value : '',
    };

    return filters;
  }

  // Render monthly report table
  function renderMonthlyReport(data) {
    if (!data || !data.employees || data.employees.length === 0) {
      reportBody.innerHTML = `
        <tr>
          <td colspan="100%" class="text-center">Нет данных для отображения</td>
        </tr>
      `;
      return;
    }

    const canEdit = document.body.getAttribute('data-can-edit') === '1';

    reportBody.innerHTML = data.employees.map(emp => {
      const notes = monthlyNotesCache[emp.user_key] || emp.notes || '';
      
      const userLink = emp.user_email || emp.user_key || emp.user_name;
      return `
        <tr>
          <td colspan="100%">
            <div class="row g-0">
              <div class="col-12 mb-2 d-flex justify-content-between align-items-center">
                <div>
                  <strong>
                    <a href="/users/${encodeURIComponent(userLink)}">${escapeHtml(emp.user_name)}</a>
                  </strong>
                  ${emp.division ? `<a href="#" class="badge bg-secondary ms-2 meta-link text-decoration-none" data-filter="project" data-value="${encodeURIComponent(emp.division)}">${escapeHtml(emp.division)}</a>` : ''}
                  ${emp.department ? `<a href="#" class="badge bg-info ms-1 meta-link text-decoration-none" data-filter="department" data-value="${encodeURIComponent(emp.department)}">${escapeHtml(emp.department)}</a>` : ''}
                  ${emp.unit ? `<a href="#" class="badge bg-light text-dark ms-1 meta-link text-decoration-none" data-filter="unit" data-value="${encodeURIComponent(emp.unit)}">${escapeHtml(emp.unit)}</a>` : ''}
                  ${emp.team ? `<a href="#" class="badge bg-light text-dark ms-1 meta-link text-decoration-none" data-filter="team" data-value="${encodeURIComponent(emp.team)}">${escapeHtml(emp.team)}</a>` : ''}
                </div>
                ${canEdit ? `
                  <button 
                    class="btn btn-sm btn-outline-success edit-all-fields-btn"
                    data-internal-user-id="${emp.internal_user_id || ''}"
                    data-user-name="${escapeHtml(emp.user_name)}"
                    data-plan-days="${emp.plan_days}"
                    data-vacation-days="${emp.vacation_days}"
                    data-day-off-days="${emp.day_off_days}"
                    data-sick-days="${emp.sick_days}"
                    data-fact-days="${emp.fact_days}"
                    data-minimum-hours="${escapeHtml(emp.minimum_hours)}"
                    data-delay-count="${emp.delay_count}"
                    data-tracked-hours="${escapeHtml(emp.tracked_hours)}"
                    data-corrected-hours="${escapeHtml(emp.corrected_hours)}"
                    data-notes="${escapeHtml(notes)}"
                    data-start-date="${emp.start_date || ''}"
                  >
                    <i class="bi bi-pencil-square"></i> Edit All
                  </button>
                ` : ''}
              </div>
              <div class="col">
                <div class="text-center p-2 border-end">
                  <div class="fw-bold">Plan Days</div>
                  <div class="fs-4">${emp.plan_days}</div>
                  <div class="small text-muted">Minimum per month</div>
                  <div>${escapeHtml(emp.minimum_hours)}</div>
                </div>
              </div>
              <div class="col">
                <div class="text-center p-2 border-end">
                  <div class="fw-bold">Vacation</div>
                  <div class="fs-4">${emp.vacation_days}</div>
                  <div class="small text-muted">Tracked Hours</div>
                  <div>${escapeHtml(emp.tracked_hours)}</div>
                </div>
              </div>
              <div class="col">
                <div class="text-center p-2 border-end">
                  <div class="fw-bold">Day Off</div>
                  <div class="fs-4">${emp.day_off_days}</div>
                  <div class="small text-muted">Delay >10</div>
                  <div>${emp.delay_count}</div>
                </div>
              </div>
              <div class="col">
                <div class="text-center p-2 border-end">
                  <div class="fw-bold">Sick</div>
                  <div class="fs-4">${emp.sick_days}</div>
                  <div class="small text-muted">Corrected Hours</div>
                  <div>${escapeHtml(emp.corrected_hours)}</div>
                </div>
              </div>
              <div class="col">
                <div class="text-center p-2 border-end">
                  <div class="fw-bold">Fact Days</div>
                  <div class="fs-4">${emp.fact_days}</div>
                </div>
              </div>
              <div class="col-2">
                <div class="p-2">
                  <div class="fw-bold mb-1">Notes</div>
                  ${canEdit ? `
                    <div class="d-flex align-items-center gap-2">
                      <span class="flex-grow-1">${escapeHtml(notes) || '—'}</span>
                      <button 
                        class="btn btn-sm btn-outline-primary edit-notes-btn"
                        data-user-key="${escapeHtml(emp.user_key)}"
                        data-notes="${escapeHtml(notes)}"
                      >
                        <i class="bi bi-pencil"></i>
                      </button>
                    </div>
                  ` : `<span>${escapeHtml(notes) || '—'}</span>`}
                </div>
              </div>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    if (canEdit) {
      document.querySelectorAll('.edit-notes-btn').forEach(btn => {
        btn.addEventListener('click', function () {
          const userKey = this.dataset.userKey;
          const noteValue = this.dataset.notes || '';
          openNotesModal(userKey, noteValue);
        });
      });

      document.querySelectorAll('.edit-all-fields-btn').forEach(btn => {
        btn.addEventListener('click', function () {
          openEditFieldsModal(this.dataset);
        });
      });
    }
  }

  // Open notes modal
  function openNotesModal(userKey, notes) {
    notesUserKey.value = userKey;
    notesText.value = notes || '';
    notesModal.show();
  }

  // Save monthly notes
  function saveMonthlyNotes() {
    const userKey = notesUserKey.value;
    const notes = notesText.value;
    const month = filterMonth.value;

    fetch('/api/monthly-notes', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        user_key: userKey,
        month: month,
        notes: notes,
      }),
    })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          monthlyNotesCache[userKey] = notes;
          notesModal.hide();
          loadMonthlyReport();
        } else {
          alert('Ошибка сохранения: ' + (data.error || 'Неизвестная ошибка'));
        }
      })
      .catch(error => {
        console.error('Error saving notes:', error);
        alert('Ошибка сохранения заметки');
      });
  }

  // Recalculate auto fields (Plan Days, Fact Days, Minimum Hours)
  function recalculateAutoFields() {
    console.log('recalculateAutoFields called');
    
    const getValue = (elementId) => {
      const elem = document.getElementById(elementId);
      return elem ? parseFloat(elem.value) || 0 : 0;
    };
    
    const setValue = (elementId, value) => {
      const elem = document.getElementById(elementId);
      if (elem) elem.value = value;
    };
    
    // 1. Перераховуємо Plan Days якщо вказана дата початку
    let planDays = getValue('edit-plan-days');
    const startDateElem = document.getElementById('edit-start-date');
    const startDate = startDateElem ? startDateElem.value : null;
    
    console.log('startDate:', startDate, 'filterMonth:', filterMonth.value);
    
    if (startDate && filterMonth.value) {
      const [year, month] = filterMonth.value.split('-').map(Number);
      const start = new Date(startDate);
      const monthEnd = new Date(year, month, 0); // Останній день місяця
      
      console.log('Calculating workDays from', start, 'to', monthEnd);
      
      // Рахуємо робочі дні від start до кінця місяця
      let workDays = 0;
      let current = new Date(start);
      while (current <= monthEnd) {
        const dayOfWeek = current.getDay();
        if (dayOfWeek !== 0 && dayOfWeek !== 6) { // Не субота і не неділя
          workDays++;
        }
        current.setDate(current.getDate() + 1);
      }
      
      planDays = workDays;
      setValue('edit-plan-days', planDays);
    }
    
    // 2. Рахуємо Fact Days = Plan - Vacation - DayOff - Sick
    const vacationDays = getValue('edit-vacation-days');
    const dayOffDays = getValue('edit-day-off-days');
    const sickDays = getValue('edit-sick-days');
    
    const factDays = Math.max(0, planDays - vacationDays - dayOffDays - sickDays);
    setValue('edit-fact-days', factDays);
    
    // 3. Рахуємо Minimum Hours = Fact Days × hours per day (from selector)
    const hoursPerDayElem = document.getElementById('edit-hours-per-day');
    const minHoursPerDay = hoursPerDayElem ? parseFloat(hoursPerDayElem.value) : 7.0;
    const totalMinutes = factDays * minHoursPerDay * 60;
    const hours = Math.floor(totalMinutes / 60);
    const mins = Math.floor(totalMinutes % 60);
    setValue('edit-minimum-hours', `${hours}:${mins.toString().padStart(2, '0')}`);
  }

  // Open edit all fields modal
  function openEditFieldsModal(data) {
    const month = filterMonth.value;
    
    document.getElementById('edit-internal-user-id').value = data.internalUserId;
    document.getElementById('edit-month').value = month;
    
    // Safely set values, checking if elements exist
    const setInputValue = (elementId, value) => {
      const elem = document.getElementById(elementId);
      if (elem) elem.value = value || '';
    };
    
    setInputValue('edit-start-date', data.start_date);
    setInputValue('edit-plan-days', data.planDays);
    setInputValue('edit-vacation-days', data.vacationDays);
    setInputValue('edit-day-off-days', data.dayOffDays);
    setInputValue('edit-sick-days', data.sickDays);
    setInputValue('edit-fact-days', data.factDays);
    setInputValue('edit-minimum-hours', data.minimumHours);
    setInputValue('edit-delay-count', data.delayCount);
    setInputValue('edit-tracked-hours', data.trackedHours);
    setInputValue('edit-corrected-hours', data.correctedHours);
    setInputValue('edit-notes', data.notes);
    
    // Set hours per day selector based on current minimum hours and fact days
    const hoursPerDayElem = document.getElementById('edit-hours-per-day');
    if (hoursPerDayElem && data.factDays && data.minimumHours) {
      const [hours, mins] = data.minimumHours.split(':').map(Number);
      const totalMinutes = hours * 60 + (mins || 0);
      const calculatedHoursPerDay = totalMinutes / (data.factDays * 60);
      // Round to nearest 0.5 and set selector
      if (calculatedHoursPerDay <= 6.75) {
        hoursPerDayElem.value = '6.5';
      } else {
        hoursPerDayElem.value = '7';
      }
    }
    
    document.getElementById('editFieldsModalLabel').textContent = 
      `Редактировать данные за месяц: ${data.userName}`;
    
    // Add event listeners for auto-calculation (with null check)
    ['edit-start-date', 'edit-plan-days', 'edit-vacation-days', 'edit-day-off-days', 'edit-sick-days', 'edit-hours-per-day'].forEach(id => {
      const elem = document.getElementById(id);
      if (elem) elem.addEventListener('input', recalculateAutoFields);
    });
    
    editFieldsModal.show();
  }

  // Save all fields
  function saveAllFields() {
    const internalUserId = document.getElementById('edit-internal-user-id').value;
    const month = document.getElementById('edit-month').value;
    
    const adjustments = {
      start_date: document.getElementById('edit-start-date').value || null,
      plan_days: parseFloat(document.getElementById('edit-plan-days').value) || 0,
      vacation_days: parseFloat(document.getElementById('edit-vacation-days').value) || 0,
      day_off_days: parseFloat(document.getElementById('edit-day-off-days').value) || 0,
      sick_days: parseFloat(document.getElementById('edit-sick-days').value) || 0,
      fact_days: parseFloat(document.getElementById('edit-fact-days').value) || 0,
      minimum_hours: document.getElementById('edit-minimum-hours').value || '',
      hours_per_day: parseFloat(document.getElementById('edit-hours-per-day').value) || 7.0,
      delay_count: parseInt(document.getElementById('edit-delay-count').value) || 0,
      tracked_hours: document.getElementById('edit-tracked-hours').value || '',
      corrected_hours: document.getElementById('edit-corrected-hours').value || '',
      notes: document.getElementById('edit-notes').value || ''
    };

    fetch('/api/monthly-adjustments', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        internal_user_id: internalUserId,
        month: month,
        adjustments: adjustments
      }),
    })
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          editFieldsModal.hide();
          loadMonthlyReport();
        } else {
          alert('Ошибка сохранения: ' + (data.error || 'Неизвестная ошибка'));
        }
      })
      .catch(error => {
        console.error('Error saving adjustments:', error);
        alert('Ошибка сохранения данных');
      });
  }



  // Export monthly report
  function exportMonthlyReport(format) {
    const filters = getFilters();
    const params = new URLSearchParams();
    params.set('month', filters.month);
    if (filters.user) {
      params.set('user', filters.user);
    }

    // Add selected filters
    if (typeof window.selectedFilters !== 'undefined') {
      const sf = window.selectedFilters;
      if (sf.projects && sf.projects.size > 0) {
        Array.from(sf.projects).forEach(p => params.append('project', p));
      }
      if (sf.departments && sf.departments.size > 0) {
        Array.from(sf.departments).forEach(d => params.append('department', d));
      }
      if (sf.units && sf.units.size > 0) {
        Array.from(sf.units).forEach(u => params.append('unit', u));
      }
      if (sf.teams && sf.teams.size > 0) {
        Array.from(sf.teams).forEach(t => params.append('team', t));
      }
    }

    // Add selected employees
    if (typeof window.selectedEmployees !== 'undefined' && window.selectedEmployees && window.selectedEmployees.size > 0) {
      Array.from(window.selectedEmployees).forEach(key => {
        params.append('user_key', key);
      });
    }
    if (typeof window.getIncludeArchivedParam === 'function') {
      params.set('include_archived', window.getIncludeArchivedParam());
    }
    
    const url = format === 'pdf'
      ? `/api/monthly-report/pdf?${params.toString()}`
      : `/api/monthly-report/excel?${params.toString()}`;
    
    window.open(url, '_blank');
  }

  // Escape HTML
  function escapeHtml(text) {
    const map = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    };
    return text ? text.replace(/[&<>"']/g, m => map[m]) : '';
  }
})();
