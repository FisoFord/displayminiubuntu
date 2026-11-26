/* MiniDisplay Web · 4 diseños fijos + fondos + servicios */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

const FPS_OPTIONS = [0.5, 1, 2, 3];

const S = {
  config: null,
  state: null,
  bgs: [],
  presets: {},
  health: null,
  services: null,
  tab: 'design',
  lastPreview: 0,
  designStamp: Date.now(),
  saving: false,
  pendingSave: false,
  saveTimer: null,
  thumbTimer: null,
  svcFilter: '',
  svcState: 'all',
};

/* ------------------------------------------------------------------ utils */
function esc(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function hex6(color) {
  const m = String(color || '').replace('#', '');
  return '#' + (m.length >= 6 ? m.slice(0, 6) : 'ffffff');
}
function fmtBytes(value) {
  if (value == null) return '—';
  let v = Number(value);
  if (!isFinite(v) || v < 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
  return (i === 0 ? Math.round(v) : v.toFixed(1)) + ' ' + units[i];
}
function toast(message, isError = false) {
  const box = $('#toasts');
  const el = document.createElement('div');
  el.className = 'toast' + (isError ? ' err' : '');
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), isError ? 7000 : 3500);
}

async function api(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let msg = res.statusText;
    try { const data = await res.json(); msg = data.error || data.message || msg; } catch (_) {}
    throw new Error(msg);
  }
  const type = res.headers.get('content-type') || '';
  return type.includes('json') ? res.json() : res;
}
const getJSON = (url) => api(url);
const putJSON = (url, body) => api(url, {
  method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
});
const postJSON = (url, body) => api(url, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
});

/* ------------------------------------------------------------------- save */
function scheduleSave() {
  clearTimeout(S.saveTimer);
  S.saveTimer = setTimeout(saveNow, 250);
}
async function saveNow() {
  if (!S.config) return;
  if (S.saving) { S.pendingSave = true; return; }
  S.saving = true;
  try {
    await putJSON('/api/config', S.config);
  } catch (err) {
    toast('No se pudo guardar: ' + err.message, true);
  } finally {
    S.saving = false;
    if (S.pendingSave) { S.pendingSave = false; saveNow(); }
  }
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  try {
    const [config, presets, backgrounds, health] = await Promise.all([
      getJSON('/api/config'), getJSON('/api/presets'),
      getJSON('/api/backgrounds'), getJSON('/api/health'),
    ]);
    S.config = config;
    S.presets = presets;
    S.bgs = backgrounds.items || [];
    S.health = health;
    renderAll();
    await pollState();
    setInterval(pollState, 1000);
    setInterval(() => { if (S.tab === 'services') loadServices(false); }, 4000);
  } catch (err) {
    toast('Error cargando el panel: ' + err.message, true);
  }
}

function renderAll() {
  renderDisplaySettings();
  renderDesigns();
  renderGallery();
  renderBgControls();
}

/* ------------------------------------------------------------------- tabs */
function showTab(name) {
  S.tab = name;
  $$('.tab-btn').forEach((btn) => btn.classList.toggle('active', btn.dataset.tab === name));
  $$('.tab-panel').forEach((panel) => panel.classList.add('hidden'));
  const target = $('#tab-' + name);
  if (target) target.classList.remove('hidden');
  if (name === 'services') { renderSvcCards(); loadServices(true); }
  if (name === 'settings') loadHealth();
}
$$('.tab-btn').forEach((btn) => btn.addEventListener('click', () => showTab(btn.dataset.tab)));

/* ---------------------------------------------------------------- preview */
async function pollState() {
  try {
    const st = await getJSON('/api/state');
    S.state = st;
    if (st.preview_ts && st.preview_ts !== S.lastPreview) {
      S.lastPreview = st.preview_ts;
      $('#preview').src = '/api/preview.png?t=' + encodeURIComponent(st.preview_ts.toFixed(3));
    }
    updateStatus(st);
    if (S.tab === 'services') renderSvcCards();
  } catch (_) { /* servidor reiniciando */ }
}

