/* ============================================================
   Orchestrator UI — core JavaScript
   API client, CRUD page builder, toast notifications, helpers
   ============================================================ */

// ---- API Client ----
const API = {
  get token() { return localStorage.getItem('auth_token'); },

  async request(method, path, body) {
    const opts = { method, headers: {} };
    if (this.token) opts.headers['Authorization'] = 'Bearer ' + this.token;
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(path, opts);
    if (resp.status === 401) {
      localStorage.removeItem('auth_token');
      window.location.href = '/login';
      return;
    }
    if (resp.status === 204) return null;
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || JSON.stringify(err));
    }
    return resp.json();
  },

  get(p)    { return API.request('GET', p); },
  post(p,b) { return API.request('POST', p, b); },
  put(p,b)  { return API.request('PUT', p, b); },
  del(p)    { return API.request('DELETE', p); },
};

// ---- Logout ----
function doLogout() {
  localStorage.removeItem('auth_token');
  window.location.href = '/login';
}

// ---- Sidebar toggle ----
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('btn-toggle-sidebar');
  if (btn) {
    btn.addEventListener('click', () => {
      document.getElementById('sidebar').classList.toggle('collapsed');
    });
  }
  // Redirect to login if no token (except on login page)
  if (!API.token && !window.location.pathname.startsWith('/login')) {
    window.location.href = '/login';
  }
});

