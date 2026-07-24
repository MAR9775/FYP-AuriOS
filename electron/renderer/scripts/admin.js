/* scripts/admin.js — Admin Dashboard (full functional implementation) */

(function () {
  'use strict';

  const BASE = 'http://127.0.0.1:8000';

  // ── Auth helpers ────────────────────────────────────────────────────────────

  function getToken() {
    return localStorage.getItem('aurios_auth_token') || '';
  }

  function authHeaders(extra) {
    return Object.assign({ 'Authorization': `Bearer ${getToken()}`, 'Content-Type': 'application/json' }, extra);
  }

  async function apiFetch(path, opts) {
    const res = await fetch(BASE + path, Object.assign({ headers: authHeaders() }, opts));
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const j = await res.clone().json(); detail = j.detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  }

  // ── Toast notifications ─────────────────────────────────────────────────────

  let _toastTimer = null;

  function showToast(message, type /* 'success' | 'error' | 'info' */) {
    type = type || 'info';
    const container = document.getElementById('admin-toast-container');
    if (!container) return;

    if (_toastTimer) { clearTimeout(_toastTimer); _toastTimer = null; }

    container.innerHTML = `<div class="admin-toast admin-toast-${type}">
      <span class="toast-icon">${
        type === 'success'
          ? '<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>'
          : type === 'error'
          ? '<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'
          : '<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>'
      }</span>
      <span class="toast-msg">${esc(message)}</span>
    </div>`;
    container.classList.add('visible');

    _toastTimer = setTimeout(() => {
      container.classList.remove('visible');
      setTimeout(() => { container.innerHTML = ''; }, 300);
    }, 3200);
  }

  // ── Confirm dialog ──────────────────────────────────────────────────────────

  function adminConfirm(message) {
    return new Promise((resolve) => {
      const overlay = document.getElementById('admin-confirm-overlay');
      const msgEl   = document.getElementById('admin-confirm-msg');
      const yesBtn  = document.getElementById('admin-confirm-yes');
      const noBtn   = document.getElementById('admin-confirm-no');
      if (!overlay) { resolve(false); return; }

      msgEl.textContent = message;
      overlay.classList.remove('hidden');

      function cleanup(result) {
        overlay.classList.add('hidden');
        yesBtn.removeEventListener('click', onYes);
        noBtn.removeEventListener('click', onNo);
        resolve(result);
      }
      function onYes() { cleanup(true); }
      function onNo()  { cleanup(false); }
      yesBtn.addEventListener('click', onYes);
      noBtn.addEventListener('click',  onNo);
    });
  }

  // ── Button loading states ───────────────────────────────────────────────────

  function setBtnLoading(btn, loading, originalHTML) {
    if (!btn) return;
    if (loading) {
      btn.dataset.origHTML = btn.innerHTML;
      btn.textContent = 'Loading...';
      btn.disabled = true;
    } else {
      btn.innerHTML = originalHTML || btn.dataset.origHTML || btn.innerHTML;
      btn.disabled = false;
    }
  }

  
  // ── Skeletons ───────────────────────────────────────────────────────────────
  function createSkeletonRow(cols) {
    let cells = '';
    for(let i=0; i<cols; i++) {
      const w = i === 0 ? 'short' : i === cols-1 ? 'short' : 'med';
      cells += `<td><div class="skeleton-row"><div class="skeleton-cell ${w}"></div></div></td>`;
    }
    return `<tr>${cells}</tr>`;
  }

  function skeletonRows(cols, count=4) {
    return Array(count).fill(createSkeletonRow(cols)).join('');
  }

  // ── Custom SVG Charts ───────────────────────────────────────────────────────

  function drawLineChart(data, width=300, height=100, color='#3b82f6') {
    if (!data || data.length === 0) return '';
    const max = Math.max(...data.map(d=>d.value), 1);
    const min = Math.min(...data.map(d=>d.value), 0);
    const dx = width / Math.max(data.length - 1, 1);
    let lineD = '';
    data.forEach((val, i) => {
      const x = i * dx;
      const y = height - ((val.value - min) / (max - min) * height * 0.8) - 10;
      lineD += `${i===0?'M':'L'}${x},${y} `;
    });
    return `<svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="overflow:visible;">
      <path d="${lineD}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
  }

  function drawTopSoftwareBars(data) {
    if (!data || data.length === 0) return '<div class="admin-empty-row">No data</div>';
    const max = Math.max(...data.map(d=>d.c), 1);
    return data.map(d => {
      const pct = (d.c / max) * 100;
      return `
        <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:4px;">
          <span style="color:#fff;">${esc(d.name)}</span>
          <span style="color:#a1a1aa;">${d.c}</span>
        </div>
        <div style="width:100%; height:8px; background:#252535; border-radius:4px; margin-bottom:16px;">
          <div style="width:${pct}%; height:100%; background:linear-gradient(90deg, #8b5cf6, #6d28d9); border-radius:4px;"></div>
        </div>
      `;
    }).join('');
  }

  function drawSuccessFailBars(data, width=300, height=100) {
    // data is like [{d: '2023-01-01', status: 'done', c: 5}, ...]
    if (!data || data.length === 0) return '';
    const days = [...new Set(data.map(d=>d.d))].sort();
    const parsed = days.map(day => {
      const dayData = data.filter(x => x.d === day);
      return {
        d: day,
        success: dayData.find(x => ['done','completed','success'].includes(x.status))?.c || 0,
        fail: dayData.find(x => ['failed','error'].includes(x.status))?.c || 0
      };
    });
    const max = Math.max(...parsed.map(p => Math.max(p.success, p.fail)), 1);
    const barWidth = Math.max((width / parsed.length) * 0.3, 2);
    const spacing = width / Math.max(parsed.length, 1);
    
    let svg = `<svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">`;
    parsed.forEach((p, i) => {
      const xCenter = i * spacing + spacing/2;
      const sh = (p.success / max) * height * 0.9;
      const fh = (p.fail / max) * height * 0.9;
      
      // Success bar (Green)
      svg += `<rect x="${xCenter - barWidth - 1}" y="${height - sh}" width="${barWidth}" height="${sh}" fill="#10b981" rx="2" ry="2"/>`;
      // Fail bar (Red)
      svg += `<rect x="${xCenter + 1}" y="${height - fh}" width="${barWidth}" height="${fh}" fill="#ef4444" rx="2" ry="2"/>`;
    });
    svg += '</svg>';
    return svg;
  }

  function drawSparkline(data, width=80, height=24, color='#8b5cf6') {
    if (!data || data.length === 0) return '';
    const max = Math.max(...data, 1);
    const min = 0;
    const dx = width / Math.max(data.length - 1, 1);
    let d = '';
    data.forEach((val, i) => {
      const x = i * dx;
      const y = height - ((val - min) / (max - min) * height * 0.8) - 2;
      d += `${i===0?'M':'L'}${x},${y} `;
    });
    return `<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="overflow:visible">
      <path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;
  }

  function drawAreaChart(data, width=300, height=100, color='#8b5cf6') {
    if (!data || data.length === 0) return '';
    const max = Math.max(...data.map(d=>d.value), 1);
    const dx = width / Math.max(data.length - 1, 1);
    let lineD = '';
    data.forEach((val, i) => {
      const x = i * dx;
      const y = height - ((val.value) / max * height * 0.9) - 2;
      lineD += `${i===0?'M':'L'}${x},${y} `;
    });
    const areaD = lineD + `L${width},${height} L0,${height} Z`;
    return `<svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <defs>
        <linearGradient id="areaGradient" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="${color}" stop-opacity="0.2" />
          <stop offset="100%" stop-color="${color}" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path d="${areaD}" fill="url(#areaGradient)"/>
      <path d="${lineD}" fill="none" stroke="${color}" stroke-width="2"/>
    </svg>`;
  }

  // ── Formatting helpers ──────────────────────────────────────────────────────

  function esc(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function fmtDate(ts) {
    if (!ts) return '—';
    const d = new Date(ts);
    if (isNaN(d)) return ts;
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
      + ' ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
  }

  function fmtBytes(gb) {
    if (gb == null) return '—';
    return gb.toFixed(1) + ' GB';
  }

  function statusBadge(status) {
    if (!status) return '<span class="admin-badge badge-neutral">—</span>';
    const s = status.toLowerCase();
    let cls = 'badge-neutral';
    if (['completed', 'success', 'done', 'ok', 'true'].includes(s))     cls = 'badge-success';
    else if (['failed', 'error', 'false'].includes(s))                   cls = 'badge-error';
    else if (['running', 'in_progress', 'pending', 'starting'].includes(s)) cls = 'badge-warning';
    else if (s === 'cancelled')                                           cls = 'badge-neutral';
    return `<span class="admin-badge ${cls}">${esc(status)}</span>`;
  }

  function roleBadge(role) {
    const cls = role === 'user' ? 'badge-blue' : 'badge-purple';
    return `<span class="admin-badge ${cls}">${esc(role)}</span>`;
  }

  function boolBadge(val) {
    return val
      ? '<span class="admin-badge badge-success">Yes</span>'
      : '<span class="admin-badge badge-error">No</span>';
  }

  // ── Table helpers ───────────────────────────────────────────────────────────

  function setBody(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  }

  function setCount(id, n) {
    const el = document.getElementById(id);
    if (el) el.textContent = n;
  }

  function emptyRow(cols, msg) {
    return `<tr class="admin-empty-row"><td colspan="${cols}">${msg}</td></tr>`;
  }

  function errRow(cols) {
    return emptyRow(cols, 'Failed to load — check backend connection.');
  }

  // ── Clock ───────────────────────────────────────────────────────────────────

  function startClock() {
    const el = document.getElementById('admin-live-time');
    if (!el) return;
    const tick = () => {
      el.textContent = new Date().toLocaleTimeString('en-US', {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      });
    };
    tick();
    setInterval(tick, 1000);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Section: Overview / Stats
  // ═══════════════════════════════════════════════════════════════════════════

  async function loadStats() {
    try {
      const d = await apiFetch('/admin/dashboard-stats');
      const set = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = v ?? '—'; };
      set('stat-users',    d.totals.users);
      set('stat-sessions', d.totals.active_sessions);
      set('stat-installs', d.totals.installations);
      set('stat-convos', d.totals.conversations ?? 0);
      
      const setHTML = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
      
      // FIX 8: compute real week-over-week trends from daily data
      const weekUsers = (d.users_by_day || []).slice(0, 7).reduce((s, r) => s + r.c, 0);
      const weekInstalls = (d.installs_activity || []).slice(0, 7).reduce((s, r) => s + r.c, 0);
      const weekConvos = (d.conversations_by_day || []).slice(0, 7).reduce((s, r) => s + r.c, 0);
      const upArrow = '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-1px"><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>';
      setHTML('trend-users', weekUsers > 0 ? `${upArrow} ${weekUsers} new this week` : 'No new this week');
      setHTML('trend-installs', weekInstalls > 0 ? `${upArrow} ${weekInstalls} this week` : 'None this week');
      setHTML('trend-convos', weekConvos > 0 ? `${weekConvos} this week` : `${d.totals.conversations ?? 0} total`);
      
      const liveDot = document.getElementById('live-session-dot');
      if (liveDot) {
        if (d.totals.active_sessions > 0) liveDot.classList.add('pulse');
        else liveDot.classList.remove('pulse');
      }
      set('live-session-text', `${d.totals.active_sessions} live now`);
      
      // Inject sparklines with specific colors
      const usersSpark = d.users_by_day.map(r=>r.c).reverse();
      const installsSpark = d.installs_activity.map(r=>r.c).reverse();
      // FIX 9: use real conversations-by-day data from backend
      const convosSpark = (d.conversations_by_day || []).map(r=>r.c).reverse();
      
      const setSpark = (id, data, color) => { const el = document.getElementById(id); if (el) el.innerHTML = drawSparkline(data, 60, 30, color); };
      setSpark('spark-users', usersSpark, '#06b6d4');
      setSpark('spark-installs', installsSpark, '#f59e0b');
      setSpark('spark-convos', convosSpark, '#10b981');
      
      // Inject big charts
      const elArea = document.getElementById('chart-install-activity');
      if (elArea) elArea.innerHTML = drawAreaChart(d.installs_activity.map(r=>({value:r.c})).reverse());
      
      const elTop = document.getElementById('chart-top-software');
      if (elTop) elTop.innerHTML = drawTopSoftwareBars(d.top_software);
      
      const elGrowth = document.getElementById('chart-user-growth');
      if (elGrowth) {
        let cumulative = 0;
        const growthData = d.users_by_day.reverse().map(r => { cumulative += r.c; return {value: cumulative}; });
        elGrowth.innerHTML = drawLineChart(growthData, 300, 100, '#06b6d4');
      }
      
      const elSF = document.getElementById('chart-success-fail');
      if (elSF) elSF.innerHTML = drawSuccessFailBars(d.success_fail);

      
    } catch (_) {}
  }

  async function loadOverviewInstalls() {
    setBody('overview-installs-body', skeletonRows(4, 4));
    try {
      const rows = await apiFetch('/admin/installations');
      setCount('overview-installs-count', rows.length);
      if (!rows.length) { setBody('overview-installs-body', emptyRow(4, 'No installations yet.')); return; }
      setBody('overview-installs-body', rows.slice(0, 8).map(r => `
        <tr>
          <td class="cell-primary">${esc(r.preset_name || r.software || '—')}</td>
          <td>${statusBadge(r.status)}</td>
          <td class="cell-muted">${r.duration_s != null ? r.duration_s.toFixed(1) + 's' : '—'}</td>
          <td class="cell-muted">${fmtDate(r.timestamp)}</td>
        </tr>`).join(''));
    } catch (_) {
      setBody('overview-installs-body', errRow(4));
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Section: System Status
  // ═══════════════════════════════════════════════════════════════════════════

  async function loadSystemStatus() {
    const contentEl = document.getElementById('system-status-content');
    if (!contentEl) return;
    contentEl.innerHTML = '<div class="admin-loading-state">Fetching system status…</div>';

    try {
      const d = await apiFetch('/admin/system-status');

      const diskPct = d.disk_total_gb > 0
        ? Math.round((d.disk_used_gb / d.disk_total_gb) * 100)
        : 0;

      const swRows = Object.entries(d.installed || {}).map(([name, ok]) => `
        <div class="sys-sw-row">
          <span class="sys-sw-name">${esc(name)}</span>
          ${boolBadge(ok)}
        </div>`).join('');

      contentEl.innerHTML = `
        <div class="sys-grid">
          <div class="sys-card">
            <div class="sys-card-label">Ollama</div>
            <div class="sys-card-value">${boolBadge(d.ollama_connected)}</div>
            <div class="sys-card-sub">LLM engine connectivity</div>
          </div>
          <div class="sys-card">
            <div class="sys-card-label">System Admin</div>
            <div class="sys-card-value">${boolBadge(d.is_admin)}</div>
            <div class="sys-card-sub">Elevated OS privileges</div>
          </div>
          <div class="sys-card">
            <div class="sys-card-label">CPU Usage</div>
            <div class="sys-card-value sys-num">${d.cpu_percent != null ? d.cpu_percent.toFixed(1) + '%' : '—'}</div>
            <div class="sys-status-bar-container"><div class="sys-status-bar-fill" style="width:${d.cpu_percent || 0}%;background:${(d.cpu_percent||0)>85?'var(--c-red)':(d.cpu_percent||0)>60?'var(--c-amber)':'var(--c-green)'}"></div></div>
          </div>
          <div class="sys-card">
            <div class="sys-card-label">RAM Usage</div>
            <div class="sys-card-value sys-num">${d.ram_percent != null ? d.ram_percent.toFixed(1) + '%' : '—'}</div>
            <div class="sys-card-sub">${d.ram_used_gb != null ? d.ram_used_gb + ' GB used of ' + d.ram_total_gb + ' GB' : ''}</div>
            <div class="sys-status-bar-container"><div class="sys-status-bar-fill" style="width:${d.ram_percent || 0}%;background:${(d.ram_percent||0)>85?'var(--c-red)':(d.ram_percent||0)>60?'var(--c-amber)':'var(--c-purple)'}"></div></div>
          </div>
          <div class="sys-card">
            <div class="sys-card-label">Free Disk</div>
            <div class="sys-card-value sys-num">${fmtBytes(d.free_disk_gb)}</div>
            <div class="sys-card-sub">${fmtBytes(d.disk_used_gb)} used of ${fmtBytes(d.disk_total_gb)}</div>
          </div>
          <div class="sys-card">
            <div class="sys-card-label">Platform</div>
            <div class="sys-card-value sys-platform">${esc(d.platform || '—')}</div>
            <div class="sys-card-sub">Python ${esc(d.python_version || '—')}</div>
          </div>
        </div>

        <div class="admin-table-section">
          <div class="admin-table-header">
            <h3>Disk Usage</h3>
          </div>
          <div class="sys-disk-bar-wrap">
            <div class="sys-disk-bar">
              <div class="sys-disk-fill" style="width:${diskPct}%"></div>
            </div>
            <span class="sys-disk-label">${diskPct}% used</span>
          </div>
        </div>

        <div class="admin-table-section">
          <div class="admin-table-header">
            <h3>Detected Software</h3>
            <span class="admin-count-badge">${Object.keys(d.installed || {}).length}</span>
          </div>
          <div class="sys-sw-grid">${swRows || '<div class="admin-loading-state">No software checked.</div>'}</div>
        </div>`;
    } catch (err) {
      contentEl.innerHTML = `<div class="admin-error-state">Failed to load system status: ${esc(err.message)}</div>`;
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Section: Users
  // ═══════════════════════════════════════════════════════════════════════════

  async function loadUsers() {
    setBody('users-body', skeletonRows(5, 5));
    try {
      const rows = await apiFetch('/admin/users');
      setCount('users-count', rows.length);
      if (!rows.length) { setBody('users-body', emptyRow(4, 'No registered users.')); return; }
      setBody('users-body', rows.map(r => {
        const isInactive = (r.status || 'active') === 'inactive';
        const toggleBtn = isInactive
          ? `<button class="admin-tbl-btn primary" data-action="reactivate-user" data-id="${esc(r.id)}" data-email="${esc(r.email)}">Reactivate</button>`
          : `<button class="admin-tbl-btn secondary" data-action="deactivate-user" data-id="${esc(r.id)}" data-email="${esc(r.email)}">Deactivate</button>`;
        const statusEl = isInactive
          ? '<span class="admin-badge badge-error">Inactive</span>'
          : '<span class="admin-badge badge-success">Active</span>';
        return `
        <tr>
          <td class="cell-mono">${esc(r.id)}</td>
          <td class="cell-primary">${esc(r.name)}</td>
          <td>${esc(r.email)}</td>
          <td>${roleBadge(r.role || 'user')}</td>
          <td>${statusEl}</td>
          <td>
            <button class="admin-tbl-btn secondary" data-action="reset-pw"
              data-id="${esc(r.id)}" data-email="${esc(r.email)}">Reset PW</button>
            ${toggleBtn}
            <button class="admin-tbl-btn danger" data-action="delete-user"
              data-id="${esc(r.id)}" data-email="${esc(r.email)}">Delete</button>
          </td>
        </tr>`;
      }).join(''));
    } catch (_) {
      setBody('users-body', errRow(5));
    }
  }

  async function deleteUser(userId, userEmail) {
    const ok = await adminConfirm(`Permanently delete user "${userEmail}"?\nThis also removes all their sessions.`);
    if (!ok) return;
    try {
      await apiFetch(`/admin/users/${userId}`, { method: 'DELETE' });
      showToast(`User ${userEmail} deleted.`, 'success');
      loadUsers();
      loadStats();
    } catch (err) {
      showToast(`Delete failed: ${err.message}`, 'error');
    }
  }

  async function deactivateUser(userId, userEmail) {
    const ok = await adminConfirm(`Deactivate "${userEmail}"?\nThey will be unable to log in until reactivated.`);
    if (!ok) return;
    try {
      await apiFetch(`/admin/users/${userId}/deactivate`, { method: 'POST' });
      showToast(`${userEmail} deactivated.`, 'success');
      loadUsers();
    } catch (err) {
      showToast(`Deactivate failed: ${err.message}`, 'error');
    }
  }

  async function reactivateUser(userId, userEmail) {
    // FIX 18: add confirmation before reactivating
    const ok = await adminConfirm(`Reactivate "${userEmail}"? They will regain full access to the system.`);
    if (!ok) return;
    try {
      await apiFetch(`/admin/users/${userId}/reactivate`, { method: 'POST' });
      showToast(`${userEmail} reactivated.`, 'success');
      loadUsers();
    } catch (err) {
      showToast(`Reactivate failed: ${err.message}`, 'error');
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Section: Installations + Tasks
  // ═══════════════════════════════════════════════════════════════════════════

  let _installHistory = [];

  function renderInstallHistory(rows) {
    setCount('installs-count', rows.length);
    if (!rows.length) { setBody('installs-body', emptyRow(5, 'No matching records.')); return; }
    setBody('installs-body', rows.map(r => `
          <tr>
            <td class="cell-mono">${esc(r.id)}</td>
            <td class="cell-primary">${esc(r.preset_name || r.software || '—')}</td>
            <td>${statusBadge(r.status)}</td>
            <td class="cell-muted">${r.duration_s != null ? r.duration_s.toFixed(1) + 's' : '—'}</td>
            <td class="cell-muted">${fmtDate(r.timestamp)}</td>
          </tr>`).join(''));
  }

  function filterInstalls() {
    const text  = (document.getElementById('installs-filter-text')?.value || '').toLowerCase().trim();
    const status = (document.getElementById('installs-filter-status')?.value || '').toLowerCase();
    const filtered = _installHistory.filter(r => {
      const name = (r.preset_name || r.software || '').toLowerCase();
      const matchText   = !text   || name.includes(text);
      const matchStatus = !status || (r.status || '').toLowerCase() === status;
      return matchText && matchStatus;
    });
    renderInstallHistory(filtered);
  }

  async function loadInstallations() {
    setBody('installs-body', skeletonRows(5, 5));
    setBody('tasks-body', skeletonRows(6, 5));
    try {
      const [history, tasks] = await Promise.all([
        apiFetch('/admin/installations'),
        apiFetch('/admin/tasks'),
      ]);

      // Cache and render history
      _installHistory = history || [];
      renderInstallHistory(_installHistory);

      // Wire filter controls (idempotent: only bind once via flag)
      const filterText   = document.getElementById('installs-filter-text');
      const filterStatus = document.getElementById('installs-filter-status');
      const filterClear  = document.getElementById('installs-filter-clear');
      if (filterText && !filterText.dataset.wired) {
        filterText.addEventListener('input', filterInstalls);
        filterText.dataset.wired = '1';
      }
      if (filterStatus && !filterStatus.dataset.wired) {
        filterStatus.addEventListener('change', filterInstalls);
        filterStatus.dataset.wired = '1';
      }
      if (filterClear && !filterClear.dataset.wired) {
        filterClear.addEventListener('click', () => {
          if (filterText) filterText.value = '';
          if (filterStatus) filterStatus.value = '';
          renderInstallHistory(_installHistory);
        });
        filterClear.dataset.wired = '1';
      }

      // Tasks table
      setCount('tasks-count', tasks.length);
      if (!tasks.length) {
        setBody('tasks-body', emptyRow(6, 'No tasks found.'));
      } else {
        setBody('tasks-body', tasks.map(r => {
          const canCancel = !['done', 'cancelled', 'failed'].includes(r.status);
          const cancelBtn = canCancel
            ? `<button class="admin-tbl-btn danger" data-action="cancel-task" data-id="${esc(r.id)}">Cancel</button>`
            : '<span class="cell-muted">—</span>';
          return `
            <tr>
              <td class="cell-mono" style="max-width:120px">${esc(r.id.slice(0, 8))}…</td>
              <td class="cell-primary">${esc(r.preset || '—')}</td>
              <td>${statusBadge(r.status)}</td>
              <td>
                <div class="task-progress-bar">
                  <div class="task-progress-fill" style="width:${r.progress || 0}%"></div>
                </div>
                <span class="cell-muted" style="font-size:11px">${r.progress || 0}%</span>
              </td>
              <td class="cell-muted" style="max-width:180px">${esc((r.current_step || '').replace(/:/g, ' '))}</td>
              <td>${cancelBtn}</td>
            </tr>`;
        }).join(''));
      }
    } catch (_) {
      setBody('installs-body', errRow(5));
      setBody('tasks-body',    errRow(6));
    }
  }

  async function cancelTask(taskId) {
    const ok = await adminConfirm('Cancel this installation task?');
    if (!ok) return;
    try {
      await apiFetch(`/cancel/${taskId}`, { method: 'POST' });
      showToast('Task cancelled.', 'success');
      loadInstallations();
    } catch (err) {
      showToast(`Cancel failed: ${err.message}`, 'error');
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Section: Conversations
  // ═══════════════════════════════════════════════════════════════════════════

  async function loadConversations() {
    setBody('convos-body', skeletonRows(4, 5));
    try {
      const rows = await apiFetch('/admin/conversations');
      setCount('convos-count', rows.length);
      if (!rows.length) { setBody('convos-body', emptyRow(4, 'No conversations logged.')); return; }
      setBody('convos-body', rows.map(r => {
        const roleClass = r.role === 'user' ? 'badge-blue' : 'badge-purple';
        return `
          <tr>
            <td class="cell-mono">${esc(r.id)}</td>
            <td><span class="admin-badge ${roleClass}">${esc(r.role)}</span></td>
            <td class="convo-preview">${esc(r.content)}</td>
            <td class="cell-muted">${fmtDate(r.timestamp)}</td>
          </tr>`;
      }).join(''));
    } catch (_) {
      setBody('convos-body', errRow(4));
    }
  }

  async function clearConversations() {
    const btn = document.getElementById('clear-history-btn');
    const ok = await adminConfirm('Clear ALL conversation history? This cannot be undone.');
    if (!ok) return;
    setBtnLoading(btn, true);
    try {
      await apiFetch('/admin/conversations', { method: 'DELETE' });
      showToast('Conversation history cleared.', 'success');
      loadConversations();
      loadStats();
    } catch (err) {
      showToast(`Failed: ${err.message}`, 'error');
    } finally {
      setBtnLoading(btn, false, 'Clear History');
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Section: Preferences
  // ═══════════════════════════════════════════════════════════════════════════

  async function loadPreferences() {
    const section = document.getElementById('section-preferences');
    const tableSection = section ? section.querySelector('.admin-table-section') : null;
    if (!tableSection) return;

    // Show skeleton in the existing table body while loading
    setBody('prefs-body', skeletonRows(4, 5));

    try {
      const [allPrefs, allUsers] = await Promise.all([
        apiFetch('/admin/preferences'),
        apiFetch('/admin/users'),
      ]);

      // Build a map: user_id (or null) -> [pref rows]
      const byUser = {};
      allPrefs.forEach(r => {
        const uid = r.user_id != null ? String(r.user_id) : '__system__';
        if (!byUser[uid]) byUser[uid] = [];
        byUser[uid].push(r);
      });

      // Build user lookup by id
      const userMap = {};
      allUsers.forEach(u => { userMap[String(u.id)] = u; });

      // Total count across all users
      setCount('prefs-count', allPrefs.length);

      if (!allPrefs.length) {
        setBody('prefs-body', emptyRow(4, 'No preferences stored.'));
        return;
      }

      // Order: system (null user_id) first, then users sorted by id
      const uidKeys = Object.keys(byUser).sort((a, b) => {
        if (a === '__system__') return -1;
        if (b === '__system__') return 1;
        return parseInt(a) - parseInt(b);
      });

      // Build all rows — user header rows + pref rows — into the single tbody
      let html = '';
      uidKeys.forEach(uid => {
        const prefs = byUser[uid];
        const user = uid === '__system__' ? null : userMap[uid];

        if (uid === '__system__') {
          // System-level prefs (no user association)
          html += `
            <tr>
              <td colspan="4" style="padding:10px 16px;background:rgba(139,92,246,0.08);border-left:3px solid #8b5cf6;">
                <div style="display:flex;align-items:center;gap:10px;">
                  <span style="font-weight:600;color:#a78bfa;">System / Global</span>
                  <span class="admin-badge badge-purple">Global</span>
                  <span style="margin-left:auto;font-size:11px;color:var(--text-muted);">${prefs.length} key${prefs.length !== 1 ? 's' : ''}</span>
                </div>
              </td>
            </tr>`;
        } else if (user) {
          html += `
            <tr>
              <td colspan="4" style="padding:10px 16px;background:rgba(6,182,212,0.07);border-left:3px solid #06b6d4;">
                <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                  <span style="font-weight:600;color:#06b6d4;">${esc(user.name)}</span>
                  <span style="font-size:12px;color:var(--text-muted);">${esc(user.email)}</span>
                  ${roleBadge(user.role || 'user')}
                  <span style="margin-left:auto;font-size:11px;color:var(--text-muted);">${prefs.length} key${prefs.length !== 1 ? 's' : ''}</span>
                </div>
              </td>
            </tr>`;
        } else {
          // user_id present but user not found (deleted user)
          html += `
            <tr>
              <td colspan="4" style="padding:10px 16px;background:rgba(161,161,170,0.07);border-left:3px solid #52525b;">
                <div style="display:flex;align-items:center;gap:10px;">
                  <span style="font-weight:600;color:#a1a1aa;">User #${esc(uid)}</span>
                  <span class="admin-badge badge-neutral">Deleted</span>
                  <span style="margin-left:auto;font-size:11px;color:var(--text-muted);">${prefs.length} key${prefs.length !== 1 ? 's' : ''}</span>
                </div>
              </td>
            </tr>`;
        }

        prefs.forEach(r => {
          html += buildPrefRow(r.key, r.value, r.updated_at, r.user_id);
        });
      });

      setBody('prefs-body', html);
    } catch (_) {
      setBody('prefs-body', errRow(4));
    }
  }

  // uid is the raw user_id value (integer or null)
  function buildPrefRow(key, value, updatedAt, uid) {
    // Encode uid into the row id and button data so edit/save/cancel stay scoped
    const safeUid = uid != null ? String(uid) : '__system__';
    const rowId   = `pref-row-${esc(key)}-${safeUid}`;
    return `
      <tr id="${rowId}">
        <td class="cell-primary cell-mono">${esc(key)}</td>
        <td class="pref-value-cell">${esc(value)}</td>
        <td class="cell-muted">${fmtDate(updatedAt)}</td>
        <td>
          <button class="admin-tbl-btn secondary" data-action="edit-pref"
            data-key="${esc(key)}" data-value="${esc(value)}"
            data-uid="${safeUid}">Edit</button>
        </td>
      </tr>`;
  }

  function enterPrefEditMode(key, currentValue, safeUid) {
    const row = document.getElementById(`pref-row-${key}-${safeUid}`);
    if (!row) return;
    const valueCell  = row.querySelector('.pref-value-cell');
    const actionCell = row.querySelector('td:last-child');
    if (!valueCell || !actionCell) return;

    valueCell.innerHTML = `<input class="pref-inline-input" id="pref-input-${esc(key)}-${safeUid}"
      value="${esc(currentValue)}" autocomplete="off" />`;
    actionCell.innerHTML = `
      <button class="admin-tbl-btn primary"   data-action="save-pref"
        data-key="${esc(key)}" data-uid="${safeUid}">Save</button>
      <button class="admin-tbl-btn secondary" data-action="cancel-pref"
        data-key="${esc(key)}" data-value="${esc(currentValue)}"
        data-uid="${safeUid}">Cancel</button>`;

    const input = document.getElementById(`pref-input-${key}-${safeUid}`);
    if (input) { input.focus(); input.select(); }
  }

  function cancelPrefEdit(key, originalValue, safeUid) {
    const row = document.getElementById(`pref-row-${key}-${safeUid}`);
    if (!row) return;
    const valueCell  = row.querySelector('.pref-value-cell');
    const actionCell = row.querySelector('td:last-child');
    if (valueCell)  valueCell.textContent = originalValue;
    if (actionCell) actionCell.innerHTML = `
      <button class="admin-tbl-btn secondary" data-action="edit-pref"
        data-key="${esc(key)}" data-value="${esc(originalValue)}"
        data-uid="${safeUid}">Edit</button>`;
  }

  async function savePref(key, safeUid) {
    const input   = document.getElementById(`pref-input-${key}-${safeUid}`);
    if (!input) return;
    const newValue = input.value.trim();
    const saveBtn  = document.querySelector(`[data-action="save-pref"][data-key="${key}"][data-uid="${safeUid}"]`);
    setBtnLoading(saveBtn, true);
    try {
      // Pass user_id (null for system prefs) so the backend updates the right row
      const userId = safeUid === '__system__' ? null : parseInt(safeUid, 10);
      await apiFetch(`/admin/preferences/${encodeURIComponent(key)}`, {
        method: 'PUT',
        body: JSON.stringify({ value: newValue, user_id: userId }),
      });
      showToast(`Saved: ${key}`, 'success');
      loadPreferences();
    } catch (err) {
      showToast(`Save failed: ${err.message}`, 'error');
      setBtnLoading(saveBtn, false, 'Save');
    }
  }

  async function resetAllPreferences() {
    const btn = document.getElementById('reset-prefs-btn');
    const ok = await adminConfirm('Reset ALL preferences? This will clear onboarding, voice settings, and all user preferences.');
    if (!ok) return;
    setBtnLoading(btn, true);
    try {
      await apiFetch('/admin/preferences', { method: 'DELETE' });
      showToast('All preferences reset.', 'success');
      loadPreferences();
    } catch (err) {
      showToast(`Reset failed: ${err.message}`, 'error');
    } finally {
      setBtnLoading(btn, false, '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.5"/></svg> Reset All');
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Section: Software Catalog
  // ═══════════════════════════════════════════════════════════════════════════

  async function loadCatalog() {
    setBody('catalog-body', skeletonRows(5, 6));
    // Show last-synced info
    try {
      const sync = await apiFetch('/admin/catalog/sync-status');
      const syncEl = document.getElementById('catalog-sync-status');
      if (syncEl && sync.last_sync_ts) {
        syncEl.textContent = `Last synced: ${sync.last_sync_ago_min != null ? sync.last_sync_ago_min + ' min ago' : sync.last_sync_ts}`;
      }
    } catch (_) {}
    try {
      const rows = await apiFetch('/available-software');
      setCount('catalog-count', rows.length);
      if (!rows.length) { setBody('catalog-body', emptyRow(5, 'No software in catalog.')); return; }
      setBody('catalog-body', rows.map(r => `
        <tr>
          <td class="cell-primary">${esc(r.display_name || r.slug || '—')}</td>
          <td class="cell-mono">${esc(r.slug || '—')}</td>
          <td class="cell-muted" style="max-width:220px">${esc(r.url ? new URL(r.url).hostname : '—')}</td>
          <td class="cell-muted">${esc(r.filename || '—')}</td>
          <td style="text-align: right;">
            <button class="admin-tbl-btn secondary" data-action="edit-software" 
              data-slug="${esc(r.slug)}" data-name="${esc(r.display_name)}" 
              data-url="${esc(r.url)}" data-file="${esc(r.filename)}">Edit</button>
            <button class="admin-tbl-btn danger" data-action="delete-software" data-slug="${esc(r.slug)}">Delete</button>
          </td>
        </tr>`).join(''));
    } catch (_) {
      setBody('catalog-body', errRow(5));
    }
  }

  async function refreshCatalog() {
    const btn = document.getElementById('catalog-refresh-btn');
    const icon = btn.querySelector('.refresh-icon');
    const text = btn.querySelector('.refresh-text');
    if (icon) icon.style.animation = 'spin 1s linear infinite';
    if (text) text.textContent = 'Refreshing...';
    btn.disabled = true;
    try {
      const res = await apiFetch('/admin/catalog/refresh', { method: 'POST' });
      showToast(`Catalog refreshed — ${res.count} items synced.`, 'success');
      loadCatalog();
      if (icon) { icon.style.animation = 'none'; icon.textContent = ''; icon.innerHTML = '<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>'; }
      if (text) text.textContent = 'Updated';
      setTimeout(() => {
        if (icon) icon.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.5"/></svg>';
        if (text) text.textContent = 'Refresh from Source';
        btn.disabled = false;
      }, 1500);
    } catch (err) {
      showToast(`Refresh failed: ${err.message}`, 'error');
      if (icon) { icon.style.animation = 'none'; icon.textContent = ''; icon.innerHTML = '<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>'; }
      if (text) text.textContent = 'Failed';
      setTimeout(() => {
        if (icon) icon.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.5"/></svg>';
        if (text) text.textContent = 'Refresh from Source';
        btn.disabled = false;
      }, 1500);
    }
  }

  // Add Software Modal Logic
  function openSoftwareModal(isEdit, data={}) {
    const modal = document.getElementById('admin-software-modal');
    document.getElementById('software-modal-title').textContent = isEdit ? 'Edit Software' : 'Add Software';
    document.getElementById('sw-slug').value = data.slug || '';
    document.getElementById('sw-slug').disabled = isEdit; // slug acts as ID
    document.getElementById('sw-display-name').value = data.name || '';
    document.getElementById('sw-url').value = data.url || '';
    document.getElementById('sw-filename').value = data.file || '';
    modal.classList.remove('hidden');
  }

  function closeSoftwareModal() {
    document.getElementById('admin-software-modal').classList.add('hidden');
  }

  async function saveSoftwareModal() {
    const slug = document.getElementById('sw-slug').value.trim();
    const displayName = document.getElementById('sw-display-name').value.trim();
    const url = document.getElementById('sw-url').value.trim();
    const filename = document.getElementById('sw-filename').value.trim();
    
    // FIX 6: require filename field as well
    if (!slug || !displayName || !url || !filename) { showToast('Please fill all fields (slug, name, URL, filename).', 'error'); return; }
    
    const btn = document.getElementById('sw-modal-save');
    const origText = btn.textContent;
    btn.textContent = 'Saving...'; btn.disabled = true;
    try {
      await apiFetch('/admin/catalog/local', {
        method: 'POST',
        body: JSON.stringify({ slug, display_name: displayName, url, filename })
      });
      showToast('Software saved.', 'success');
      closeSoftwareModal();
      loadCatalog();
    } catch(err) {
      showToast('Failed to save: ' + err.message, 'error');
    } finally {
      btn.textContent = origText; btn.disabled = false;
    }
  }

  async function deleteSoftware(slug) {
    if (!await adminConfirm(`Are you sure you want to delete ${slug}?`)) return;
    try {
      await apiFetch(`/admin/catalog/local/${slug}`, { method: 'DELETE' });
      showToast('Software deleted.', 'success');
      loadCatalog();
    } catch(err) {
      showToast('Failed to delete: ' + err.message, 'error');
    }
  }


  // ═══════════════════════════════════════════════════════════════════════════
  // Section: Sessions
  // ═══════════════════════════════════════════════════════════════════════════

  async function loadSessions() {
    setBody('sessions-body', skeletonRows(5, 5));
    try {
      const rows = await apiFetch('/admin/sessions');
      setCount('sessions-count', rows.length);
      if (!rows.length) { setBody('sessions-body', emptyRow(5, 'No active sessions.')); return; }
      setBody('sessions-body', rows.map(r => `
        <tr>
          <td class="cell-mono">${esc(r.token_preview)}</td>
          <td class="cell-primary">${esc(r.user_name)}</td>
          <td>${esc(r.email)}</td>
          <td class="cell-muted">${fmtDate(r.created_at)}</td>
          <td>
            <button class="admin-tbl-btn danger" data-action="revoke-session"
              data-token="${esc(r.token)}">Revoke</button>
          </td>
        </tr>`).join(''));
    } catch (_) {
      setBody('sessions-body', errRow(5));
    }
  }

  async function revokeSession(token) {
    const ok = await adminConfirm('Revoke this session? The user will be logged out immediately.');
    if (!ok) return;
    try {
      await apiFetch('/admin/sessions/revoke', {
        method: 'POST',
        body: JSON.stringify({ token }),
      });
      showToast('Session revoked.', 'success');
      loadSessions();
      loadStats();
    } catch (err) {
      showToast(`Revoke failed: ${err.message}`, 'error');
    }
  }


  // ═══════════════════════════════════════════════════════════════════════════
  // Section: Admin Management
  // ═══════════════════════════════════════════════════════════════════════════

  async function loadAdmins() {
    setBody('admins-body', skeletonRows(5, 3));
    try {
      const rows = await apiFetch('/admin/users'); // We filter by role client-side
      const admins = rows.filter(r => r.role === 'admin' || r.id === 0);
      // FIX 5: update the count badge
      setCount('admins-count', admins.length);
      if (!admins.length) { setBody('admins-body', emptyRow(5, 'No administrators found.')); return; }
      setBody('admins-body', admins.map(r => {
        const isSysAdmin = r.id === 0;
        const revokeBtn = isSysAdmin ? '' : `<button class="admin-tbl-btn danger" data-action="revoke-admin" data-id="${esc(r.id)}" data-email="${esc(r.email)}">Revoke</button>`;
        const delBtn = isSysAdmin ? '' : `<button class="admin-tbl-btn danger" data-action="delete-user" data-id="${esc(r.id)}" data-email="${esc(r.email)}">Delete</button>`;
        // FIX 11: add ID cell to match 5-column thead (ID, Name, Email, Created, Actions)
        return `
        <tr>
          <td class="cell-mono">${isSysAdmin ? '<span class="cell-muted">—</span>' : esc(String(r.id))}</td>
          <td class="cell-primary">${esc(r.name)} ${isSysAdmin ? '<span class="admin-badge badge-purple">System</span>' : ''}</td>
          <td>${esc(r.email)}</td>
          <td class="cell-muted">${fmtDate(r.created_at)}</td>
          <td style="text-align:right;">
            <button class="admin-tbl-btn secondary" data-action="reset-pw" data-id="${esc(r.id)}" data-email="${esc(r.email)}">Reset PW</button>
            ${revokeBtn}
            ${delBtn}
          </td>
        </tr>`;
      }).join(''));
    } catch (_) {
      setBody('admins-body', errRow(5));
    }
  }

  async function revokeAdmin(id, email) {
    if (!await adminConfirm(`Revoke admin privileges for ${email}? They will become a regular user.`)) return;
    try {
      await apiFetch(`/admin/accounts/revoke/${id}`, { method: 'POST' });
      showToast('Admin revoked.', 'success');
      loadAdmins();
    } catch(err) {
      showToast(`Revoke failed: ${err.message}`, 'error');
    }
  }

  // PW Reset Modal
  let _resetTargetId = null;
  function openResetPwModal(id, email) {
    _resetTargetId = id;
    document.getElementById('reset-pw-target').textContent = `Target: ${email}`;
    document.getElementById('reset-pw-new').value = '';
    document.getElementById('reset-pw-confirm').value = '';
    document.getElementById('admin-reset-pw-modal').classList.remove('hidden');
  }

  async function submitResetPw() {
    const p1 = document.getElementById('reset-pw-new').value;
    const p2 = document.getElementById('reset-pw-confirm').value;
    // FIX 17: validate password length before checking match
    if (!p1) { showToast('Please enter a new password.', 'error'); return; }
    if (p1.length < 8) { showToast('Password must be at least 8 characters.', 'error'); return; }
    if (p1 !== p2) { showToast('Passwords do not match.', 'error'); return; }
    try {
      await apiFetch('/admin/accounts/reset-password', {
        method: 'POST',
        body: JSON.stringify({ user_id: parseInt(_resetTargetId), new_password: p1 })
      });
      showToast('Password reset successful.', 'success');
      document.getElementById('admin-reset-pw-modal').classList.add('hidden');
    } catch(err) {
      showToast(`Reset failed: ${err.message}`, 'error');
    }
  }

  // Create Admin Modal
  function openCreateAdminModal() {
    document.getElementById('new-admin-name').value = '';
    document.getElementById('new-admin-email').value = '';
    document.getElementById('new-admin-pw').value = '';
    document.getElementById('new-admin-pw-confirm').value = '';
    document.getElementById('admin-create-modal').classList.remove('hidden');
  }

  async function submitCreateAdmin() {
    const name = document.getElementById('new-admin-name').value.trim();
    const email = document.getElementById('new-admin-email').value.trim();
    const p1 = document.getElementById('new-admin-pw').value;
    const p2 = document.getElementById('new-admin-pw-confirm').value;
    // FIX 5: stronger validation for create admin form
    if (!name || !email || !p1) { showToast('Please fill all required fields.', 'error'); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { showToast('Please enter a valid email address.', 'error'); return; }
    if (p1.length < 8) { showToast('Password must be at least 8 characters.', 'error'); return; }
    if (p1 !== p2) { showToast('Passwords do not match.', 'error'); return; }
    
    try {
      await apiFetch('/admin/accounts', {
        method: 'POST',
        body: JSON.stringify({ name, email, password: p1 })
      });
      showToast('Administrator created.', 'success');
      document.getElementById('admin-create-modal').classList.add('hidden');
      loadAdmins();
    } catch(err) {
      showToast(`Failed: ${err.message}`, 'error');
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Section: Software Manager Streams
  // ═══════════════════════════════════════════════════════════════════════════
  
  async function streamFetch(url, body, onProgress, onDone, onError) {
    try {
      const res = await fetch(BASE + url, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const data = JSON.parse(line);
            onProgress(data);
          } catch(e) {}
        }
      }
      onDone();
    } catch(err) {
      onError(err);
    }
  }

  async function startDownload() {
    const query = (document.getElementById('dl-search-input')?.value || '').trim();
    if (!query) { showToast('Enter a software name to search.', 'error'); return; }

    const btn = document.getElementById('dl-start-btn');
    const wrap = document.getElementById('dl-progress-wrap');
    const statusEl = document.getElementById('dl-status-text');
    const pctEl = document.getElementById('dl-pct-text');
    const bar = document.getElementById('dl-progress-bar');
    if (btn) btn.disabled = true;
    if (wrap) wrap.style.display = 'block';
    if (statusEl) statusEl.textContent = 'Searching…';
    if (pctEl) pctEl.textContent = '0%';
    if (bar) bar.style.width = '0%';

    // FIX 19: animate progress bar while the blocking request is in-flight
    let _animPct = 0;
    const _animTimer = setInterval(() => {
      if (_animPct < 88) {
        _animPct += 2 + Math.random() * 4;
        const clamped = Math.min(_animPct, 88);
        if (bar) bar.style.width = clamped + '%';
        if (pctEl) pctEl.textContent = Math.floor(clamped) + '%';
      }
    }, 600);

    try {
      const res = await apiFetch('/admin/software/download', {
        method: 'POST',
        body: JSON.stringify({ name: query })
      });
      clearInterval(_animTimer);
      if (statusEl) statusEl.textContent = res.status === 'ok'
        ? `Downloaded via ${res.method}. Saved to ${res.destination || res.file || ''}. Size: ${res.size_mb ?? '?'} MB`
        : JSON.stringify(res);
      if (pctEl) pctEl.textContent = '100%';
      if (bar) bar.style.width = '100%';
      showToast('Download complete!', 'success');
      // Pre-fill upload tab
      const upPath = document.getElementById('up-filepath-input');
      if (upPath && res.file) upPath.value = (res.destination || '') + '/' + res.file;
      const toUpBtn = document.getElementById('dl-to-upload-btn');
      if (toUpBtn) toUpBtn.style.display = '';
    } catch(err) {
      clearInterval(_animTimer);
      if (bar) bar.style.width = '0%';
      if (pctEl) pctEl.textContent = '0%';
      if (statusEl) statusEl.textContent = 'Download failed: ' + err.message;
      showToast('Download failed: ' + err.message, 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function startUpload() {
    const filepath = (document.getElementById('up-filepath-input')?.value || '').trim();
    const releaseTag = (document.getElementById('up-tag-input')?.value || '').trim();
    const releaseName = (document.getElementById('up-displayname-input')?.value || '').trim();
    if (!filepath || !releaseTag) { showToast('File path and release tag are required.', 'error'); return; }

    const btn = document.getElementById('up-start-btn');
    const wrap = document.getElementById('up-progress-wrap');
    const statusEl = document.getElementById('up-status-text');
    const pctEl = document.getElementById('up-pct-text');
    const bar = document.getElementById('up-progress-bar');
    if (btn) btn.disabled = true;
    if (wrap) wrap.style.display = 'block';
    if (statusEl) statusEl.textContent = 'Uploading…';
    if (pctEl) pctEl.textContent = '0%';
    if (bar) bar.style.width = '0%';

    try {
      const res = await apiFetch('/admin/software/upload', {
        method: 'POST',
        body: JSON.stringify({ file_path: filepath, release_tag: releaseTag, release_name: releaseName || undefined })
      });
      if (statusEl) statusEl.textContent = `Uploaded: ${res.asset_name}. Catalog slug: ${res.slug}`;
      if (pctEl) pctEl.textContent = '100%';
      if (bar) bar.style.width = '100%';
      showToast('Upload complete! Catalog updated.', 'success');
    } catch(err) {
      if (statusEl) statusEl.textContent = 'Upload failed: ' + err.message;
      showToast('Upload failed: ' + err.message, 'error');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function saveGithubConfig() {
    const token = document.getElementById('gh-token').value.trim();
    const owner = document.getElementById('gh-owner').value.trim();
    const repo = document.getElementById('gh-repo').value.trim();
    // If token field is blank but was previously saved (shown as placeholder), skip sending empty token
    const payload = { owner, repo };
    if (token) payload.token = token;
    else payload.token = ''; // preserve old token if no new one entered — backend won't overwrite blank
    if (!owner || !repo) { showToast('Owner and Repo are required.', 'error'); return; }
    // FIX 7: warn if a new token was entered but not validated
    if (token) {
      const statusEl = document.getElementById('gh-validate-status');
      const validated = statusEl && statusEl.dataset.valid === 'true';
      if (!validated) {
        showToast('Tip: You entered a new token but didn\'t validate it. Saving anyway — use Validate Token to verify.', 'info');
      }
    }
    try {
      await apiFetch('/admin/config/github', { method: 'POST', body: JSON.stringify(payload) });
      showToast('GitHub config securely saved.', 'success');
      document.getElementById('admin-github-modal').classList.add('hidden');
    } catch(e) {
      showToast('Failed to save config: ' + e.message, 'error');
    }
  }

  // FIX 13: Validate Token against GitHub API
  async function validateGithubToken() {
    const btn = document.getElementById('gh-validate-btn');
    const statusEl = document.getElementById('gh-validate-status');
    if (btn) { btn.disabled = true; btn.textContent = 'Checking…'; }
    if (statusEl) statusEl.textContent = '';
    try {
      const res = await apiFetch('/admin/config/github/validate', { method: 'POST' });
      if (statusEl) {
        statusEl.style.color = '#4ade80';
        statusEl.textContent = `Valid — @${res.login} (${res.scopes || 'no scopes'})`;
        statusEl.dataset.valid = 'true';
      }
    } catch(err) {
      if (statusEl) {
        statusEl.style.color = '#f87171';
        statusEl.textContent = err.message;
        statusEl.dataset.valid = 'false';
      }
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Validate Token'; }
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Section routing
  // ═══════════════════════════════════════════════════════════════════════════

  const SECTION_TITLES = {
    overview:            'Overview',
    'system-status':     'System Status',
    users:               'Users',
    installations:       'Installations',
    conversations:       'Conversations',
    preferences:         'Preferences',
    software:            'Software Catalog',
    sessions:            'Sessions',
    'admin-management':  'Admin Management',
    'software-manager':  'Software Manager',
  };

  // FIX 14: standalone chart loader so Users section can render growth chart without loading overview stats
  async function loadUserGrowthChart() {
    try {
      const d = await apiFetch('/admin/dashboard-stats');
      const elGrowth = document.getElementById('chart-user-growth');
      if (elGrowth && d.users_by_day) {
        let cumulative = 0;
        const growthData = [...d.users_by_day].reverse().map(r => { cumulative += r.c; return { value: cumulative }; });
        elGrowth.innerHTML = drawLineChart(growthData, 300, 100, '#06b6d4');
      }
    } catch (_) {}
  }

  const SECTION_LOADERS = {
    overview:            () => { loadStats(); loadOverviewInstalls(); },
    'system-status':     loadSystemStatus,
    // FIX 14: also render growth chart when navigating directly to Users
    users:               () => { loadUsers(); loadUserGrowthChart(); },
    installations:       loadInstallations,
    conversations:       loadConversations,
    preferences:         loadPreferences,
    software:            loadCatalog,
    sessions:            loadSessions,
    'admin-management':  loadAdmins,
    'software-manager':  () => {},
  };

  let _currentSection = 'overview';

  function switchSection(section) {
    if (!SECTION_LOADERS[section]) return;
    _currentSection = section;

    document.querySelectorAll('.admin-nav-item').forEach(el => {
      el.classList.toggle('active', el.dataset.section === section);
    });
    document.querySelectorAll('.admin-section').forEach(el => {
      el.classList.toggle('hidden', el.id !== `section-${section}`);
    });

    const titleEl = document.getElementById('admin-page-title');
    if (titleEl) titleEl.textContent = SECTION_TITLES[section] || section;

    SECTION_LOADERS[section]();
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Global delegated event listeners
  // ═══════════════════════════════════════════════════════════════════════════

  function wireContentEvents() {
    document.getElementById('admin-content').addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;

      if (action === 'delete-user')        { deleteUser(btn.dataset.id, btn.dataset.email); }
      else if (action === 'deactivate-user') { deactivateUser(btn.dataset.id, btn.dataset.email); }
      else if (action === 'reactivate-user') { reactivateUser(btn.dataset.id, btn.dataset.email); }
      else if (action === 'cancel-task')     { cancelTask(btn.dataset.id); }
      else if (action === 'revoke-session')  { revokeSession(btn.dataset.token); }
      else if (action === 'edit-pref')       { enterPrefEditMode(btn.dataset.key, btn.dataset.value, btn.dataset.uid); }
      else if (action === 'save-pref')       { savePref(btn.dataset.key, btn.dataset.uid); }
      else if (action === 'cancel-pref')     { cancelPrefEdit(btn.dataset.key, btn.dataset.value, btn.dataset.uid); }
      else if (action === 'edit-software')   { openSoftwareModal(true, btn.dataset); }
      else if (action === 'delete-software') { deleteSoftware(btn.dataset.slug); }
      else if (action === 'reset-pw')        { openResetPwModal(btn.dataset.id, btn.dataset.email); }
      else if (action === 'revoke-admin')    { revokeAdmin(btn.dataset.id, btn.dataset.email); }
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Logout
  // ═══════════════════════════════════════════════════════════════════════════

  async function adminLogout() {
    const token = getToken();
    if (token) {
      try {
        await fetch(`${BASE}/auth/logout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        });
      } catch (_) {}
    }
    localStorage.removeItem('aurios_auth_token');
    localStorage.removeItem('aurios_user_role');
    document.getElementById('admin-view')?.classList.add('hidden');
    document.getElementById('auth-view')?.classList.remove('hidden');
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Window controls
  // ═══════════════════════════════════════════════════════════════════════════

  function wireWindowControls() {
    const min = document.getElementById('admin-btn-minimize');
    const max = document.getElementById('admin-btn-maximize');
    const cls = document.getElementById('admin-btn-close');
    if (min) min.addEventListener('click', () => window.api?.minimize?.());
    if (max) max.addEventListener('click', () => window.api?.maximize?.());
    if (cls) cls.addEventListener('click', () => window.api?.close?.());
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Init
  // ═══════════════════════════════════════════════════════════════════════════

  window.initAdmin = function () {
    wireWindowControls();
    startClock();
    wireContentEvents();

    // Nav item clicks
    document.querySelectorAll('.admin-nav-item').forEach(el => {
      el.addEventListener('click', () => switchSection(el.dataset.section));
    });

    // Topbar: refresh current section (full handler with animation registered below)

    // Topbar: section action buttons
    document.getElementById('clear-history-btn')
      ?.addEventListener('click', clearConversations);
    document.getElementById('reset-prefs-btn')
      ?.addEventListener('click', resetAllPreferences);
    document.getElementById('catalog-refresh-btn')
      ?.addEventListener('click', refreshCatalog);
    document.getElementById('add-software-btn')
      ?.addEventListener('click', () => openSoftwareModal(false));
    document.getElementById('sw-modal-cancel')
      ?.addEventListener('click', closeSoftwareModal);
    document.getElementById('sw-modal-save')
      ?.addEventListener('click', saveSoftwareModal);
      
    document.getElementById('add-admin-btn')?.addEventListener('click', openCreateAdminModal);
    document.getElementById('create-admin-cancel')?.addEventListener('click', () => document.getElementById('admin-create-modal').classList.add('hidden'));
    document.getElementById('create-admin-save')?.addEventListener('click', submitCreateAdmin);
    
    document.getElementById('reset-pw-cancel')?.addEventListener('click', () => document.getElementById('admin-reset-pw-modal').classList.add('hidden'));
    document.getElementById('reset-pw-save')?.addEventListener('click', submitResetPw);
    
    document.getElementById('tab-download-btn')?.addEventListener('click', () => {
      document.getElementById('sw-tab-download').classList.remove('hidden');
      document.getElementById('sw-tab-upload').classList.add('hidden');
      document.getElementById('tab-download-btn').classList.add('active');
      document.getElementById('tab-upload-btn').classList.remove('active');
    });
    document.getElementById('tab-upload-btn')?.addEventListener('click', () => {
      document.getElementById('sw-tab-upload').classList.remove('hidden');
      document.getElementById('sw-tab-download').classList.add('hidden');
      document.getElementById('tab-upload-btn').classList.add('active');
      document.getElementById('tab-download-btn').classList.remove('active');
    });
    document.getElementById('dl-to-upload-btn')?.addEventListener('click', () => {
      document.getElementById('tab-upload-btn').click();
    });
    
    document.getElementById('dl-start-btn')?.addEventListener('click', startDownload);
    document.getElementById('up-start-btn')?.addEventListener('click', startUpload);
    
    // FIX 12: load existing GitHub config when modal opens to pre-fill owner/repo fields
    document.getElementById('github-settings-btn')?.addEventListener('click', async () => {
      document.getElementById('admin-github-modal').classList.remove('hidden');
      // Reset validate status
      const statusEl = document.getElementById('gh-validate-status');
      if (statusEl) statusEl.textContent = '';
      try {
        const cfg = await apiFetch('/admin/config/github');
        const ownerEl = document.getElementById('gh-owner');
        const repoEl  = document.getElementById('gh-repo');
        const tokenEl = document.getElementById('gh-token');
        if (ownerEl && cfg.owner) ownerEl.value = cfg.owner;
        if (repoEl  && cfg.repo)  repoEl.value  = cfg.repo;
        if (tokenEl) {
          tokenEl.value = '';
          tokenEl.placeholder = cfg.token_set ? '●●●●●●●● (saved — leave blank to keep)' : 'GitHub personal access token';
        }
      } catch (_) {}
    });
    document.getElementById('gh-modal-cancel')?.addEventListener('click', () => document.getElementById('admin-github-modal').classList.add('hidden'));
    document.getElementById('gh-modal-save')?.addEventListener('click', saveGithubConfig);
    // FIX 13: wire Validate Token button
    document.getElementById('gh-validate-btn')?.addEventListener('click', validateGithubToken);


    // Logout
    document.getElementById('admin-logout-btn')
      ?.addEventListener('click', adminLogout);

    // Start status poller
    setInterval(async () => {
      const el = document.getElementById('admin-status-backend');
      if (!el) return;
      try {
        await apiFetch('/ping');
        el.innerHTML = '<span class="status-dot connected"></span>Backend: Connected';
      } catch (_) {
        el.innerHTML = '<span class="status-dot disconnected"></span>Backend: Disconnected';
      }
    }, 5000);

    // Refresh animation
    document.getElementById('admin-refresh-btn')?.addEventListener('click', function() {
      const icon = this.querySelector('.refresh-icon');
      const text = this.querySelector('.refresh-text');
      if (icon) icon.style.animation = 'spin 1s linear infinite';
      if (text) text.textContent = 'Refreshing...';
      this.disabled = true;
      
      const loader = SECTION_LOADERS[_currentSection];
      if (loader) {
        Promise.resolve(loader()).finally(() => {
          if (icon) { icon.style.animation = 'none'; icon.innerHTML = '<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>'; }
          if (text) text.textContent = 'Updated';
          setTimeout(() => {
            if (icon) icon.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3.5"/></svg>';
            if (text) text.textContent = 'Refresh';
            this.disabled = false;
          }, 1500);
        });
      }
    });

    // Load default section
    switchSection('overview');

    // System-status auto-refresh: every 10s, only when that section is visible
    setInterval(() => {
      if (_currentSection === 'system-status') loadSystemStatus();
    }, 10000);
  };
})();