function updateStatus(st) {
  const d = st.display || {};
  const dot = $('#deviceDot');
  dot.className = 'dot ' + (d.connected ? 'on' : (d.last_error ? 'err' : ''));
  dot.title = d.last_error || '';
  $('#deviceText').textContent = d.connected
    ? 'panel · ' + (d.port || 'conectado')
    : (d.last_error ? 'panel sin conexión' : 'panel desconectado');
  $('#pushText').textContent = d.frames
    ? d.frames + ' frames' + (d.push_ms ? ' · ' + d.push_ms + ' ms' : '')
    : '';
  const stats = st.stats || {};
  if (stats.cpu) {
    $('#previewInfo').textContent =
      (stats.hostname || '') + ' · CPU ' + Number(stats.cpu.percent).toFixed(0) + '%' +
      ' · RAM ' + Number(stats.ram.percent).toFixed(0) + '%';
  }
}

$('#pushBtn').addEventListener('click', async () => {
  try { await postJSON('/api/display/push'); toast('Frame enviado'); }
  catch (err) { toast(err.message, true); }
});

/* ---------------------------------------------------------------- designs */
function renderDesigns() {
  const grid = $('#designGrid');
  if (!grid) return;
  const current = S.config.design;
  grid.innerHTML = Object.entries(S.presets).map(([key, preset]) => `
    <button type="button" class="design-card ${current === key ? 'selected' : ''}" data-design="${esc(key)}">
      <span class="check" aria-hidden="true">✓</span>
      <img src="/api/presets/${encodeURIComponent(key)}/preview.png?v=${S.designStamp}"
           alt="Diseño ${esc(preset.label)}" loading="lazy">
      <span class="dname">${esc(preset.label)}</span>
    </button>`).join('');
  const hint = $('#designHint');
  if (hint) {
    hint.textContent = current === 'custom'
      ? 'La configuración actual no coincide con ninguno de los cuatro diseños. Elige uno para reemplazarla.'
      : 'Elige uno de los cuatro diseños. El fondo, el brillo y las imágenes se ajustan debajo.';
  }
}

function refreshDesignThumbs(delay = 800) {
  clearTimeout(S.thumbTimer);
  S.thumbTimer = setTimeout(() => {
    S.designStamp = Date.now();
    renderDesigns();
  }, delay);
}

$('#designGrid').addEventListener('click', async (event) => {
  const card = event.target.closest('[data-design]');
  if (!card) return;
  const name = card.dataset.design;
  if (!name || S.config.design === name) return;
  try {
    S.config = await postJSON('/api/presets/' + encodeURIComponent(name));
    renderDesigns();
    S.lastPreview = 0;
    if (S.services) renderServices();
    toast('Diseño «' + ((S.presets[name] || {}).label || name) + '» aplicado');
  } catch (err) { toast(err.message, true); }
});

/* --------------------------------------------------------- display config */
function renderDisplaySettings() {
  const d = S.config.display;
  const options = FPS_OPTIONS.map((f) =>
    `<option value="${f}" ${Number(d.fps) === f ? 'selected' : ''}>${f} fps</option>`).join('');
  $('#displaySettings').innerHTML = `
    <label class="fld check wide">
      <input type="checkbox" data-disp="enabled" ${d.enabled ? 'checked' : ''}>
      Enviar frames al panel USB
    </label>
    <label class="fld">
      <span>Brillo <b id="brightVal">${d.brightness}%</b></span>
      <input type="range" min="0" max="100" step="1" data-disp="brightness" value="${d.brightness}">
    </label>
    <label class="fld"><span>Refresco</span>
      <select data-disp="fps">${options}</select>
    </label>
    <p class="hint wide">La revisión A se calienta: mantén el brillo en 20–50 %.</p>`;
}

