async function schedulerLoadJobs() {
  const tableBody = document.querySelector('#scheduler-table tbody');
  if (!tableBody) {
    return;
  }
  tableBody.innerHTML = '<tr><td colspan="5" class="text-muted text-center py-3">Загрузка…</td></tr>';
  try {
    const res = await fetch('/api/admin/scheduler/jobs');
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'Не удалось получить список задач');
    }
    const jobs = data.jobs || [];
    if (!jobs.length) {
      tableBody.innerHTML = '<tr><td colspan="5" class="text-muted text-center py-3">Нет задач</td></tr>';
      return;
    }
    tableBody.innerHTML = '';
    jobs.forEach((job) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><code>${job.id}</code></td>
        <td>${job.name}</td>
        <td><small>${job.trigger}</small></td>
        <td>${job.next_run_time || '—'}</td>
        <td class="d-flex flex-wrap gap-1">
          <button class="btn btn-sm btn-success" data-action="run" data-id="${job.id}">Run now</button>
          <button class="btn btn-sm btn-warning" data-action="pause" data-id="${job.id}">Pause</button>
          <button class="btn btn-sm btn-info" data-action="resume" data-id="${job.id}">Resume</button>
          <button class="btn btn-sm btn-danger" data-action="remove" data-id="${job.id}">Remove</button>
        </td>
      `;
      tableBody.appendChild(tr);
    });
  } catch (error) {
    tableBody.innerHTML = `<tr><td colspan="5" class="text-danger text-center py-3">${error.message}</td></tr>`;
  }
}

async function schedulerPost(url, payload) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload ? JSON.stringify(payload) : null,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || 'Ошибка запроса');
  }
  return data;
}

document.addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) {
    return;
  }
  const action = button.dataset.action;
  const jobId = button.dataset.id;
  if (!jobId || !action) {
    return;
  }
  button.disabled = true;
  try {
    await schedulerPost(`/api/admin/scheduler/jobs/${encodeURIComponent(jobId)}/${action}`);
    await schedulerLoadJobs();
  } catch (error) {
    window.alert(error.message);
  } finally {
    button.disabled = false;
  }
});

document.getElementById('scheduler-refresh')?.addEventListener('click', () => {
  schedulerLoadJobs();
});

document.getElementById('scheduler-reschedule')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const formData = new FormData(form);
  const jobId = formData.get('job_id');
  if (!jobId) {
    return;
  }
  const payload = {};
  ['minute', 'hour', 'day', 'month', 'day_of_week'].forEach((field) => {
    const value = (formData.get(field) || '').toString().trim();
    if (value) {
      payload[field] = value;
    }
  });
  try {
    await schedulerPost(`/api/admin/scheduler/jobs/${encodeURIComponent(jobId)}/reschedule`, payload);
    form.reset();
    await schedulerLoadJobs();
  } catch (error) {
    window.alert(error.message);
  }
});

document.addEventListener('DOMContentLoaded', () => {
  schedulerLoadJobs();
});
