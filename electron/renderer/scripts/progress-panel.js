/* progress-panel.js — Installation progress side panel with real-time WebSocket updates */

(function () {

  // ── Inject panel HTML into body ────────────────────────────────────────────
  document.body.insertAdjacentHTML('beforeend', `
    <div id="progress-panel" class="panel-hidden">
      <div id="panel-header">Installing: <span id="panel-preset-name"></span></div>
      <div id="panel-steps"></div>
      <div id="panel-footer">
        <button id="cancel-btn">✕ Cancel</button>
        <span id="panel-counter">0 of 0 done</span>
      </div>
    </div>
  `);

  // ── Constants ───────────────────────────────────────────────────────────────

  const STATUS_ICONS = {
    pending:     '⬜',
    in_progress: '⏳',
    done:        '✅',
    failed:      '❌',
  };

  const STATUS_LABELS = {
    pending:     'Pending',
    in_progress: 'In Progress…',
    done:        'Done',
    failed:      'Failed',
  };

  const STEP_DISPLAY_NAMES = {
    detection:   'System Check',
    download:    'Download',
    install:     'Install',
    configure:   'Configure',
    validate:    'Validate',
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

  let _steps      = [];      // [{id, name}, …]
  let _stepStates = {};      // {stepId: 'pending'|'in_progress'|'done'|'failed'}
  let _taskId     = null;

  // ── DOM helpers ─────────────────────────────────────────────────────────────

  const $panel   = () => document.getElementById('progress-panel');
  const $steps   = () => document.getElementById('panel-steps');
  const $counter = () => document.getElementById('panel-counter');
  const $header  = () => document.getElementById('panel-header');

  // ── showPanel ───────────────────────────────────────────────────────────────
  function showPanel(presetName, steps, taskId) {
    _taskId = taskId || null;

    // Normalise steps to [{id, name}]
    _steps = steps.map(s =>
      typeof s === 'string'
        ? { id: s, name: STEP_DISPLAY_NAMES[s] || _titleCase(s) }
        : s
    );
    _stepStates = {};
    _steps.forEach(s => { _stepStates[s.id] = 'pending'; });

    // Reset header
    $header().innerHTML = 'Installing: <span id="panel-preset-name"></span>';
    document.getElementById('panel-preset-name').textContent = presetName;

    // Render step rows
    $steps().innerHTML = '';
    _steps.forEach(s => {
      const row = document.createElement('div');
      row.className  = 'step-row';
      row.id         = `step-row-${s.id}`;
      row.innerHTML  = `
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

    // Slide in (double rAF to ensure transition fires after class change)
    const p = $panel();
    p.classList.remove('panel-visible');
    p.classList.add('panel-hidden');
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

    // Terminal signal with no specific step → all done or all failed
    if (!step) {
      if (status === 'done' || status === 'completed') {
        _onAllDone(false);
      } else if (status === 'failed' || status === 'error' || status === 'cancelled') {
        _onAllDone(true);
      }
      return;
    }

    const mapped = STATUS_MAP[status] || 'pending';
    _stepStates[step] = mapped;

    const iconEl   = document.getElementById(`step-icon-${step}`);
    const statusEl = document.getElementById(`step-status-${step}`);
    const trackEl  = document.getElementById(`step-track-${step}`);
    const fillEl   = document.getElementById(`step-fill-${step}`);

    if (iconEl)   iconEl.textContent   = STATUS_ICONS[mapped]  || STATUS_ICONS.pending;
    if (statusEl) statusEl.textContent = message               || STATUS_LABELS[mapped] || mapped;

    if (trackEl && fillEl) {
      if (mapped === 'in_progress' && progress != null) {
        trackEl.style.display = 'block';
        fillEl.style.width    = `${progress}%`;
      } else {
        trackEl.style.display = 'none';
      }
    }

    _updateCounter();

    // Check if every step has reached a terminal state
    const allTerminal = _steps.length > 0 && _steps.every(
      s => _stepStates[s.id] === 'done' || _stepStates[s.id] === 'failed'
    );
    if (allTerminal) {
      const anyFailed = _steps.some(s => _stepStates[s.id] === 'failed');
      _onAllDone(anyFailed);
    }
  }

  // ── hidePanel ───────────────────────────────────────────────────────────────
  function hidePanel() {
    const p = $panel();
    p.classList.remove('panel-visible');
    p.classList.add('panel-hidden');
    // Clear state after slide-out completes
    setTimeout(() => {
      $steps().innerHTML = '';
      _steps      = [];
      _stepStates = {};
      _taskId     = null;
    }, 350);
  }

  // ── _onAllDone ──────────────────────────────────────────────────────────────
  function _onAllDone(hadFailures) {
    const h = $header();
    if (hadFailures) {
      h.textContent  = '⚠️ Completed with errors';
      h.style.color  = '#f59e0b';
    } else {
      h.textContent  = '✅ All Done!';
      h.style.color  = '#4ade80';
    }

    setTimeout(() => {
      hidePanel();
      _emitBubble(
        hadFailures
          ? 'Installation finished with some issues. Check the logs for details. 🔍'
          : "Everything's set up and ready to go! Let me know what you'd like to build. 🚀"
      );
    }, 3000);
  }

  // ── Cancel button ───────────────────────────────────────────────────────────
  document.getElementById('cancel-btn').addEventListener('click', async () => {
    if (_taskId) {
      try {
        await window.api.cancelTask(_taskId);
      } catch (_) {}
    }
    hidePanel();
    _emitBubble("Installation cancelled. Let me know when you're ready! 🙌");
  });

  // ── Helpers ─────────────────────────────────────────────────────────────────

  function _updateCounter() {
    const total = _steps.length;
    const done  = _steps.filter(s => _stepStates[s.id] === 'done').length;
    const el    = $counter();
    if (el) el.textContent = `${done} of ${total} done`;
  }

  function _emitBubble(text) {
    if (typeof renderMessage === 'function') {
      renderMessage('assistant', text);
    }
  }

  function _titleCase(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  // ── Public API ───────────────────────────────────────────────────────────────
  window.progressPanel = { showPanel, updateStep, hidePanel };

})();