$('#displaySettings').addEventListener('input', (event) => {
  const field = event.target.dataset.disp;
  if (!field) return;
  let value;
  if (event.target.type === 'checkbox') value = event.target.checked;
  else if (event.target.type === 'range' || event.target.tagName === 'SELECT') value = Number(event.target.value);
  else value = event.target.value;
  S.config.display[field] = value;
  if (field === 'brightness') $('#brightVal').textContent = value + '%';
  scheduleSave();
});

/* -------------------------------------------------------------- backgrounds */
function renderGallery() {
  const selected = new Set(S.config.background.images || []);
  const gallery = $('#bgGallery');
  $('#bgCount').textContent = S.bgs.length
    ? S.bgs.length + ' imagen(es) · ' + selected.size + ' en rotación'
    : 'sin imágenes';
  if (!S.bgs.length) {
    gallery.innerHTML = '<p class="hint">Sube una o varias imágenes para usarlas como fondo decorativo.</p>';
    return;
  }
  gallery.innerHTML = S.bgs.map((item) => `
    <div class="bg-item ${selected.has(item.file) ? 'in' : ''}" data-file="${esc(item.file)}">
      <img src="${esc(item.url)}" loading="lazy" alt="">
      <button class="bg-del" data-del="${esc(item.file)}" title="Eliminar">×</button>
      <label class="bg-meta">
        <input type="checkbox" data-pick="${esc(item.file)}" ${selected.has(item.file) ? 'checked' : ''}>
        <span title="${esc(item.name)}">${esc(item.name)}</span>
      </label>
    </div>`).join('');
}

$('#bgGallery').addEventListener('change', (event) => {
  const file = event.target.dataset.pick;
  if (!file) return;
  const images = S.config.background.images || (S.config.background.images = []);
  const index = images.indexOf(file);
  if (event.target.checked && index < 0) images.push(file);
  if (!event.target.checked && index >= 0) images.splice(index, 1);
  event.target.closest('.bg-item').classList.toggle('in', event.target.checked);
  $('#bgCount').textContent = S.bgs.length + ' imagen(es) · ' + images.length + ' en rotación';
  scheduleSave();
  refreshDesignThumbs();
});

$('#bgGallery').addEventListener('click', async (event) => {
  const file = event.target.dataset.del;
  if (!file) return;
  if (!confirm('¿Eliminar esta imagen del servidor?')) return;
  try {
    await api('/api/backgrounds/' + encodeURIComponent(file), { method: 'DELETE' });
    S.bgs = S.bgs.filter((item) => item.file !== file);
    S.config.background.images = (S.config.background.images || []).filter((f) => f !== file);
    renderGallery();
    refreshDesignThumbs();
    toast('Imagen eliminada');
  } catch (err) { toast(err.message, true); }
});

async function uploadFiles(files) {
  files = Array.from(files || []).filter(Boolean);
  if (!files.length) return;
  const data = new FormData();
  files.forEach((file) => data.append('files', file));
  try {
    toast('Subiendo ' + files.length + ' imagen(es)…');
    const res = await api('/api/backgrounds', { method: 'POST', body: data });
    if (res.items && res.items.length) {
      S.bgs = S.bgs.concat(res.items);
      res.items.forEach((item) => {
        if (!S.config.background.images.includes(item.file)) S.config.background.images.push(item.file);
      });
      renderGallery();
      refreshDesignThumbs(300);
      toast(res.items.length + ' imagen(es) añadida(s)');
    }
    if (res.errors && res.errors.length) toast(res.errors.join(' · '), true);
  } catch (err) { toast('Error subiendo: ' + err.message, true); }
}

$('#bgUpload').addEventListener('change', (event) => {
  uploadFiles(event.target.files);
  event.target.value = '';
});

const dropZone = $('#dropZone');
['dragenter', 'dragover'].forEach((evt) => dropZone.addEventListener(evt, (event) => {
  event.preventDefault(); dropZone.classList.add('drag');
}));
['dragleave', 'drop'].forEach((evt) => dropZone.addEventListener(evt, (event) => {
  event.preventDefault(); dropZone.classList.remove('drag');
}));
dropZone.addEventListener('drop', (event) => uploadFiles(event.dataTransfer.files));

