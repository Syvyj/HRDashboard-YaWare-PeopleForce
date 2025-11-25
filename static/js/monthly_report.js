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

    // Load notes first
    loadMonthlyNotes(filters.month).then(() => {
      fetch('/api/monthly-report?' + params.toString())
        .then(response => response.json())
        .then(data => {
          loadingSpinner.style.display = 'none';
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
              <div class="col-12 mb-2">
                <strong>
                  <a href="/users/${encodeURIComponent(userLink)}">${escapeHtml(emp.user_name)}</a>
                </strong>
                ${emp.division ? `<a href="#" class="badge bg-secondary ms-2 meta-link text-decoration-none" data-filter="project" data-value="${encodeURIComponent(emp.division)}">${escapeHtml(emp.division)}</a>` : ''}
                ${emp.department ? `<a href="#" class="badge bg-info ms-1 meta-link text-decoration-none" data-filter="department" data-value="${encodeURIComponent(emp.department)}">${escapeHtml(emp.department)}</a>` : ''}
                ${emp.unit ? `<a href="#" class="badge bg-light text-dark ms-1 meta-link text-decoration-none" data-filter="unit" data-value="${encodeURIComponent(emp.unit)}">${escapeHtml(emp.unit)}</a>` : ''}
                ${emp.team ? `<a href="#" class="badge bg-light text-dark ms-1 meta-link text-decoration-none" data-filter="team" data-value="${encodeURIComponent(emp.team)}">${escapeHtml(emp.team)}</a>` : ''}
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
