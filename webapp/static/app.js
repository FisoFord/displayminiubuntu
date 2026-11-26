/* MiniDisplay Web · 4 diseños fijos + fondos + servicios */
'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

const FPS_OPTIONS = [0.5, 1, 2, 3];

const DEMO_SERVICES = {
  systemd: [
    { unit: 'nginx.service', description: 'A high performance web server and a reverse proxy server', active: 'active', sub: 'running', cpu: 0.4, memory: 52428800, since: 'Wed 2026-11-25 09:12:00 -03' },
    { unit: 'postgresql.service', description: 'PostgreSQL RDBMS', active: 'active', sub: 'running', cpu: 1.2, memory: 268435456, since: 'Wed 2026-11-25 09:12:03 -03' },
    { unit: 'docker.service', description: 'Docker Application Container Engine', active: 'active', sub: 'running', cpu: 2.8, memory: 104857600, since: 'Wed 2026-11-25 09:12:05 -03' },
    { unit: 'backup.service', description: 'Nightly backup job', active: 'failed', sub: 'failed', cpu: null, memory: null, since: 'Wed 2026-11-25 03:00:00 -03' },
    { unit: 'ssh.service', description: 'OpenBSD Secure Shell server', active: 'active', sub: 'running', cpu: 0.1, memory: 8388608, since: 'Wed 2026-11-25 09:12:01 -03' },
  ],
  docker: [
    { name: 'nextcloud', image: 'nextcloud:apache', state: 'running', status: 'Up 3 days', ports: '8081/tcp' },
    { name: 'plex', image: 'plexinc/pms-docker', state: 'running', status: 'Up 3 days', ports: '32400/tcp' },
    { name: 'watchtower', image: 'containrrr/watchtower', state: 'exited', status: 'Exited (0) 2 hours ago', ports: '' },
    { name: 'redis-cache', image: 'redis:7-alpine', state: 'running', status: 'Up 5 days', ports: '6379/tcp' },
  ],
  systemd_error: '',
  docker_error: '',
  actions_allowed: true,
  generated: 0,
};

const DEMO_STATS = {
  hostname: 'ubuntu-server',
  cpu: { percent: 34, count: 8, load: 0.62 },
  ram: { percent: 58, used_str: '9.7 GB', total_str: '16.7 GB' },
  disk: { percent: 61, used_str: '98 GB', total_str: '160 GB' },
  net: { down_str: '1.2 MB/s', up_str: '180 KB/s' },
  gpu: { name: 'NVIDIA GeForce RTX 3060', percent: 18, temp: 55,
         memory_used_str: '2.1 GB', memory_total_str: '12 GB' },
  uptime_str: '8d 3h',
};

const S = {
  config: null,
  state: null,
  bgs: [],
  presets: {},
  health: null,
  services: null,
  demo: false,
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
    toast(t('toast.saveError', { error: err.message }), true);
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
    S.demo = new URLSearchParams(location.search).has('demo');
    if (S.demo) S.services = DEMO_SERVICES;
    applyStaticTranslations();
    buildLangSelect();
    renderAll();
    await pollState();
    setInterval(pollState, 1000);
    setInterval(() => { if (S.tab === 'services') loadServices(false); }, 4000);
    const initial = location.hash.replace('#', '');
    if (['design', 'services', 'settings'].includes(initial)) showTab(initial);
    $('#langSelect').addEventListener('change', onLanguageChange);
  } catch (err) {
    toast(t('toast.loadError', { error: err.message }), true);
  }
}

function onLanguageChange(event) {
  if (!setLang(event.target.value)) return;
  buildLangSelect();
  renderAll();
  renderSvcCards();
  if (S.services) renderServices();
  if (S.tab === 'settings') loadHealth();
  if (S.state) updateStatus(S.state);
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
  if (location.hash !== '#' + name) {
    history.replaceState(null, '', '#' + name);
  }
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
    ? t('status.panel', { port: d.port || '' })
    : (d.last_error ? t('status.offline') : t('status.disconnected'));
  $('#pushText').textContent = d.frames
    ? (d.push_ms
      ? t('status.frames', { frames: d.frames, ms: d.push_ms })
      : t('status.framesShort', { frames: d.frames }))
    : '';
  const stats = (S.demo ? DEMO_STATS : (st.stats || {}));
  if (stats.cpu) {
    $('#previewInfo').textContent =
      (stats.hostname || '') + ' · CPU ' + Number(stats.cpu.percent).toFixed(0) + '%' +
      ' · RAM ' + Number(stats.ram.percent).toFixed(0) + '%';
  }
}

$('#pushBtn').addEventListener('click', async () => {
  try { await postJSON('/api/display/push'); toast(t('toast.push')); }
  catch (err) { toast(err.message, true); }
});