function renderBgControls() {
  const b = S.config.background;
  const pct = (v) => Math.round(Number(v) * 100);
  $('#bgControls').innerHTML = `
    <label class="fld"><span>Opacidad <b id="bgOpacityVal">${pct(b.opacity)}%</b></span>
      <input type="range" min="0" max="100" data-bg="opacity" data-scale="100" value="${pct(b.opacity)}"></label>
    <label class="fld"><span>Tinte <b id="bgTintVal">${pct(b.tint_strength)}%</b></span>
      <input type="range" min="0" max="100" data-bg="tint_strength" data-scale="100" value="${pct(b.tint_strength)}"></label>
    <label class="fld"><span>Color de tinte</span>
      <input type="color" data-bg="tint" value="${hex6(b.tint)}"></label>
    <label class="fld"><span>Ajuste</span>
      <select data-bg="fit">
        <option value="cover" ${b.fit === 'cover' ? 'selected' : ''}>Cubrir (recorta)</option>
        <option value="contain" ${b.fit === 'contain' ? 'selected' : ''}>Contener (borde)</option>
        <option value="stretch" ${b.fit === 'stretch' ? 'selected' : ''}>Estirar</option>
      </select></label>
    <label class="fld"><span>Desenfoque <b id="bgBlurVal">${Number(b.blur).toFixed(1)}</b></span>
      <input type="range" min="0" max="20" step="0.5" data-bg="blur" value="${b.blur}"></label>
    <label class="fld"><span>Degradado inferior <b id="bgShadeVal">${pct(b.shade)}%</b></span>
      <input type="range" min="0" max="100" data-bg="shade" data-scale="100" value="${pct(b.shade)}"></label>
    <label class="fld"><span>Rotar cada (segundos)</span>
      <input type="number" min="0" max="86400" data-bg="rotate_seconds" value="${b.rotate_seconds}"></label>
    <label class="fld"><span>Color base</span>
      <input type="color" data-bg="base_color" value="${hex6(b.base_color)}"></label>`;
}

$('#bgControls').addEventListener('input', (event) => {
  const field = event.target.dataset.bg;
  if (!field) return;
  let value = event.target.value;
  const scale = Number(event.target.dataset.scale || 1);
  if (event.target.type === 'range' || event.target.type === 'number') value = Number(value) / scale;
  S.config.background[field] = value;
  const labels = {
    opacity: ['#bgOpacityVal', 'opacity'], tint_strength: ['#bgTintVal', 'tint_strength'],
    shade: ['#bgShadeVal', 'shade'], blur: ['#bgBlurVal', 'blur'],
  };
  if (labels[field]) {
    const [selector] = labels[field];
    const node = $(selector);
    if (node) node.textContent = field === 'blur' ? Number(value).toFixed(1) : Math.round(value * 100) + '%';
  }
  scheduleSave();
  refreshDesignThumbs(900);
});

/* ---------------------------------------------------------------- services */
async function loadServices(force) {
  try {
    S.services = await getJSON('/api/services' + (force ? '?force=1' : ''));
    renderServices();
  } catch (err) {
    $('#svcNote').classList.remove('hidden');
    $('#svcNote').textContent = 'No se pudo leer systemd/docker: ' + err.message;
  }
}

function servicesWidget() {
  return S.config.widgets.find((w) => w.type === 'services');
}