// ---- Toast Notifications ----
function showToast(message, type) {
  type = type || 'success';
  const c = document.getElementById('toast-container');
  if (!c) return;
  const t = document.createElement('div');
  t.className = 'toast align-items-center text-bg-' + type + ' border-0 show';
  t.setAttribute('role', 'alert');
  t.innerHTML = '<div class="d-flex"><div class="toast-body">' + message +
    '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
  c.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

// ---- Format helpers ----
function fmtDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString();
}
function fmtBool(v) { return v ? 'Yes' : 'No'; }
function fmtJson(v) { return v != null ? JSON.stringify(v) : ''; }
function escHtml(str) {
  if (str == null) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ---- State badge helper ----
function stateBadge(state) {
  return '<span class="badge badge-state state-' + state + '">' + state.replace(/_/g,' ') + '</span>';
}
function execBadge(status) {
  return '<span class="badge exec-' + status + '">' + status + '</span>';
}

// ---- CPU Range Bar ----
function cpuRangeBar(min, max) {
  return '<div class="cpu-range-bar"><div class="cpu-range-fill" style="left:' + min +
    '%;width:' + (max - min) + '%"></div></div><small class="text-muted">' +
    min + '% - ' + max + '%</small>';
}

// ============================================================
// Generic CRUD Page Builder
// ============================================================
//
// config = {
//   entityName: 'Labs',
//   apiPath: '/api/admin/labs',
//   idField: 'id',            // default 'id'
//   columns: [
//     { key: 'id', label: 'ID' },
//     { key: 'name', label: 'Name' },
//     { key: 'created_at', label: 'Created', type: 'date' },
//   ],
//   fields: [
//     { key: 'name', label: 'Name', type: 'text', required: true },
//     { key: 'count', label: 'Count', type: 'number' },
//     { key: 'kind', label: 'Kind', type: 'select', options: ['a','b'] },
//     { key: 'active', label: 'Active', type: 'checkbox' },
//     { key: 'desc', label: 'Description', type: 'textarea' },
//     { key: 'ref', label: 'Provider Ref', type: 'json' },
//   ],
//   deleteApiPath: null,       // if different from apiPath/{id}
//   onAfterLoad: null,         // callback(items) after data loads
//   hideCreate: false,
//   hideDelete: false,
//   hideEdit: false,
// }

let _crudConfig = null;
let _crudModal = null;
let _confirmModal = null;
let _crudEditId = null;
let _crudData = [];

function initCrudPage(config) {
  _crudConfig = config;
  config.idField = config.idField || 'id';
  _crudModal = new bootstrap.Modal(document.getElementById('crud-modal'));
  _confirmModal = new bootstrap.Modal(document.getElementById('confirm-modal'));

  // Create button
  const createBtn = document.getElementById('btn-create');
  if (createBtn && !config.hideCreate) {
    createBtn.addEventListener('click', () => openCreateModal());
    createBtn.classList.remove('d-none');
  }

  // Save button
  document.getElementById('crud-modal-save').addEventListener('click', () => saveCrudForm());

  // Load data
  loadCrudData();
}

async function loadCrudData() {
  try {
    _crudData = await API.get(_crudConfig.apiPath);
    renderCrudTable(_crudData);
    if (_crudConfig.onAfterLoad) _crudConfig.onAfterLoad(_crudData);
  } catch (e) {
    showToast('Failed to load data: ' + e.message, 'danger');
  }
}

function renderCrudTable(items) {
  const tbody = document.getElementById('crud-table-body');
  if (!tbody) return;
  const cfg = _crudConfig;

  if (items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="' + (cfg.columns.length + 1) +
      '" class="text-center text-muted py-4">No records found</td></tr>';
    return;
  }

  tbody.innerHTML = items.map(item => {
    const cells = cfg.columns.map(col => {
      let val = item[col.key];
      if (col.render) return '<td>' + col.render(val, item) + '</td>';
      if (col.type === 'date') val = fmtDate(val);
      else if (col.type === 'bool') val = fmtBool(val);
      else if (col.type === 'json') val = '<code class="small">' + escHtml(fmtJson(val)) + '</code>';
      else if (col.type === 'badge') val = stateBadge(val);
      else val = escHtml(val);
      return '<td>' + (val ?? '') + '</td>';
    }).join('');

    let actions = '<td class="text-nowrap">';
    if (!cfg.hideEdit) {
      actions += '<button class="btn btn-sm btn-outline-primary me-1" onclick="openEditModal(' +
        item[cfg.idField] + ')" title="Edit"><i class="bi bi-pencil"></i></button>';
    }
    if (!cfg.hideDelete) {
      actions += '<button class="btn btn-sm btn-outline-danger" onclick="confirmDelete(' +
        item[cfg.idField] + ')" title="Delete"><i class="bi bi-trash"></i></button>';
    }
    actions += '</td>';
    return '<tr>' + cells + actions + '</tr>';
  }).join('');
}

function buildFormHtml(fields, item) {
  return fields.map(f => {
    const val = item ? (item[f.key] ?? '') : (f.default ?? '');
    const req = f.required ? ' required' : '';
    const id = 'field-' + f.key;
    let input = '';

    if (f.type === 'select') {
      const opts = (f.options || []).map(o => {
        const sel = (String(val) === String(o)) ? ' selected' : '';
        return '<option value="' + o + '"' + sel + '>' + o + '</option>';
      }).join('');
      input = '<select class="form-select" id="' + id + '"' + req + '>' +
        '<option value="">-- Select --</option>' + opts + '</select>';
    } else if (f.type === 'checkbox') {
      const chk = val ? ' checked' : '';
      input = '<div class="form-check mt-2"><input class="form-check-input" type="checkbox" id="' +
        id + '"' + chk + '><label class="form-check-label" for="' + id + '">' + escHtml(f.label) + '</label></div>';
      return '<div class="mb-3">' + input + '</div>';
    } else if (f.type === 'textarea') {
      input = '<textarea class="form-control" id="' + id + '" rows="2"' + req + '>' +
        escHtml(val) + '</textarea>';
    } else if (f.type === 'json') {
      const jv = (typeof val === 'object' && val !== null) ? JSON.stringify(val, null, 2) : (val || '{}');
      input = '<textarea class="form-control json-field" id="' + id + '" rows="3"' + req + '>' +
        escHtml(jv) + '</textarea>';
    } else if (f.type === 'json-array') {
      const jv = Array.isArray(val) ? JSON.stringify(val) : (val || '[]');
      input = '<input class="form-control json-field" id="' + id + '" value="' + escHtml(jv) + '"' + req + '>';
    } else if (f.type === 'password') {
      input = '<input type="password" class="form-control" id="' + id + '"' + req + '>';
    } else {
      const t = f.type || 'text';
      const step = (t === 'number' && f.step) ? ' step="' + f.step + '"' : '';
      input = '<input type="' + t + '" class="form-control" id="' + id + '" value="' +
        escHtml(val) + '"' + req + step + '>';
    }

    return '<div class="mb-3"><label class="form-label" for="' + id + '">' +
      escHtml(f.label) + (f.required ? ' <span class="text-danger">*</span>' : '') +
      '</label>' + input + '</div>';
  }).join('');
}

function openCreateModal() {
  _crudEditId = null;
  document.getElementById('crud-modal-title').textContent = 'Create ' + _crudConfig.entityName;
  document.getElementById('crud-modal-body').innerHTML = buildFormHtml(_crudConfig.fields, null);
  _crudModal.show();
}

function openEditModal(id) {
  _crudEditId = id;
  const item = _crudData.find(i => i[_crudConfig.idField] === id);
  if (!item) return;
  document.getElementById('crud-modal-title').textContent = 'Edit ' + _crudConfig.entityName;
  // For edit, exclude password-type fields unless they have editInclude flag
  const editFields = _crudConfig.fields.filter(f => f.type !== 'password' || f.editInclude);
  document.getElementById('crud-modal-body').innerHTML = buildFormHtml(editFields, item);
  _crudModal.show();
}

function readFormValues(fields) {
  const data = {};
  fields.forEach(f => {
    const el = document.getElementById('field-' + f.key);
    if (!el) return;
    if (f.type === 'checkbox') {
      data[f.key] = el.checked;
    } else if (f.type === 'number') {
      const v = el.value.trim();
      if (v !== '') data[f.key] = f.step ? parseFloat(v) : parseInt(v, 10);
    } else if (f.type === 'json') {
      try { data[f.key] = JSON.parse(el.value); } catch { data[f.key] = {}; }
    } else if (f.type === 'json-array') {
      try { data[f.key] = JSON.parse(el.value); } catch { data[f.key] = []; }
    } else {
      const v = el.value.trim();
      if (v !== '' || f.required) data[f.key] = v || null;
    }
  });
  return data;
}

async function saveCrudForm() {
  const cfg = _crudConfig;
  const isEdit = _crudEditId !== null;
  const fields = isEdit ? cfg.fields.filter(f => f.type !== 'password' || f.editInclude) : cfg.fields;
  const data = readFormValues(fields);

  try {
    if (isEdit) {
      await API.put(cfg.apiPath + '/' + _crudEditId, data);
      showToast(cfg.entityName + ' updated');
    } else {
      await API.post(cfg.apiPath, data);
      showToast(cfg.entityName + ' created');
    }
    _crudModal.hide();
    loadCrudData();
  } catch (e) {
    showToast('Error: ' + e.message, 'danger');
  }
}

function confirmDelete(id) {
  const btn = document.getElementById('confirm-modal-ok');
  // Remove old listener by replacing element
  const newBtn = btn.cloneNode(true);
  btn.parentNode.replaceChild(newBtn, btn);
  newBtn.addEventListener('click', async () => {
    try {
      const path = _crudConfig.deleteApiPath
        ? _crudConfig.deleteApiPath(id)
        : _crudConfig.apiPath + '/' + id;
      await API.del(path);
      showToast(_crudConfig.entityName + ' deleted');
      _confirmModal.hide();
      loadCrudData();
    } catch (e) {
      showToast('Error: ' + e.message, 'danger');
    }
  });
  _confirmModal.show();
}
