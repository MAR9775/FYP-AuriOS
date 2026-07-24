/* progress-panel.js — Sequential installation progress panel with overall percentage */

(function () {

  // ── Inject panel HTML ───────────────────────────────────────────────────────
  document.body.insertAdjacentHTML('beforeend', `
    <div id="progress-panel" class="panel-hidden">
      <div id="panel-header">
        <div id="panel-title">Installing: <span id="panel-preset-name"></span></div>
        <div id="panel-overall-wrap">
          <div id="panel-overall-track">
            <div id="panel-overall-fill"></div>
          </div>
          <span id="panel-pct">0%</span>
        </div>
      </div>
      <div id="panel-steps"></div>
      <div id="panel-footer">
        <button id="cancel-btn">Cancel</button>
        <span id="panel-counter">0 of 0 done</span>
      </div>
    </div>
  `);

  // ── Constants ───────────────────────────────────────────────────────────────

  const STATUS_ICONS = {
    pending:     '<svg width="14" height="14" fill="none" stroke="#64748b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/></svg>',
    in_progress: '<svg width="14" height="14" fill="none" stroke="#f97316" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    done:        '<svg width="14" height="14" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    failed:      '<svg width="14" height="14" fill="none" stroke="#f87171" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
  };

  const STEP_DISPLAY_NAMES = {
    detection:   'Resolving package...',
    download:    'Downloading...',
    install:     'Installing silently...',
    configure:   'Finalizing setup...',
    validate:    'Verifying installation...',
    environment: 'Environment Setup',
  };

  const STATUS_MAP = {
    pending:     'pending',
    running:     'in_progress',
    in_progress: 'in_progress',
    done:        'done',
    completed:   'done',
    error:       'failed',
    failed:      'failed',
    cancelled:   'failed',
  };

  // ── State ───────────────────────────────────────────────────────────────────

  let _steps      = [];     // [{id, name}, …] in order
  let _stepStates = {};     // {stepId: 'pending'|'in_progress'|'done'|'failed'}
  let _stepProgress = {};   // {stepId: 0-100}
  let _taskId     = null;

  // ── DOM helpers ─────────────────────────────────────────────────────────────

  const $panel    = () => document.getElementById('progress-panel');
  const $steps    = () => document.getElementById('panel-steps');
  const $counter  = () => document.getElementById('panel-counter');
  const $pct      = () => document.getElementById('panel-pct');
  const $ovFill   = () => document.getElementById('panel-overall-fill');

  // ── showPanel ───────────────────────────────────────────────────────────────
  function showPanel(presetName, steps, taskId) {
    _taskId = taskId || null;

    _steps = steps.map(s =>
      typeof s === 'string'
        ? { id: s, name: STEP_DISPLAY_NAMES[s] || _titleCase(s) }
        : s
    );
    _stepStates   = {};
    _stepProgress = {};
    _steps.forEach(s => {
      _stepStates[s.id]   = 'pending';
      _stepProgress[s.id] = 0;
    });

    // Reset header
    const headerEl = document.getElementById('panel-title');
    if (headerEl) {
      headerEl.style.color = ''; // Reset color from previous runs
      headerEl.innerHTML = 'Installing: <span id="panel-preset-name"></span>';
      document.getElementById('panel-preset-name').textContent = presetName;
    }
    const overallFill = document.getElementById('panel-overall-fill');
    if (overallFill) overallFill.style.width = '0%';
    const pctEl = document.getElementById('panel-pct');
    if (pctEl) pctEl.textContent = '0%';

    // Render step rows
    $steps().innerHTML = '';
    _steps.forEach(s => {
      const row = document.createElement('div');
      row.className = 'step-row step-pending';
      row.id        = `step-row-${s.id}`;
      row.innerHTML = `
        <div class="step-row-main">
          <span class="step-icon" id="step-icon-${s.id}">${STATUS_ICONS.pending}</span>
          <span class="step-name">${s.name}</span>
          <span class="step-status-text" id="step-status-${s.id}">Pending</span>
        </div>
        <div class="step-progress-track" id="step-track-${s.id}">
          <div class="step-progress-fill" id="step-fill-${s.id}"></div>
        </div>
      `;
      $steps().appendChild(row);
    });

    _updateCounter();
    _updateOverall();

    // Slide in
    const p = $panel();
    p.classList.remove('panel-visible');
    p.classList.add('panel-hidden');
    document.body.classList.add('has-progress');
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        p.classList.remove('panel-hidden');
        p.classList.add('panel-visible');
      });
    });
  }

  // ── updateStep ──────────────────────────────────────────────────────────────
  function updateStep(data) {
    const { step, status, progress, message } = data;

    // Terminal signal with no specific step -- all done or all failed
    if (!step) {
      if (status === 'done' || status === 'completed') {
        _onAllDone(false);
      } else if (status === 'failed' || status === 'error' || status === 'cancelled') {
        _onAllDone(true);
      }
      return;
    }

    const mapped = STATUS_MAP[status] || 'pending';

    // ── Enforce sequential order ────────────────────────────────────────────
    // If this step is now active, done, or failed, forcefully complete all preceding steps.
    if (['in_progress', 'done', 'failed'].includes(mapped)) {
      const idx = _steps.findIndex(s => s.id === step);
      if (idx > 0) {
        for (let i = 0; i < idx; i++) {
          const prevId = _steps[i].id;
          if (_stepStates[prevId] !== 'done' && _stepStates[prevId] !== 'failed') {
            _stepStates[prevId] = 'done';
            _stepProgress[prevId] = 100;
            _applyStepState(prevId, 'done', 100, null);
          }
        }
      }
    }

    // If this step is done, set its bar to 100%. If running, show an indeterminate 50%
    const pct = (mapped === 'done') ? 100 : (mapped === 'in_progress' ? 50 : 0);
    _stepProgress[step] = pct;
    _stepStates[step]   = mapped;
    _applyStepState(step, mapped, pct, message);

    _updateCounter();
    _updateOverall(progress);

    // Auto-complete check
    const allTerminal = _steps.length > 0 && _steps.every(
      s => _stepStates[s.id] === 'done' || _stepStates[s.id] === 'failed'
    );
    if (allTerminal) {
      const anyFailed = _steps.some(s => _stepStates[s.id] === 'failed');
      _onAllDone(anyFailed);
    }
  }

  // ── _applyStepState — mutate DOM for one step ───────────────────────────────
  function _applyStepState(stepId, mapped, pct, message) {
    const iconEl   = document.getElementById(`step-icon-${stepId}`);
    const statusEl = document.getElementById(`step-status-${stepId}`);
    const trackEl  = document.getElementById(`step-track-${stepId}`);
    const fillEl   = document.getElementById(`step-fill-${stepId}`);
    const rowEl    = document.getElementById(`step-row-${stepId}`);

    if (!iconEl) return;

    const LABELS = { pending: 'Pending', in_progress: 'Running…', done: 'Done', failed: 'Failed' };

    iconEl.innerHTML     = STATUS_ICONS[mapped]  || STATUS_ICONS.pending;
    statusEl.textContent = message               || LABELS[mapped] || mapped;

    // Update row class for styling
    if (rowEl) {
      rowEl.className = `step-row step-${mapped}`;
    }

    // Progress bar visibility
    if (trackEl && fillEl) {
      if (mapped === 'in_progress' || mapped === 'done') {
        trackEl.style.display = 'block';
        fillEl.style.width    = `${pct ?? 0}%`;
      } else {
        trackEl.style.display = 'none';
        fillEl.style.width    = '0%';
      }
    }
  }

  // ── _updateOverall — recalculate and render overall percentage ──────────────
  function _updateOverall(backendProgress) {
    const total = _steps.length;
    if (total === 0) return;

    let overall = backendProgress != null ? backendProgress : 0;
    if (overall > 100) overall = 100;
    if (overall < 0) overall = 0;

    const fillEl = $ovFill();
    const pctEl  = $pct();
    if (fillEl) fillEl.style.width = `${overall}%`;
    if (pctEl)  pctEl.textContent  = `${overall}%`;
  }

  // ── _updateCounter ──────────────────────────────────────────────────────────
  function _updateCounter() {
    const total = _steps.length;
    const done  = _steps.filter(s => _stepStates[s.id] === 'done').length;
    const el    = $counter();
    if (el) el.textContent = `${done} of ${total} done`;
  }

  // ── hidePanel ───────────────────────────────────────────────────────────────
  function hidePanel() {
    const p = $panel();
    p.classList.remove('panel-visible');
    p.classList.add('panel-hidden');
    document.body.classList.remove('has-progress');
    setTimeout(() => {
      $steps().innerHTML = '';
      _steps        = [];
      _stepStates   = {};
      _stepProgress = {};
      _taskId       = null;
    }, 350);
  }

  // ── _onAllDone ──────────────────────────────────────────────────────────────
  function _onAllDone(hadFailures) {
    if (!hadFailures) {
      _steps.forEach(s => {
        if (_stepStates[s.id] !== 'done' && _stepStates[s.id] !== 'failed') {
          _stepStates[s.id] = 'done';
          _stepProgress[s.id] = 100;
          _applyStepState(s.id, 'done', 100, null);
        }
      });
    }

    // Complete the overall bar
    const fillEl = $ovFill();
    const pctEl  = $pct();
    if (fillEl) fillEl.style.width = '100%';
    if (pctEl)  pctEl.textContent  = '100%';

    const titleEl = document.getElementById('panel-title');
    if (titleEl) {
      if (hadFailures) {
        titleEl.innerHTML = '<svg width="14" height="14" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true" style="vertical-align:-2px;margin-right:6px"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>Completed with errors';
        titleEl.style.color = '#f59e0b';
      } else {
        titleEl.innerHTML = '<svg width="14" height="14" fill="none" stroke="#4ade80" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true" style="vertical-align:-2px;margin-right:6px"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>All Done!';
        titleEl.style.color = '#4ade80';
      }
    }

    setTimeout(() => {
      hidePanel();
      const finalMsg = window.__auriFinalMsg;
      _emitBubble(
        hadFailures
          ? (finalMsg || 'Installation finished with some issues. Check the logs for details.')
          : (finalMsg || "Everything is set up and ready to go. Let me know what you'd like to build.")
      );
      window.__auriFinalMsg = null;
    }, 3000);
  }

  // ── Cancel ──────────────────────────────────────────────────────────────────
  document.getElementById('cancel-btn').addEventListener('click', async () => {
    if (_taskId) {
      try { await window.api.cancelTask(_taskId); } catch (_) {}
    }
    hidePanel();
    _emitBubble("Installation cancelled. Let me know when you're ready.");
  });

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function _emitBubble(text) {
    if (typeof renderMessage === 'function') renderMessage('assistant', text);
  }

  function _titleCase(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  // ── Public API ───────────────────────────────────────────────────────────────
  window.progressPanel = { showPanel, updateStep, hidePanel };

})();
