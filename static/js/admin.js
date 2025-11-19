(() => {
  const root = document.getElementById('admin-app');
  if (!root) {
    return;
  }

  const alertsEl = document.getElementById('admin-alerts');
  const employeeTable = document.getElementById('employee-table');
  const employeeTbody = employeeTable.querySelector('tbody');
  const selectAllCheckbox = document.getElementById('employee-select-all');
  const searchInput = document.getElementById('employee-search');
  const searchBtn = document.getElementById('employee-search-btn');
  const resetBtn = document.getElementById('employee-reset-btn');
  const prevBtn = document.getElementById('employee-prev');
  const nextBtn = document.getElementById('employee-next');
  const pageInfo = document.getElementById('employee-page-info');
  const bulkManagerSelect = document.getElementById('bulk-manager-select');
  const bulkManagerApply = document.getElementById('bulk-manager-apply');
  const employeeEditModalEl = document.getElementById('employeeEditModal');
  const employeeEditForm = document.getElementById('employee-edit-form');
  const employeeEditKey = document.getElementById('employee-edit-key');
  const employeeEditName = document.getElementById('employee-edit-name');
  const employeeEditEmail = document.getElementById('employee-edit-email');
  const employeeEditUserId = document.getElementById('employee-edit-user-id');
  const employeeEditPeopleforceId = document.getElementById('employee-edit-peopleforce-id');
  const employeeEditProject = document.getElementById('employee-edit-project');
  const employeeEditDepartment = document.getElementById('employee-edit-department');
  const employeeEditUnit = document.getElementById('employee-edit-unit');
  const employeeEditTeam = document.getElementById('employee-edit-team');
  const employeeEditLocation = document.getElementById('employee-edit-location');
  const employeeEditPlanStart = document.getElementById('employee-edit-plan-start');
  const employeeEditManager = document.getElementById('employee-edit-manager');
  const appUserForm = document.getElementById('app-user-form');
  const appUsersTable = document.getElementById('app-users-table');
  const appUserModalEl = document.getElementById('appUserModal');
  const appUserEditForm = document.getElementById('app-user-edit-form');
  const syncUsersBtn = document.getElementById('sync-users-btn');
  const syncDateInput = document.getElementById('sync-date-input');
  const syncDateBtn = document.getElementById('sync-date-btn');
  const refreshDiffBtn = document.getElementById('refresh-diff-btn');
  const diffSummaryEl = document.getElementById('diff-summary');
  const diffListsWrapper = document.getElementById('diff-lists');
  const diffMissingYaWareList = document.getElementById('diff-missing-yaware-list');
  const diffMissingPeopleforceList = document.getElementById('diff-missing-peopleforce-list');
  const diffYaWareOnlyList = document.getElementById('diff-yaware-only-list');
  const diffPeopleforceOnlyList = document.getElementById('diff-peopleforce-only-list');
  const diffAddModalEl = document.getElementById('diffAddModal');
  const diffAddForm = document.getElementById('diff-add-form');
  const diffAddName = document.getElementById('diff-add-name');
  const diffAddEmail = document.getElementById('diff-add-email');
  const diffAddYaware = document.getElementById('diff-add-yaware');
  const diffAddPeopleforce = document.getElementById('diff-add-peopleforce');
  const diffAddProject = document.getElementById('diff-add-project');
  const diffAddDepartment = document.getElementById('diff-add-department');
  const diffAddTeam = document.getElementById('diff-add-team');
  const diffAddLocation = document.getElementById('diff-add-location');
  const diffAddPlanStart = document.getElementById('diff-add-plan-start');
  const diffAddManager = document.getElementById('diff-add-manager');
  const diffAddHireInfo = document.getElementById('diff-add-hire-info');
  const diffAddSubmit = document.getElementById('diff-add-submit');
  const employeeDeleteBtn = document.getElementById('employee-delete-btn');

  const employeeEditModal = employeeEditModalEl ? new bootstrap.Modal(employeeEditModalEl) : null;
  const appUserModal = appUserModalEl ? new bootstrap.Modal(appUserModalEl) : null;
  const diffAddModal = diffAddModalEl ? new bootstrap.Modal(diffAddModalEl) : null;

  let employeePage = 1;
  const perPage = 25;
  let employeeTotal = 0;
  let employeeSearch = '';
  let managerOptions = [];
  const selectedKeys = new Set();
  let diffState = null;
  let diffAddContext = null;

  // Modal filter variables
  const employeeFiltersModalEl = document.getElementById('employeeFiltersModal');
  const openEmployeeFiltersModalBtn = document.getElementById('open-employee-filters-modal');
  const employeeFilterModalApplyBtn = document.getElementById('employee-filter-modal-apply');
  const employeeFilterModalClearBtn = document.getElementById('employee-filter-modal-clear');
  const employeeSelectedFiltersDisplay = document.getElementById('employee-selected-filters-display');
  const employeeFilterProjectsList = document.getElementById('employee-filter-projects-list');
  const employeeFilterDepartmentsList = document.getElementById('employee-filter-departments-list');
  const employeeFilterUnitsList = document.getElementById('employee-filter-units-list');
  const employeeFilterTeamsList = document.getElementById('employee-filter-teams-list');
  
  let employeeFiltersModal = null; // Will be initialized when needed
  let currentEmployeeFilterOptions = { projects: [], departments: [], units: [], teams: [] };
  let selectedEmployeeFilters = { projects: new Set(), departments: new Set(), units: new Set(), teams: new Set() };

  function setButtonLoading(button, isLoading) {
    if (!button) {
      return;
    }
    if (isLoading) {
      button.disabled = true;
      button.classList.add('btn-loading');
      const extra = button.dataset.loadingClass;
      if (extra && !button.dataset.loadingExtraApplied) {
        extra.split(/\s+/).forEach((cls) => {
          if (cls) {
            button.classList.add(cls);
          }
        });
        button.dataset.loadingExtraApplied = '1';
      }
    } else {
      button.disabled = false;
      button.classList.remove('btn-loading');
      if (button.dataset.loadingExtraApplied) {
        const extra = button.dataset.loadingClass;
        if (extra) {
          extra.split(/\s+/).forEach((cls) => {
            if (cls) {
              button.classList.remove(cls);
            }
          });
        }
        delete button.dataset.loadingExtraApplied;
      }
    }
  }

  function showAlert(message, type = 'danger', timeout = 5000) {
    if (!alertsEl) {
      return;
    }
    const wrapper = document.createElement('div');
    wrapper.className = `alert alert-${type} alert-dismissible fade show`;
    wrapper.role = 'alert';
    wrapper.innerHTML = `
      ${message}
      <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    alertsEl.appendChild(wrapper);
    if (timeout > 0) {
      setTimeout(() => {
        const alert = bootstrap.Alert.getOrCreateInstance(wrapper);
        alert.close();
      }, timeout);
    }
  }

  function renderManagerOptions(selectEl, currentValue) {
    if (!selectEl) {
      return;
    }
    selectEl.innerHTML = '<option value="">—</option>';
    managerOptions.forEach((value) => {
      const option = document.createElement('option');
      option.value = String(value);
      option.textContent = `Manager #${value}`;
      selectEl.appendChild(option);
    });
    selectEl.value = currentValue != null && currentValue !== '' ? String(currentValue) : '';
  }

  function updateBulkButtonState() {
    bulkManagerApply.disabled = selectedKeys.size === 0;
  }

  function populateFilterSelect(selectEl, values, currentValue) {
    if (!selectEl) {
      return;
    }
    const normalizedValues = Array.from(new Set(values || [])).filter(Boolean).sort((a, b) => a.localeCompare(b));
    const selected = currentValue || '';
    selectEl.innerHTML = '<option value="">Все</option>';
    normalizedValues.forEach((value) => {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = value;
      selectEl.appendChild(option);
    });
    if (normalizedValues.includes(selected)) {
      selectEl.value = selected;
    } else if (selected) {
      const option = document.createElement('option');
      option.value = selected;
      option.textContent = selected;
      selectEl.appendChild(option);
      selectEl.value = selected;
    }
  }

  function normalizeDiffKey(value) {
    if (value == null) {
      return null;
    }
    const text = String(value).trim().toLowerCase();
    return text || null;
  }

  function findDiffInfo(item) {
    if (!diffState || !diffState.local_presence) {
      return null;
    }
    const candidates = [];
    if (item.user_id) {
      const normalized = normalizeDiffKey(item.user_id);
      if (normalized) {
        candidates.push(normalized);
      }
    }
    if (item.email) {
      const normalized = normalizeDiffKey(item.email);
      if (normalized) {
        candidates.push(normalized);
      }
    }
    if (item.peopleforce_id) {
      const normalized = normalizeDiffKey(item.peopleforce_id);
      if (normalized) {
        candidates.push(normalized);
      }
    }
    if (item.name) {
      const normalized = normalizeDiffKey(item.name);
      if (normalized) {
        candidates.push(normalized);
      }
    }
    for (const key of candidates) {
      const info = diffState.local_presence[key];
      if (info) {
        return info;
      }
    }
    return null;
  }

  function applyDiffHighlight(row, item) {
    if (!row) {
      return;
    }
    row.classList.remove('diff-missing-yaware', 'diff-missing-peopleforce');
    if (!item) {
      return;
    }
    const info = findDiffInfo(item);
    if (!info) {
      return;
    }
    if (info.in_yaware === false) {
      row.classList.add('diff-missing-yaware');
    }
    if (info.in_peopleforce === false) {
      row.classList.add('diff-missing-peopleforce');
    }
  }

  function applyDiffToExistingRows() {
    if (!diffState || !employeeTbody) {
      return;
    }
    employeeTbody.querySelectorAll('tr[data-employee]').forEach((row) => {
      try {
        const raw = row.dataset.employee;
        if (!raw) {
          return;
        }
        const item = JSON.parse(raw);
        applyDiffHighlight(row, item);
      } catch (error) {
        console.error('Failed to parse employee payload for diff highlight', error);
      }
    });
  }

  function updateDiffSummary(data) {
    if (!diffSummaryEl) {
      return;
    }
    if (!data) {
      diffSummaryEl.textContent = '';
      return;
    }
    const counts = data.counts || {};
    // Show only total count in base
    if (counts.local_total != null) {
      diffSummaryEl.textContent = `В базе: ${counts.local_total}`;
    } else if (data.generated_at) {
      diffSummaryEl.textContent = `Обновлено ${new Date(data.generated_at).toLocaleString()}`;
    } else {
      diffSummaryEl.textContent = '';
    }
  }

  function renderDiffList(target, items, options = {}) {
    if (!target) {
      return;
    }
    target.innerHTML = '';
    if (!items || !items.length) {
      const empty = document.createElement('li');
      empty.className = 'text-muted';
      empty.textContent = '—';
      target.appendChild(empty);
      return;
    }
    items.forEach((item) => {
      const li = document.createElement('li');
      li.className = 'diff-list-item';
      const label = document.createElement('span');
      if (typeof item === 'string') {
        label.textContent = item;
      } else if (item && typeof item === 'object') {
        label.textContent = item.display || item.email || item.name || '';
      } else {
        label.textContent = String(item);
      }
      li.appendChild(label);
      if (options.type === 'peopleforce' && item && typeof item === 'object') {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-sm btn-primary diff-add-btn';
        btn.textContent = 'Добавить';
        btn.dataset.entry = JSON.stringify(item);
        li.appendChild(btn);
      }
      target.appendChild(li);
    });
  }

  function updateDiffLists(data) {
    if (!diffListsWrapper) {
      return;
    }
    if (!data) {
      diffListsWrapper.hidden = true;
      return;
    }
    const missingYaWare = data.missing_yaware || [];
  	const missingPeopleforce = data.missing_peopleforce || [];
    const yawareOnly = data.yaware_only || [];
    const peopleforceOnly = data.peopleforce_only || [];

    renderDiffList(diffMissingYaWareList, missingYaWare);
    renderDiffList(diffMissingPeopleforceList, missingPeopleforce);
    renderDiffList(diffYaWareOnlyList, yawareOnly, { type: 'yaware' });
    renderDiffList(diffPeopleforceOnlyList, peopleforceOnly, { type: 'peopleforce' });

    diffListsWrapper.hidden = false;
  }

  function handleDiffErrors(errors) {
    if (!errors) {
      return;
    }
    if (errors.yaware) {
      showAlert(`Не удалось получить данные YaWare: ${errors.yaware}`, 'warning', 8000);
    }
    if (errors.peopleforce) {
      showAlert(`Не удалось получить данные PeopleForce: ${errors.peopleforce}`, 'warning', 8000);
    }
  }

  if (diffListsWrapper) {
    diffListsWrapper.addEventListener('click', (event) => {
      const button = event.target.closest('.diff-add-btn');
      if (!button) {
        return;
      }
      const raw = button.dataset.entry;
      if (!raw) {
        return;
      }
      let data;
      try {
        data = JSON.parse(raw);
      } catch (error) {
        console.error('Failed to parse diff entry payload', error);
        return;
      }
      openDiffAddModal(data);
    });
  }

  function setDiffState(data) {
    if (!data) {
      diffState = null;
      updateDiffSummary(null);
      updateDiffLists(null);
      applyDiffToExistingRows();
      return;
    }
    diffState = data;
    updateDiffSummary(data);
    updateDiffLists(data);
    handleDiffErrors(data.errors);
    applyDiffToExistingRows();
  }

  function openDiffAddModal(data) {
    if (!diffAddModal || !diffAddForm) {
      return;
    }
    diffAddContext = data || {};
    diffAddForm.reset();
    const managerValue = data && data.control_manager != null && data.control_manager !== ''
      ? String(data.control_manager)
      : '';
    renderManagerOptions(diffAddManager, managerValue);
    diffAddName.value = (data && data.name) || (data && data.display) || '';
    diffAddEmail.value = (data && data.email) || '';
    diffAddPeopleforce.value = (data && (data.peopleforce_id || data.user_id)) || '';
    diffAddYaware.value = (data && (data.yaware_user_id || data.yaware_id)) || '';
    diffAddProject.value = (data && data.project) || '';
    diffAddDepartment.value = (data && data.department) || '';
    diffAddTeam.value = (data && data.team) || '';
    diffAddLocation.value = (data && data.location) || '';
    diffAddPlanStart.value = (data && (data.plan_start || data.start_time)) || '09:00';
    if (diffAddHireInfo) {
      diffAddHireInfo.textContent = data && data.hire_date
        ? `Дата найму PeopleForce: ${new Date(data.hire_date).toLocaleDateString()}`
        : '';
    }
    diffAddModal.show();
  }

  function renderEmployees(data) {
    const items = data.items || [];
    managerOptions = data.manager_options || [];
    renderManagerOptions(bulkManagerSelect, bulkManagerSelect.value);
    renderManagerOptions(employeeEditManager, employeeEditManager ? employeeEditManager.value : '');
    renderManagerOptions(diffAddManager, diffAddManager ? diffAddManager.value : '');

    if (data.filters) {
      // Store filter options for modal
      currentEmployeeFilterOptions = {
        projects: data.filters.project || [],
        departments: data.filters.department || [],
        units: data.filters.unit || [],
        teams: data.filters.team || []
      };
      
      // No need to restore - filters are already in selectedEmployeeFilters from modal selection
      
      updateEmployeeSelectedFiltersDisplay();
    }

    employeeTotal = data.total || 0;
    employeePage = data.page || 1;

    selectedKeys.clear();
    selectAllCheckbox.checked = false;

    if (!items.length) {
      employeeTbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Нет данных</td></tr>';
      pageInfo.textContent = '0 записей';
      prevBtn.disabled = true;
      nextBtn.disabled = true;
      updateBulkButtonState();
      return;
    }

    const fragment = document.createDocumentFragment();
    items.forEach((item) => {
      const row = document.createElement('tr');
      row.dataset.userKey = item.user_key;
      row.dataset.employee = JSON.stringify(item);

      const checkboxCell = document.createElement('td');
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'form-check-input employee-checkbox';
      checkbox.dataset.userKey = item.user_key;
      checkboxCell.appendChild(checkbox);
      row.appendChild(checkboxCell);

      const nameCell = document.createElement('td');
      nameCell.innerHTML = `<strong>${item.name || '—'}</strong>`;
      row.appendChild(nameCell);

      const contactCell = document.createElement('td');
      contactCell.innerHTML = `<div>${item.email || '—'}</div>`;
      row.appendChild(contactCell);

      const hierarchyCell = document.createElement('td');
      const hierarchyParts = [
        item.project ? `<strong>${item.project}</strong>` : null,
        item.department || null,
        item.unit || null,
        item.team || null
      ].filter(Boolean);
      hierarchyCell.innerHTML = hierarchyParts.length ? hierarchyParts.join(' → ') : '—';
      row.appendChild(hierarchyCell);

      const managerCell = document.createElement('td');
      managerCell.innerHTML = item.control_manager != null ? `#${item.control_manager}` : '—';
      row.appendChild(managerCell);

      const actionsCell = document.createElement('td');
      actionsCell.className = 'text-center';
      actionsCell.style.whiteSpace = 'nowrap';
      
      // Edit button
      const editBtn = document.createElement('button');
      editBtn.type = 'button';
      editBtn.className = 'btn btn-sm btn-outline-primary me-1';
      editBtn.dataset.userPayload = JSON.stringify(item);
      editBtn.classList.add('employee-edit-btn');
      editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
      editBtn.title = 'Редагувати';
      actionsCell.appendChild(editBtn);
      
      // Ignore/Unignore button
      const ignoreBtn = document.createElement('button');
      ignoreBtn.type = 'button';
      ignoreBtn.dataset.userKey = item.user_key;
      ignoreBtn.title = item.ignored ? 'Повернути в звіти' : 'Виключити зі звітів';
      
      if (item.ignored) {
        ignoreBtn.className = 'btn btn-sm btn-outline-success employee-unignore-btn';
        ignoreBtn.innerHTML = '<i class="bi bi-eye"></i>';
      } else {
        ignoreBtn.className = 'btn btn-sm btn-outline-warning employee-ignore-btn';
        ignoreBtn.innerHTML = '<i class="bi bi-eye-slash"></i>';
      }
      
      actionsCell.appendChild(ignoreBtn);
      row.appendChild(actionsCell);

      fragment.appendChild(row);
      applyDiffHighlight(row, item);
    });

    employeeTbody.innerHTML = '';
    employeeTbody.appendChild(fragment);

    const totalPages = Math.ceil(employeeTotal / perPage) || 1;
    pageInfo.textContent = `${employeePage} / ${totalPages} (всего ${employeeTotal})`;
    prevBtn.disabled = employeePage <= 1;
    nextBtn.disabled = employeePage >= totalPages;
    updateBulkButtonState();
    applyDiffToExistingRows();
  }

  function fetchEmployees() {
    const params = new URLSearchParams({ page: employeePage, per_page: perPage });
    if (employeeSearch) {
      params.set('search', employeeSearch);
    }
    
    // Use shared filter builder for project/department/team filters
    const filterParams = buildFilterParams(null, null, null, selectedEmployeeFilters);
    for (const [key, value] of filterParams.entries()) {
      params.append(key, value);
    }

    employeeTbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Загрузка...</td></tr>';

    fetch(`/api/admin/employees?${params.toString()}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error('Не удалось получить данные сотрудников');
        }
        return response.json();
      })
      .then(renderEmployees)
      .catch((error) => {
        employeeTbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">Ошибка загрузки</td></tr>';
        showAlert(error.message);
      });
  }

  function fetchDiffState(options = {}) {
    const force = options.force ? '?force=1' : '';
    return fetch(`/api/admin/users/diff${force}`)
      .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          throw new Error(data.error || 'Не удалось получить сравнение пользователей');
        }
        setDiffState(data);
        return data;
      })
      .catch((error) => {
        showAlert(error.message);
        throw error;
      });
  }

  function performUserSync() {
    if (!syncUsersBtn) {
      return Promise.resolve();
    }
    setButtonLoading(syncUsersBtn, true);
    return fetch('/api/admin/sync/users', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ force_refresh: true }),
    })
      .then((response) => {
        // Перевіряємо чи відповідь дійсно JSON
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
          throw new Error('Сервер повернув некоректну відповідь (не JSON). Можливо помилка на сервері.');
        }
        return response.json().then((data) => ({ ok: response.ok, data }));
      })
      .then(({ ok, data }) => {
        if (!ok) {
          throw new Error(data.error || 'Не удалось выполнить синхронизацию');
        }
        showAlert('Синхронизация пользователей завершена', 'success');
        if (data && data.diff) {
          setDiffState(data.diff);
        }
        fetchEmployees();
        return data;
      })
      .catch((error) => {
        showAlert(error.message);
        throw error;
      })
      .finally(() => {
        setButtonLoading(syncUsersBtn, false);
      });
  }

  function performDateSync() {
    if (!syncDateBtn) {
      return;
    }
    const targetDate = (syncDateInput && syncDateInput.value ? syncDateInput.value : '').trim();
    if (!targetDate) {
      showAlert('Выберите дату для синхронизации', 'warning');
      return;
    }
    setButtonLoading(syncDateBtn, true);

    const payload = {
      date: targetDate,
      skip_weekends: false,
      include_absent: true,
    };

    fetch('/api/admin/sync/attendance', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })
      .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          throw new Error(data.error || 'Не удалось синхронизировать дату');
        }
        if (data.skipped) {
          showAlert('Дата припадает на выходной. Синхронизацию пропущено.', 'warning');
          return;
        }
        showAlert(`Данные за ${data.date} обновлены`, 'success');
        fetchEmployees();
      })
      .catch((error) => showAlert(error.message))
      .finally(() => {
        setButtonLoading(syncDateBtn, false);
      });
  }

  function performDateDelete() {
    const deleteDateBtn = document.getElementById('delete-date-btn');
    if (!deleteDateBtn) {
      return;
    }
    const targetDate = (syncDateInput && syncDateInput.value ? syncDateInput.value : '').trim();
    if (!targetDate) {
      showAlert('Виберіть дату для видалення', 'warning');
      return;
    }
    
    if (!confirm(`Ви впевнені, що хочете видалити ВСІ записи за ${targetDate}?\n\nЦю дію неможливо скасувати!`)) {
      return;
    }
    
    setButtonLoading(deleteDateBtn, true);

    fetch(`/api/admin/attendance/${targetDate}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
      },
    })
      .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          throw new Error(data.error || 'Не вдалося видалити дату');
        }
        showAlert(`Видалено ${data.deleted_count} записів за ${data.date}`, 'success');
        fetchEmployees();
      })
      .catch((error) => showAlert(error.message))
      .finally(() => {
        setButtonLoading(deleteDateBtn, false);
      });
  }

  function getSelectedKeys() {
    return Array.from(selectedKeys);
  }

  function toggleSelection(key, isChecked) {
    if (!key) {
      return;
    }
    if (isChecked) {
      selectedKeys.add(key);
    } else {
      selectedKeys.delete(key);
    }
    updateBulkButtonState();
  }

  function applyManagerChange(keys, value) {
    if (!keys.length) {
      return Promise.resolve();
    }
    const payload = {
      user_keys: keys,
      control_manager: value === '' ? null : value,
    };

    return fetch('/api/admin/employees/manager', {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    })
      .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
      .then(({ ok, data }) => {
        if (!ok) {
          throw new Error(data.error || 'Не удалось обновить менеджера');
        }
        showAlert(`Обновлено ${data.updated_records} записей`, 'success');
        fetchEmployees();
      })
      .catch((error) => {
        showAlert(error.message);
      });
  }

  function handleTableChange(event) {
    const target = event.target;
    if (target.matches('.employee-checkbox')) {
      toggleSelection(target.dataset.userKey, target.checked);
      selectAllCheckbox.checked = selectedKeys.size > 0 && Array.from(employeeTbody.querySelectorAll('.employee-checkbox')).every((input) => input.checked);
    } else if (target === selectAllCheckbox) {
      const checked = target.checked;
      employeeTbody.querySelectorAll('.employee-checkbox').forEach((checkbox) => {
        checkbox.checked = checked;
        toggleSelection(checkbox.dataset.userKey, checked);
      });
    }
  }

  function openEmployeeModal(target) {
    if (!employeeEditModal || !target) {
      return;
    }
    const raw = target.dataset.userPayload;
    if (!raw) {
      return;
    }
    let payload;
    try {
      payload = JSON.parse(raw);
    } catch (error) {
      console.error('Failed to parse payload', error);
      return;
    }
    employeeEditKey.value = payload.user_key || '';
    employeeEditName.value = payload.name || '';
    employeeEditEmail.value = payload.email || '';
    employeeEditUserId.value = payload.user_id || '';
    if (employeeEditPeopleforceId) {
      employeeEditPeopleforceId.value = payload.peopleforce_id || '';
    }
    employeeEditProject.value = payload.project || '';
    employeeEditDepartment.value = payload.department || '';
    employeeEditUnit.value = payload.unit || '';
    employeeEditTeam.value = payload.team || '';
    employeeEditLocation.value = payload.location || '';
    employeeEditPlanStart.value = payload.plan_start || '';
    renderManagerOptions(employeeEditManager, payload.control_manager != null ? payload.control_manager : '');
    employeeEditModal.show();
  }

  function handleEmployeeTableClick(event) {
    const editBtn = event.target.closest('.employee-edit-btn');
    if (editBtn) {
      openEmployeeModal(editBtn);
    }
  }

  function fetchAppUsers() {
    const tbody = appUsersTable.querySelector('tbody');
    tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">Загрузка...</td></tr>';
    fetch('/api/admin/app-users')
      .then((response) => {
        if (!response.ok) {
          throw new Error('Не удалось получить пользователей ');
        }
        return response.json();
      })
      .then((payload) => {
        const items = payload.items || [];
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">Нет пользователей</td></tr>';
          return;
        }
       const fragment = document.createDocumentFragment();
       items.forEach((user) => {
         const row = document.createElement('tr');
         row.dataset.userId = user.id;
         
         // Determine role badge
         let roleBadge = '';
         if (user.is_admin) {
           roleBadge = '<span class="badge bg-primary">Admin</span>';
         } else if (user.is_control_manager) {
           roleBadge = '<span class="badge bg-info">C.M.</span>';
         } else {
           roleBadge = '<span class="badge bg-secondary">Manager</span>';
         }
         
          row.innerHTML = `
            <td>${user.email}</td>
            <td>${user.name}</td>
            <td>${roleBadge}</td>
            <td>${user.manager_filter || '—'}</td>
            <td class="text-center"></td>
          `;
          const actionsCell = row.lastElementChild;
          const editBtn = document.createElement('button');
          editBtn.type = 'button';
          editBtn.className = 'btn btn-sm btn-outline-primary app-user-edit';
          editBtn.innerHTML = '<i class="bi bi-pencil"></i>';
          editBtn.dataset.user = JSON.stringify(user);
          actionsCell.appendChild(editBtn);
          fragment.appendChild(row);
        });
        tbody.innerHTML = '';
        tbody.appendChild(fragment);
      })
      .catch((error) => {
        appUsersTable.querySelector('tbody').innerHTML = '<tr><td colspan="5" class="text-center text-danger py-4">Ошибка загрузки</td></tr>';
        showAlert(error.message);
      });
  }

  // Event bindings
  employeeTable.addEventListener('change', handleTableChange);
  employeeTable.addEventListener('click', handleEmployeeTableClick);

  if (diffAddForm) {
    diffAddForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const name = (diffAddName ? diffAddName.value : '').trim();
      const email = (diffAddEmail ? diffAddEmail.value : '').trim();
      if (!name || !email) {
        showAlert('Заполните имя и email для нового пользователя', 'warning');
        return;
      }
      const payload = {
        name,
        email,
        user_id: (diffAddYaware ? diffAddYaware.value : '').trim(),
        peopleforce_id: (diffAddPeopleforce ? diffAddPeopleforce.value : '').trim(),
        project: (diffAddProject ? diffAddProject.value : '').trim(),
        department: (diffAddDepartment ? diffAddDepartment.value : '').trim(),
        team: (diffAddTeam ? diffAddTeam.value : '').trim(),
        location: (diffAddLocation ? diffAddLocation.value : '').trim(),
        plan_start: (diffAddPlanStart ? diffAddPlanStart.value : '').trim(),
        control_manager: diffAddManager ? diffAddManager.value : '',
      };
      setButtonLoading(diffAddSubmit, true);
      fetch('/api/admin/employees', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          if (!ok) {
            throw new Error(data.error || 'Не удалось добавить пользователя');
          }
          showAlert('Пользователь добавлен', 'success');
          if (diffAddModal) {
            diffAddModal.hide();
          }
          diffAddContext = null;
          fetchDiffState({ force: true }).catch(() => {});
          fetchEmployees();
        })
        .catch((error) => {
          showAlert(error.message || 'Произошла ошибка');
        })
        .finally(() => {
          setButtonLoading(diffAddSubmit, false);
        });
    });
  }

  if (syncUsersBtn) {
    syncUsersBtn.addEventListener('click', () => {
      performUserSync().catch(() => {});
    });
  }

  if (refreshDiffBtn) {
    refreshDiffBtn.addEventListener('click', () => {
      setButtonLoading(refreshDiffBtn, true);
      fetchDiffState({ force: true })
        .catch(() => {})
        .finally(() => {
          setButtonLoading(refreshDiffBtn, false);
        });
    });
  }

  if (syncDateBtn) {
    syncDateBtn.addEventListener('click', performDateSync);
  }

  const deleteDateBtn = document.getElementById('delete-date-btn');
  if (deleteDateBtn) {
    deleteDateBtn.addEventListener('click', performDateDelete);
  }

  if (searchBtn) {
    searchBtn.addEventListener('click', () => {
      employeeSearch = (searchInput.value || '').trim();
      employeePage = 1;
      fetchEmployees();
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      searchInput.value = '';
      employeeSearch = '';
      selectedEmployeeFilters = { projects: new Set(), departments: new Set(), units: new Set(), teams: new Set() };
      updateEmployeeSelectedFiltersDisplay();
      employeePage = 1;
      fetchEmployees();
    });
  }

  if (prevBtn) {
    prevBtn.addEventListener('click', () => {
      if (employeePage > 1) {
        employeePage -= 1;
        fetchEmployees();
      }
    });
  }

  if (nextBtn) {
    nextBtn.addEventListener('click', () => {
      const totalPages = Math.ceil(employeeTotal / perPage) || 1;
      if (employeePage < totalPages) {
        employeePage += 1;
        fetchEmployees();
      }
    });
  }

  if (bulkManagerSelect) {
    bulkManagerSelect.addEventListener('change', updateBulkButtonState);
  }

  // Old select filters - removed in favor of modal-based filters

  if (bulkManagerApply) {
    bulkManagerApply.addEventListener('click', () => {
      const keys = getSelectedKeys();
      const value = bulkManagerSelect.value;
      applyManagerChange(keys, value);
    });
  }

  if (employeeEditForm) {
    employeeEditForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const key = (employeeEditKey.value || '').trim();
      if (!key) {
        return;
      }
      const payload = {
        name: (employeeEditName.value || '').trim(),
        email: (employeeEditEmail.value || '').trim(),
        user_id: (employeeEditUserId.value || '').trim(),
        peopleforce_id: employeeEditPeopleforceId ? (employeeEditPeopleforceId.value || '').trim() : '',
        project: (employeeEditProject.value || '').trim(),
        department: (employeeEditDepartment.value || '').trim(),
        unit: (employeeEditUnit.value || '').trim(),
        team: (employeeEditTeam.value || '').trim(),
        location: (employeeEditLocation.value || '').trim(),
        plan_start: (employeeEditPlanStart.value || '').trim(),
        control_manager: employeeEditManager.value,
      };

      fetch(`/api/admin/employees/${encodeURIComponent(key)}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          if (!ok) {
            throw new Error(data.error || 'Не удалось обновить данные сотрудника');
          }
          showAlert('Данные сотрудника обновлены', 'success');
          if (employeeEditModal) {
            employeeEditModal.hide();
          }
          fetchEmployees();
        })
        .catch((error) => showAlert(error.message));
    });
  }

  if (employeeDeleteBtn && employeeEditModal) {
    employeeDeleteBtn.addEventListener('click', () => {
      const key = (employeeEditKey.value || '').trim();
      if (!key) {
        return;
      }
      if (!window.confirm('Удалить пользователя и все записи attendance?')) {
        return;
      }
      employeeDeleteBtn.disabled = true;
      fetch(`/api/admin/employees/${encodeURIComponent(key)}`, {
        method: 'DELETE',
      })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          if (!ok) {
            throw new Error(data.error || 'Не удалось удалить пользователя');
          }
          showAlert('Пользователь удален', 'success');
          if (employeeEditModal) {
            employeeEditModal.hide();
          }
          fetchEmployees();
          fetchDiffState().catch(() => {});
        })
        .catch((error) => showAlert(error.message))
        .finally(() => {
          employeeDeleteBtn.disabled = false;
        });
    });
  }

  const employeeSyncBtn = document.getElementById('employee-sync-btn');
  if (employeeSyncBtn) {
    employeeSyncBtn.addEventListener('click', () => {
      const key = (employeeEditKey.value || '').trim();
      if (!key) {
        showAlert('Користувача не вибрано', 'warning');
        return;
      }
      
      employeeSyncBtn.disabled = true;
      const originalText = employeeSyncBtn.innerHTML;
      employeeSyncBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Синхронізація...';
      
      fetch(`/api/admin/employees/${encodeURIComponent(key)}/sync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          if (!ok) {
            throw new Error(data.error || 'Не вдалося синхронізувати користувача');
          }
          
          const updatedFields = data.updated_fields || [];
          
          // Завжди оновлюємо поля в формі після синхронізації
          const userInfo = data.user_info || {};
          if (userInfo.project !== undefined) document.getElementById('employee-edit-project').value = userInfo.project || '';
          if (userInfo.department !== undefined) document.getElementById('employee-edit-department').value = userInfo.department || '';
          if (userInfo.unit !== undefined) document.getElementById('employee-edit-unit').value = userInfo.unit || '';
          if (userInfo.team !== undefined) document.getElementById('employee-edit-team').value = userInfo.team || '';
          if (userInfo.location !== undefined) document.getElementById('employee-edit-location').value = userInfo.location || '';
          if (userInfo.control_manager !== undefined) {
            const managerSelect = document.getElementById('employee-edit-manager');
            if (managerSelect) {
              managerSelect.value = userInfo.control_manager;
            }
          }
          
          if (updatedFields.length === 0) {
            showAlert('Дані вже актуальні, змін не потрібно', 'info');
          } else {
            showAlert(`Оновлено поля: ${updatedFields.join(', ')}`, 'success');
          }
          
          // Оновлюємо таблицю
          fetchEmployees();
        })
        .catch((error) => showAlert(error.message))
        .finally(() => {
          employeeSyncBtn.disabled = false;
          employeeSyncBtn.innerHTML = originalText;
        });
    });
  }

  // Кнопка "Адаптировать запись" - адаптує дані з Level_Grade.json
  const employeeAdaptBtn = document.getElementById('employee-adapt-btn');
  if (employeeAdaptBtn) {
    employeeAdaptBtn.addEventListener('click', () => {
      const userKey = employeeEditName.value.trim();
      if (!userKey) {
        showAlert('Не вказано користувача для адаптації', 'warning');
        return;
      }

      employeeAdaptBtn.disabled = true;
      const originalText = employeeAdaptBtn.innerHTML;
      employeeAdaptBtn.innerHTML = '<i class="bi bi-hourglass-split"></i> Адаптація...';

      fetch(`/api/admin/employees/${encodeURIComponent(userKey)}/adapt`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          if (!ok) {
            throw new Error(data.error || 'Не вдалося адаптувати дані');
          }

          const updatedFields = data.updated_fields || [];
          
          // Оновлюємо поля в формі
          const userInfo = data.user_info || {};
          if (userInfo.project !== undefined) document.getElementById('employee-edit-project').value = userInfo.project || '';
          if (userInfo.department !== undefined) document.getElementById('employee-edit-department').value = userInfo.department || '';
          if (userInfo.unit !== undefined) document.getElementById('employee-edit-unit').value = userInfo.unit || '';
          if (userInfo.team !== undefined) document.getElementById('employee-edit-team').value = userInfo.team || '';

          if (updatedFields.length === 0) {
            showAlert('Дані вже адаптовані відповідно до Level_Grade.json', 'info');
          } else {
            showAlert(`Адаптовано поля: ${updatedFields.join(', ')}`, 'success');
          }
          
          // Оновлюємо таблицю
          fetchEmployees();
        })
        .catch((error) => showAlert(error.message))
        .finally(() => {
          employeeAdaptBtn.disabled = false;
          employeeAdaptBtn.innerHTML = originalText;
        });
    });
  }

  if (appUserForm) {
    appUserForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const email = document.getElementById('app-user-email').value.trim();
      const name = document.getElementById('app-user-name').value.trim();
      const password = document.getElementById('app-user-password').value;
      const managerFilter = document.getElementById('app-user-managers').value.trim();
      const isAdmin = document.getElementById('app-user-admin').checked;
      const isControlManager = document.getElementById('app-user-control-manager').checked;

      const payload = {
        email,
        name,
        password,
        manager_filter: managerFilter,
        is_admin: isAdmin,
        is_control_manager: isControlManager,
      };

      fetch('/api/admin/app-users', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          if (!ok) {
            throw new Error(data.error || 'Не удалось создать пользователя ');
          }
          showAlert('Пользователь создан', 'success');
          appUserForm.reset();
          fetchAppUsers();
        })
        .catch((error) => showAlert(error.message));
    });
  }

  if (appUsersTable) {
    appUsersTable.addEventListener('click', (event) => {
      const button = event.target.closest('.app-user-edit');
      if (!button || !appUserModal) {
        return;
      }
      const data = JSON.parse(button.dataset.user);
      document.getElementById('app-user-edit-id').value = data.id;
      document.getElementById('app-user-edit-email').value = data.email || '';
      document.getElementById('app-user-edit-name').value = data.name || '';
      document.getElementById('app-user-edit-managers').value = data.manager_filter || '';
      document.getElementById('app-user-edit-password').value = '';
      document.getElementById('app-user-edit-admin').checked = Boolean(data.is_admin);
      document.getElementById('app-user-edit-control-manager').checked = Boolean(data.is_control_manager);
      appUserModal.show();
    });
  }

  if (appUserEditForm) {
    appUserEditForm.addEventListener('submit', (event) => {
      event.preventDefault();
      const userId = document.getElementById('app-user-edit-id').value;
      const email = document.getElementById('app-user-edit-email').value.trim();
      const name = document.getElementById('app-user-edit-name').value.trim();
      const managerFilter = document.getElementById('app-user-edit-managers').value.trim();
      const password = document.getElementById('app-user-edit-password').value;
      const isAdmin = document.getElementById('app-user-edit-admin').checked;
      const isControlManager = document.getElementById('app-user-edit-control-manager').checked;

      const payload = {
        email,
        name,
        manager_filter: managerFilter,
        is_admin: isAdmin,
        is_control_manager: isControlManager,
      };
      if (password) {
        payload.password = password;
      }

      fetch(`/api/admin/app-users/${userId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      })
        .then((response) => response.json().then((data) => ({ ok: response.ok, data })))
        .then(({ ok, data }) => {
          if (!ok) {
            throw new Error(data.error || 'Не удалось обновить пользователя');
          }
          showAlert('Данные пользователя обновлены', 'success');
          if (appUserModal) {
            appUserModal.hide();
          }
          fetchAppUsers();
        })
        .catch((error) => showAlert(error.message));
    });
  }

  // Toggle password visibility
  const togglePasswordBtn = document.getElementById('app-user-edit-toggle-password');
  if (togglePasswordBtn) {
    togglePasswordBtn.addEventListener('click', () => {
      const passwordInput = document.getElementById('app-user-edit-password');
      const icon = togglePasswordBtn.querySelector('i');
      if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        icon.className = 'bi bi-eye-slash';
      } else {
        passwordInput.type = 'password';
        icon.className = 'bi bi-eye';
      }
    });
  }

  // Employee modal filters
  function updateEmployeeSelectedFiltersDisplay() {
    updateFilterDisplay(employeeSelectedFiltersDisplay, selectedEmployeeFilters);
  }

  function renderEmployeeFilterModal() {
    renderFilterCheckboxes(employeeFilterProjectsList, currentEmployeeFilterOptions.projects, selectedEmployeeFilters.projects);
    renderFilterCheckboxes(employeeFilterDepartmentsList, currentEmployeeFilterOptions.departments, selectedEmployeeFilters.departments);
    renderFilterCheckboxes(employeeFilterUnitsList, currentEmployeeFilterOptions.units, selectedEmployeeFilters.units);
    renderFilterCheckboxes(employeeFilterTeamsList, currentEmployeeFilterOptions.teams, selectedEmployeeFilters.teams);
  }

  if (openEmployeeFiltersModalBtn) {
    openEmployeeFiltersModalBtn.addEventListener('click', () => {
      console.log('=== Opening employee filters modal ===');
      console.log('Modal element exists:', !!employeeFiltersModalEl);
      console.log('Modal element:', employeeFiltersModalEl);
      
      renderEmployeeFilterModal();
      
      // Initialize modal if not already done
      if (!employeeFiltersModal && employeeFiltersModalEl) {
        console.log('Initializing new bootstrap Modal...');
        employeeFiltersModal = new bootstrap.Modal(employeeFiltersModalEl);
        console.log('Modal initialized:', !!employeeFiltersModal);
      }
      
      if (employeeFiltersModal) {
        console.log('Calling modal.show()...');
        employeeFiltersModal.show();
        console.log('Modal show() called');
      } else {
        console.error('ERROR: Could not initialize modal');
        alert('Ошибка: не удалось открыть модальное окно');
      }
    });
  }

  if (employeeFilterModalApplyBtn) {
    employeeFilterModalApplyBtn.addEventListener('click', () => {
      // Filters are already in selectedEmployeeFilters Sets, just refresh display and data
      updateEmployeeSelectedFiltersDisplay();
      employeePage = 1;
      fetchEmployees();
    });
  }

  if (employeeFilterModalClearBtn) {
    employeeFilterModalClearBtn.addEventListener('click', () => {
      selectedEmployeeFilters = { projects: new Set(), departments: new Set(), units: new Set(), teams: new Set() };
      renderEmployeeFilterModal();
      updateEmployeeSelectedFiltersDisplay();
    });
  }

  // Event delegation for Ignore/Unignore buttons
  if (employeeTbody) {
    employeeTbody.addEventListener('click', (event) => {
      const ignoreBtn = event.target.closest('.employee-ignore-btn');
      const unignoreBtn = event.target.closest('.employee-unignore-btn');
      
      if (ignoreBtn) {
        const userKey = ignoreBtn.dataset.userKey;
        if (!userKey) return;
        
        if (!confirm('Виключити користувача зі звітів та diff? Користувач більше не буде відображатися в порівняннях.')) {
          return;
        }
        
        ignoreBtn.disabled = true;
        
        fetch(`/api/admin/employees/${encodeURIComponent(userKey)}/ignore`, { method: 'POST' })
          .then((response) => {
            if (!response.ok) {
              throw new Error('Failed to ignore employee');
            }
            return response.json();
          })
          .then((data) => {
            showAlert('success', `Користувача "${data.user_name}" виключено зі звітів`);
            fetchEmployees();
            fetchDiffState();
          })
          .catch((error) => {
            console.error('Error ignoring employee:', error);
            showAlert('danger', 'Помилка виключення користувача');
            ignoreBtn.disabled = false;
          });
      }
      
      if (unignoreBtn) {
        const userKey = unignoreBtn.dataset.userKey;
        if (!userKey) return;
        
        if (!confirm('Повернути користувача в звіти та diff?')) {
          return;
        }
        
        unignoreBtn.disabled = true;
        
        fetch(`/api/admin/employees/${encodeURIComponent(userKey)}/unignore`, { method: 'POST' })
          .then((response) => {
            if (!response.ok) {
              throw new Error('Failed to unignore employee');
            }
            return response.json();
          })
          .then((data) => {
            showAlert('success', `Користувача "${data.user_name}" повернуто в звіти`);
            fetchEmployees();
            fetchDiffState();
          })
          .catch((error) => {
            console.error('Error unignoring employee:', error);
            showAlert('danger', 'Помилка повернення користувача');
            unignoreBtn.disabled = false;
          });
      }
    });
  }

  // Initial load
  fetchEmployees();
  fetchAppUsers();
  fetchDiffState().catch(() => {});
})();