/* ---------------------------------------------------------------- designs */
function renderDesigns() {
  const grid = $('#designGrid');
  if (!grid) return;
  const current = S.config.design;
  grid.innerHTML = Object.entries(S.presets).map(([key, preset]) => {
    const label = t('design.' + key);
    return `
    <button type="button" class="design-card ${current === key ? 'selected' : ''}" data-design="${esc(key)}">
      <span class="check" aria-hidden="true">✓</span>
      <img src="/api/presets/${encodeURIComponent(key)}/preview.png?v=${S.designStamp}"
           alt="${esc(label)}" loading="lazy">
      <span class="dname">${esc(label)}</span>
    </button>`;
  }).join('');
  const hint = $('#designHint');
  if (hint) {
    hint.textContent = current === 'custom' ? t('design.customHint') : t('design.hint');
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
    toast(t('design.applied', { name: t('design.' + name) }));
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
      ${t('display.enabled')}
    </label>
    <label class="fld">
      <span>${t('display.brightness')} <b id="brightVal">${d.brightness}%</b></span>
      <input type="range" min="0" max="100" step="1" data-disp="brightness" value="${d.brightness}">
    </label>
    <label class="fld"><span>${t('display.fps')}</span>
      <select data-disp="fps">${options}</select>
    </label>
    <p class="hint wide">${t('display.hint')}</p>`;
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
    ? t('bg.count', { total: S.bgs.length, selected: selected.size })
    : t('bg.none');
  if (!S.bgs.length) {
    gallery.innerHTML = `<p class="hint">${t('bg.empty')}</p>`;
    return;
  }
  gallery.innerHTML = S.bgs.map((item) => `
    <div class="bg-item ${selected.has(item.file) ? 'in' : ''}" data-file="${esc(item.file)}">
      <img src="${esc(item.url)}" loading="lazy" alt="">
      <button class="bg-del" data-del="${esc(item.file)}" title="${esc(t('bg.delete'))}">×</button>
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
  $('#bgCount').textContent = t('bg.count', { total: S.bgs.length, selected: images.length });
  scheduleSave();
  refreshDesignThumbs();
});

$('#bgGallery').addEventListener('click', async (event) => {
  const file = event.target.dataset.del;
  if (!file) return;
  if (!confirm(t('bg.deleteConfirm'))) return;
  try {
    await api('/api/backgrounds/' + encodeURIComponent(file), { method: 'DELETE' });
    S.bgs = S.bgs.filter((item) => item.file !== file);
    S.config.background.images = (S.config.background.images || []).filter((f) => f !== file);
    renderGallery();
    refreshDesignThumbs();
    toast(t('bg.deleted'));
  } catch (err) { toast(err.message, true); }
});

async function uploadFiles(files) {
  files = Array.from(files || []).filter(Boolean);
  if (!files.length) return;
  const data = new FormData();
  files.forEach((file) => data.append('files', file));
  try {
    toast(t('bg.uploading', { count: files.length }));
    const res = await api('/api/backgrounds', { method: 'POST', body: data });
    if (res.items && res.items.length) {
      S.bgs = S.bgs.concat(res.items);
      res.items.forEach((item) => {
        if (!S.config.background.images.includes(item.file)) S.config.background.images.push(item.file);
      });
      renderGallery();
      refreshDesignThumbs(300);
      toast(t('bg.uploaded', { count: res.items.length }));
    }
    if (res.errors && res.errors.length) toast(res.errors.join(' · '), true);
  } catch (err) { toast(t('bg.uploadError', { error: err.message }), true); }
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
    <label class="fld"><span>${t('bg.opacity')} <b id="bgOpacityVal">${pct(b.opacity)}%</b></span>
      <input type="range" min="0" max="100" data-bg="opacity" data-scale="100" value="${pct(b.opacity)}"></label>
    <label class="fld"><span>${t('bg.tintStrength')} <b id="bgTintVal">${pct(b.tint_strength)}%</b></span>
      <input type="range" min="0" max="100" data-bg="tint_strength" data-scale="100" value="${pct(b.tint_strength)}"></label>
    <label class="fld"><span>${t('bg.tintColor')}</span>
      <input type="color" data-bg="tint" value="${hex6(b.tint)}"></label>
    <label class="fld"><span>${t('bg.fit')}</span>
      <select data-bg="fit">
        <option value="cover" ${b.fit === 'cover' ? 'selected' : ''}>${t('bg.fitCover')}</option>
        <option value="contain" ${b.fit === 'contain' ? 'selected' : ''}>${t('bg.fitContain')}</option>
        <option value="stretch" ${b.fit === 'stretch' ? 'selected' : ''}>${t('bg.fitStretch')}</option>
      </select></label>
    <label class="fld"><span>${t('bg.blur')} <b id="bgBlurVal">${Number(b.blur).toFixed(1)}</b></span>
      <input type="range" min="0" max="20" step="0.5" data-bg="blur" value="${b.blur}"></label>
    <label class="fld"><span>${t('bg.shade')} <b id="bgShadeVal">${pct(b.shade)}%</b></span>
      <input type="range" min="0" max="100" data-bg="shade" data-scale="100" value="${pct(b.shade)}"></label>
    <label class="fld"><span>${t('bg.rotate')}</span>
      <input type="number" min="0" max="86400" data-bg="rotate_seconds" value="${b.rotate_seconds}"></label>
    <label class="fld"><span>${t('bg.baseColor')}</span>
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
  if (S.demo) {
    renderServices();
    return;
  }
  try {
    S.services = await getJSON('/api/services' + (force ? '?force=1' : ''));
    renderServices();
  } catch (err) {
    $('#svcNote').classList.remove('hidden');
    $('#svcNote').textContent = t('services.loadError', { error: err.message });
  }
}

