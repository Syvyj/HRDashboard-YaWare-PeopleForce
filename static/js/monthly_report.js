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
  
  // Listen for filter modal apply button (from report.js)
  const filterModalApplyBtn = document.getElementById('filter-modal-apply');
  if (filterModalApplyBtn) {
    filterModalApplyBtn.addEventListener('click', function () {
      // Delay to let report.js update selectedFilters first
      setTimeout(() => loadMonthlyReport(), 100);
    });
  }
  
  // Listen for multi-select apply button (from report.js)
  const multiSelectApplyBtn = document.getElementById('multi-select-apply');
  if (multiSelectApplyBtn) {
    multiSelectApplyBtn.addEventListener('click', function () {
      setTimeout(() => loadMonthlyReport(), 100);
    });
  }

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

    // Load notes first
    loadMonthlyNotes(filters.month).then(() => {
      fetch('/api/monthly-report?' + new URLSearchParams(filters))
        .then(response => response.json())
        .then(data => {
          loadingSpinner.style.display = 'none';
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

    // Get selected filters from report.js if available
    if (typeof window.selectedFilters !== 'undefined') {
      const sf = window.selectedFilters;
      if (sf.projects && sf.projects.size > 0) {
        filters.project = Array.from(sf.projects)[0];  // Backend expects single project
      }
      if (sf.departments && sf.departments.size > 0) {
        filters.department = Array.from(sf.departments)[0];
      }
      if (sf.units && sf.units.size > 0) {
        filters.team = Array.from(sf.units)[0];  // Backend maps unit to team
      }
      if (sf.teams && sf.teams.size > 0) {
        filters.team = Array.from(sf.teams)[0];
      }
      if (sf.controlManager) {
        filters.manager = sf.controlManager;
      }
    }

    // Get selected employees from multi-select
    if (typeof window.selectedEmployeeKeys !== 'undefined' && window.selectedEmployeeKeys.length > 0) {
      filters.selected_users = window.selectedEmployeeKeys.join(',');
    }

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
      
      return `
        <tr>
          <td colspan="100%">
            <div class="row g-0">
              <div class="col-12 mb-2">
                <strong>${escapeHtml(emp.user_name)}</strong>
                <span class="text-muted ms-2">${escapeHtml(emp.user_email)}</span>
                ${emp.division ? `<span class="badge bg-secondary ms-2">${escapeHtml(emp.division)}</span>` : ''}
                ${emp.department ? `<span class="badge bg-info ms-1">${escapeHtml(emp.department)}</span>` : ''}
                ${emp.unit ? `<span class="badge bg-light text-dark ms-1">${escapeHtml(emp.unit)}</span>` : ''}
                ${emp.team ? `<span class="badge bg-light text-dark ms-1">${escapeHtml(emp.team)}</span>` : ''}
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

    // Add event listeners for edit buttons
    if (canEdit) {
      document.querySelectorAll('.edit-notes-btn').forEach(btn => {
        btn.addEventListener('click', function () {
          const userKey = this.getAttribute('data-user-key');
          const notes = this.getAttribute('data-notes');
          openNotesModal(userKey, notes);
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
    const params = new URLSearchParams(filters);
    
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