function renderSvcCards() {
  const stats = S.state && S.state.stats;
  if (!stats || !stats.cpu) return;
  const cards = [
    ['CPU', Number(stats.cpu.percent).toFixed(0) + '%', (stats.cpu.count || '?') + ' hilos'],
    ['RAM', Number(stats.ram.percent).toFixed(0) + '%', stats.ram.used_str + ' / ' + stats.ram.total_str],
    ['Disco', Number(stats.disk.percent).toFixed(0) + '%', stats.disk.used_str + ' / ' + stats.disk.total_str],
    ['Red ↓', stats.net.down_str, 'Red ↑ ' + stats.net.up_str],
    ['Uptime', stats.uptime_str, stats.hostname],
    ['Load', Number(stats.cpu.load).toFixed(2), (stats.cpu.count || '?') + ' núcleos'],
  ];
  $('#svcCards').innerHTML = cards.map(([k, v, s]) =>
    `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join('');
}

function renderServices() {
  const data = S.services || { systemd: [], docker: [] };
  const units = data.systemd || [];
  const docker = data.docker || [];
  const note = $('#svcNote');

  const messages = [];
  if (data.systemd_error && !units.length) messages.push('systemd: ' + data.systemd_error);
  if (data.docker_error && !docker.length) messages.push('docker: ' + data.docker_error);
  if (data.actions_allowed === false) {
    messages.push('Acciones deshabilitadas: instala los permisos con “webapp/install.sh --actions”.');
  }
  const widget = servicesWidget();
  if (!widget) {
    messages.push('El diseño actual no incluye la lista de servicios en el panel (elige “Proxmox”).');
  }
  if (messages.length) { note.classList.remove('hidden'); note.textContent = messages.join(' · '); }
  else note.classList.add('hidden');

  const picked = new Set(widget ? (widget.units || []) : []);
  const canPick = !!widget;
  const filter = S.svcFilter.toLowerCase();
  const stateFilter = S.svcState;
  const filtered = units.filter((u) => {
    if (stateFilter !== 'all' && u.active !== stateFilter) return false;
    if (!filter) return true;
    return u.unit.toLowerCase().includes(filter) || (u.description || '').toLowerCase().includes(filter);
  });

  $('#svcCount').textContent = filtered.length + ' de ' + units.length + ' unidades';
  $('#svcBody').innerHTML = filtered.map((u) => {
    const allowed = data.actions_allowed;
    const actions = [];
    if (u.active === 'active') {
      actions.push(actionBtn('restart', u.unit, 'Reiniciar', allowed, 'ghost'));
      actions.push(actionBtn('stop', u.unit, 'Detener', allowed, 'danger'));
    } else {
      actions.push(actionBtn('start', u.unit, 'Arrancar', allowed, 'primary'));
    }
    return `<tr>
      <td><input class="pick" type="checkbox" data-pick-unit="${esc(u.unit)}"
        ${picked.has(u.unit) ? 'checked' : ''} ${canPick ? '' : 'disabled'}></td>
      <td><code>${esc(u.unit)}</code><div class="desc">${esc(u.description || '')}</div></td>
      <td><span class="pill ${esc(u.active)}">${esc(u.active)}</span></td>
      <td class="num">${u.cpu != null ? u.cpu + '%' : '—'}</td>
      <td class="num">${fmtBytes(u.memory)}</td>
      <td class="num">${esc(shortSince(u.since))}</td>
      <td class="act">${actions.join('')}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="7" class="muted">Sin resultados.</td></tr>`;

  $('#dockerCount').textContent = docker.length + ' contenedor(es)';
  $('#dockerBody').innerHTML = docker.map((c) => {
    const allowed = data.actions_allowed;
    const actions = c.state === 'running'
      ? actionBtn('restart', c.name, 'Reiniciar', allowed, 'ghost', 'docker') +
        actionBtn('stop', c.name, 'Detener', allowed, 'danger', 'docker')
      : actionBtn('start', c.name, 'Arrancar', allowed, 'primary', 'docker');
    return `<tr>
      <td><code>${esc(c.name)}</code></td>
      <td class="muted">${esc(c.image)}</td>
      <td><span class="pill ${c.state === 'running' ? 'active' : 'inactive'}">${esc(c.status || c.state)}</span></td>
      <td class="act">${actions}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="4" class="muted">Docker no disponible o sin contenedores.</td></tr>`;
}

function shortSince(value) {
  if (!value) return '—';
  return String(value).replace(/^\w{3}\s+/, '').replace(/:\d{2}\s+[+-]\d{4}$/, '');
}

function actionBtn(action, name, label, allowed, style, scope = 'systemd') {
  return `<button class="btn icon ${style}" data-svc-action="${action}" data-svc-name="${esc(name)}"
    data-svc-scope="${scope}" ${allowed ? '' : 'disabled title="Sin permisos"'}>${label}</button>`;
}

$('#svcBody').addEventListener('change', (event) => {
  const unit = event.target.dataset.pickUnit;
  if (!unit) return;
  const widget = servicesWidget();
  if (!widget) {
    event.target.checked = false;
    toast('El diseño actual no incluye lista de servicios. Elige el diseño Proxmox.', true);
    return;
  }
  const set = new Set(widget.units || []);
  if (event.target.checked) set.add(unit); else set.delete(unit);
  widget.units = Array.from(set);
  scheduleSave();
});

async function doServiceAction(scope, name, action) {
  const verb = { start: 'arrancar', stop: 'detener', restart: 'reiniciar' }[action] || action;
  if (!confirm(`¿${verb} ${name}?`)) return;
  try {
    const res = await postJSON('/api/services/action', { scope, name, action });
    toast(res.message || 'Hecho', !res.ok);
    loadServices(true);
  } catch (err) { toast(err.message, true); }
}

document.addEventListener('click', (event) => {
  const btn = event.target.closest('[data-svc-action]');
  if (!btn) return;
  doServiceAction(btn.dataset.svcScope, btn.dataset.svcName, btn.dataset.svcAction);
});

$('#svcSearch').addEventListener('input', (event) => {
  S.svcFilter = event.target.value;
  renderServices();
});
$('#svcState').addEventListener('change', (event) => {
  S.svcState = event.target.value;
  renderServices();
});
$('#svcRefresh').addEventListener('click', () => loadServices(true));

/* ---------------------------------------------------------------- settings */
async function loadHealth() {
  try {
    const health = await getJSON('/api/health');
    S.health = health;
    const device = health.device || {};
    const rows = [
      ['Versión', health.version],
      ['Host', health.host || '—'],
      ['Datos', health.data_dir],
      ['Panel', device.connected ? (device.port || 'conectado') : (device.last_error || 'desconectado')],
      ['Frames enviados', device.frames != null ? device.frames : '—'],
      ['Último envío', device.last_push ? new Date(device.last_push * 1000).toLocaleString() : '—'],
      ['systemd', health.systemd ? 'disponible' : 'no disponible'],
      ['Docker', health.docker ? 'disponible' : 'no instalado'],
      ['Acciones', health.actions_allowed ? 'permitidas' : 'solo lectura'],
      ['Imágenes', health.backgrounds],
    ];
    $('#healthBox').innerHTML = rows.map(([k, v]) =>
      `<div class="k">${esc(k)}</div><div><code>${esc(v)}</code></div>`).join('');
  } catch (err) { toast(err.message, true); }
}

$('#exportBtn').addEventListener('click', () => {
  const blob = new Blob([JSON.stringify(S.config, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'minidisplay-config.json'; a.click();
  URL.revokeObjectURL(url);
});

$('#importFile').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const parsed = JSON.parse(await file.text());
    S.config = await putJSON('/api/config', parsed);
    renderAll();
    toast('Configuración importada');
  } catch (err) { toast('Config inválida: ' + err.message, true); }
  event.target.value = '';
});

$('#logsBtn').addEventListener('click', async () => {
  try {
    const data = await getJSON('/api/logs?lines=150');
    const box = $('#logsBox');
    box.classList.remove('hidden');
    box.textContent = (data.lines || []).join('\n') || '(vacío)';
  } catch (err) { toast(err.message, true); }
});

/* -------------------------------------------------------------------- init */
boot();