function servicesWidget() {
  return S.config.widgets.find((w) => w.type === 'services');
}

function renderSvcCards() {
  const stats = S.demo ? DEMO_STATS : (S.state && S.state.stats);
  if (!stats || !stats.cpu) return;
  const gpu = stats.gpu || {};
  const disk = stats.disk || {};
  const diskLabel = t('storage.' + (disk.type || 'unknown'));
  const diskParts = [];
  if (disk.used_str && disk.total_str) diskParts.push(disk.used_str + ' / ' + disk.total_str);
  if (disk.read_str) diskParts.push('R ' + disk.read_str);
  if (disk.write_str) diskParts.push('W ' + disk.write_str);
  if (disk.busy != null) diskParts.push(disk.busy.toFixed(0) + '% ' + t('services.busy'));
  if (disk.latency != null) diskParts.push(disk.latency.toFixed(0) + ' ms');
  const diskSub = diskParts.length ? diskParts.join(' · ') : t('health.none');
  const gpuValue = gpu.percent != null ? Math.round(gpu.percent) + '%' : '—';
  const gpuParts = [];
  if (gpu.name) gpuParts.push(gpu.name);
  if (gpu.temp != null) gpuParts.push(gpu.temp.toFixed(0) + ' °C');
  if (gpu.memory_used_str && gpu.memory_total_str) {
    gpuParts.push(gpu.memory_used_str + ' / ' + gpu.memory_total_str);
  }
  if (!gpuParts.length) gpuParts.push(t('services.gpuNone'));
  const cards = [
    [t('services.cpu'), Number(stats.cpu.percent).toFixed(0) + '%', t('services.threads', { count: stats.cpu.count || '?' })],
    [t('services.ram'), Number(stats.ram.percent).toFixed(0) + '%', stats.ram.used_str + ' / ' + stats.ram.total_str],
    [diskLabel, Number(stats.disk.percent).toFixed(0) + '%', diskSub],
    [t('services.netDown'), stats.net.down_str, t('services.netUp') + ' ' + stats.net.up_str],
  ];
  if (gpu.available) {
    cards.push([t('services.gpu'), gpuValue, gpuParts.join(' · ')]);
  }
  cards.push(
    [t('services.uptime'), stats.uptime_str, stats.hostname],
    [t('services.load'), Number(stats.cpu.load).toFixed(2), t('services.cores', { count: stats.cpu.count || '?' })],
  );
  $('#svcCards').innerHTML = cards.map(([k, v, s]) =>
    `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join('');
}

function renderServices() {
  const data = S.services || { systemd: [], docker: [] };
  const units = data.systemd || [];
  const docker = data.docker || [];
  const note = $('#svcNote');

  const messages = [];
  if (data.systemd_error && !units.length) {
    messages.push(t('services.note.systemd', { error: data.systemd_error }));
  }
  if (data.docker_error && !docker.length) {
    messages.push(t('services.note.docker', { error: data.docker_error }));
  }
  if (data.actions_allowed === false) {
    messages.push(t('services.note.actions'));
  }
  const widget = servicesWidget();
  if (!widget) {
    messages.push(t('services.note.noDesign'));
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

  $('#svcCount').textContent = t('services.count', { filtered: filtered.length, total: units.length });
  $('#svcBody').innerHTML = filtered.map((u) => {
    const allowed = data.actions_allowed;
    const actions = [];
    if (u.active === 'active') {
      actions.push(actionBtn('restart', u.unit, t('services.restart'), allowed, 'ghost'));
      actions.push(actionBtn('stop', u.unit, t('services.stop'), allowed, 'danger'));
    } else {
      actions.push(actionBtn('start', u.unit, t('services.start'), allowed, 'primary'));
    }
    return `<tr>
      <td><input class="pick" type="checkbox" data-pick-unit="${esc(u.unit)}"
        ${picked.has(u.unit) ? 'checked' : ''} ${canPick ? '' : 'disabled'}></td>
      <td><code>${esc(u.unit)}</code><div class="desc">${esc(u.description || '')}</div></td>
      <td><span class="pill ${esc(u.active)}">${esc(t('state.' + u.active, {}, u.active))}</span></td>
      <td class="num">${u.cpu != null ? u.cpu + '%' : '—'}</td>
      <td class="num">${fmtBytes(u.memory)}</td>
      <td class="num">${esc(shortSince(u.since))}</td>
      <td class="act">${actions.join('')}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="7" class="muted">${t('services.noResults')}</td></tr>`;

  $('#dockerCount').textContent = t('services.dockerCount', { count: docker.length });
  $('#dockerBody').innerHTML = docker.map((c) => {
    const allowed = data.actions_allowed;
    const actions = c.state === 'running'
      ? actionBtn('restart', c.name, t('services.restart'), allowed, 'ghost', 'docker') +
        actionBtn('stop', c.name, t('services.stop'), allowed, 'danger', 'docker')
      : actionBtn('start', c.name, t('services.start'), allowed, 'primary', 'docker');
    return `<tr>
      <td><code>${esc(c.name)}</code></td>
      <td class="muted">${esc(c.image)}</td>
      <td><span class="pill ${c.state === 'running' ? 'active' : 'inactive'}">${esc(c.status || c.state)}</span></td>
      <td class="act">${actions}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="4" class="muted">${t('services.noDocker')}</td></tr>`;
}

function shortSince(value) {
  if (!value) return '—';
  return String(value).replace(/^\w{3}\s+/, '').replace(/:\d{2}\s+[+-]\d{4}$/, '');
}

function actionBtn(action, name, label, allowed, style, scope = 'systemd') {
  return `<button class="btn icon ${style}" data-svc-action="${action}" data-svc-name="${esc(name)}"
    data-svc-scope="${scope}" ${allowed ? '' : 'disabled title="' + esc(t('services.noPermission')) + '"'}>${label}</button>`;
}

$('#svcBody').addEventListener('change', (event) => {
  const unit = event.target.dataset.pickUnit;
  if (!unit) return;
  const widget = servicesWidget();
  if (!widget) {
    event.target.checked = false;
    toast(t('services.note.noPick'), true);
    return;
  }
  const set = new Set(widget.units || []);
  if (event.target.checked) set.add(unit); else set.delete(unit);
  widget.units = Array.from(set);
  scheduleSave();
});

async function doServiceAction(scope, name, action) {
  const verb = t('services.verb.' + action);
  if (!confirm(t('services.confirm', { verb, name }))) return;
  try {
    const res = await postJSON('/api/services/action', { scope, name, action });
    toast(res.ok ? t('toast.done') : (res.message || 'Error'), !res.ok);
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
    const gpu = health.gpu || {};
    const sensors = health.sensors || {};
    const cpuSensor = sensors.cpu_temp != null
      ? (sensors.cpu_source || 'CPU') + ' ' + Number(sensors.cpu_temp).toFixed(0) + ' °C'
      : t('health.none');
    const gpuSensor = sensors.gpu_temp != null
      ? (sensors.gpu_source || 'GPU') + ' ' + Number(sensors.gpu_temp).toFixed(0) + ' °C'
      : t('health.none');
    const rows = [
      [t('health.version'), health.version],
      [t('health.host'), health.host || '—'],
      [t('health.data'), health.data_dir],
      [t('health.panel'), device.connected ? (device.port || t('health.connected')) : (device.last_error || t('health.disconnected'))],
      [t('health.frames'), device.frames != null ? device.frames : '—'],
      [t('health.lastPush'), device.last_push ? new Date(device.last_push * 1000).toLocaleString(locale()) : '—'],
      [t('health.systemd'), health.systemd ? t('health.available') : t('health.unavailable')],
      [t('health.docker'), health.docker ? t('health.available') : t('health.notInstalled')],
      [t('health.gpu'), gpu.name || t('health.none')],
      [t('health.sensors'), t('health.cpu') + ': ' + cpuSensor + ' · ' + t('health.gpu') + ': ' + gpuSensor],
      [t('health.actions'), health.actions_allowed ? t('health.allowed') : t('health.readOnly')],
      [t('health.images'), health.backgrounds],
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
    toast(t('toast.configImported'));
  } catch (err) { toast(t('toast.configInvalid', { error: err.message }), true); }
  event.target.value = '';
});

$('#logsBtn').addEventListener('click', async () => {
  try {
    const data = await getJSON('/api/logs?lines=150');
    const box = $('#logsBox');
    box.classList.remove('hidden');
    box.textContent = (data.lines || []).join('\n') || t('settings.empty');
  } catch (err) { toast(err.message, true); }
});

/* -------------------------------------------------------------------- init */
boot();
