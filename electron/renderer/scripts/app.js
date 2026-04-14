/* app.js — Chat logic, dashboard, view routing, suggestions, status bar */

const chatMessages  = document.getElementById('chat-messages');
const chatInput     = document.getElementById('chat-input');
const sendBtn       = document.getElementById('send-btn');
const typingEl      = document.getElementById('typing-indicator');
const dashboardView = document.getElementById('dashboard-view');
const suggestionsEl = document.getElementById('suggestions-dropdown');

let userName         = 'there';
let lastSystemStatus = null;
let backendOffline   = false;
let backendRetryTmr  = null;
let lastAuriReply    = '';
let currentView      = 'dashboard';   // 'dashboard' | 'chat'
let suggestionIndex  = -1;

// ── Suggestions list ──────────────────────────────────────────────────────────
const SUGGESTIONS = [
  'Set up Python development environment',
  'Install machine learning tools',
  'Create a new React project',
  'Configure PostgreSQL database',
  'Install Node.js and npm',
  'Set up Git and GitHub',
  'Install Visual Studio Code',
  'Configure Windows Subsystem for Linux',
  'Install Docker Desktop',
  'Set up Java development environment',
  'Install MongoDB',
  'Install Anaconda for data science',
  'Configure SSH keys for GitHub',
  'Install Redis',
  'Set up a virtual environment in Python',
];

// ── Time-based greeting ───────────────────────────────────────────────────────
function getGreeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

// ── View management ───────────────────────────────────────────────────────────
function showDashboard() {
  currentView = 'dashboard';
  dashboardView.classList.remove('hidden');
  dashboardView.classList.add('view-enter');
  chatMessages.classList.add('hidden');
  setTimeout(() => dashboardView.classList.remove('view-enter'), 350);
}

function showChat() {
  if (currentView === 'chat') return;
  currentView = 'chat';
  chatMessages.classList.remove('hidden');
  chatMessages.classList.add('view-enter');
  dashboardView.classList.add('hidden');
  setTimeout(() => chatMessages.classList.remove('view-enter'), 350);
}

// ── Template cards ────────────────────────────────────────────────────────────
document.querySelectorAll('.template-card').forEach(card => {
  card.addEventListener('click', () => {
    const prompt = card.dataset.prompt;
    if (!prompt) return;
    chatInput.value = prompt;
    autoResizeTextarea();
    updateSendBtnState();
    showChat();
    sendMessage();
  });
});

// ── Recent history items ──────────────────────────────────────────────────────
function addRecentItem(text) {
  const list = document.getElementById('recent-list');
  const section = document.getElementById('recent-section');
  if (!list) return;

  // Avoid duplicate entries
  const existing = Array.from(list.children).find(el =>
    el.querySelector('.recent-text')?.textContent === text
  );
  if (existing) return;

  const item = document.createElement('div');
  item.className = 'recent-item';
  item.innerHTML = `<span class="recent-item-icon">💬</span>
    <span class="recent-text">${text}</span>`;
  item.addEventListener('click', () => {
    chatInput.value = text;
    autoResizeTextarea();
    updateSendBtnState();
    showChat();
  });
  list.insertBefore(item, list.firstChild);

  // Keep max 5 recent items
  while (list.children.length > 5) list.removeChild(list.lastChild);
  if (section) section.style.display = '';
}

// ── Textarea auto-resize ──────────────────────────────────────────────────────
function autoResizeTextarea() {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
}

// ── Suggestions ───────────────────────────────────────────────────────────────
function showSuggestions(query) {
  const q = query.trim().toLowerCase();
  if (!q || q.length < 2) { hideSuggestions(); return; }

  const matches = SUGGESTIONS.filter(s => s.toLowerCase().includes(q)).slice(0, 6);
  if (!matches.length) { hideSuggestions(); return; }

  suggestionsEl.innerHTML = '';
  suggestionIndex = -1;
  matches.forEach((s, i) => {
    const item = document.createElement('div');
    item.className = 'suggestion-item';
    item.textContent = s;
    item.addEventListener('mousedown', (e) => {
      e.preventDefault();   // keep focus on input
      chatInput.value = s;
      autoResizeTextarea();
      updateSendBtnState();
      hideSuggestions();
    });
    suggestionsEl.appendChild(item);
  });
  suggestionsEl.classList.remove('hidden');
}

function hideSuggestions() {
  suggestionsEl.classList.add('hidden');
  suggestionIndex = -1;
}

function navigateSuggestions(dir) {
  const items = suggestionsEl.querySelectorAll('.suggestion-item');
  if (!items.length) return;
  items[suggestionIndex]?.classList.remove('active');
  suggestionIndex = (suggestionIndex + dir + items.length) % items.length;
  const active = items[suggestionIndex];
  active.classList.add('active');
  active.scrollIntoView({ block: 'nearest' });
}

// ── Send-button state ─────────────────────────────────────────────────────────
function updateSendBtnState() {
  const empty = chatInput.value.trim().length === 0;
  sendBtn.disabled = empty;
  sendBtn.classList.toggle('disabled', empty);
}

chatInput.addEventListener('input', () => {
  updateSendBtnState();
  autoResizeTextarea();
  showSuggestions(chatInput.value);
});

chatInput.addEventListener('keydown', (e) => {
  if (!suggestionsEl.classList.contains('hidden')) {
    if (e.key === 'ArrowDown')  { e.preventDefault(); navigateSuggestions(1);  return; }
    if (e.key === 'ArrowUp')    { e.preventDefault(); navigateSuggestions(-1); return; }
    if (e.key === 'Tab' || (e.key === 'Enter' && suggestionIndex >= 0)) {
      e.preventDefault();
      const active = suggestionsEl.querySelector('.suggestion-item.active') ||
                     suggestionsEl.querySelector('.suggestion-item');
      if (active) {
        chatInput.value = active.textContent;
        autoResizeTextarea();
        updateSendBtnState();
        hideSuggestions();
      }
      return;
    }
    if (e.key === 'Escape') { hideSuggestions(); return; }
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

chatInput.addEventListener('blur', () => {
  setTimeout(hideSuggestions, 150);
});

// ── Backend-offline banner ────────────────────────────────────────────────────
function showBackendBanner() {
  if (backendOffline) return;
  backendOffline = true;
  const banner = document.getElementById('backend-banner');
  if (banner) banner.classList.remove('hidden');
  if (!backendRetryTmr) backendRetryTmr = setInterval(retryBackend, 10000);
}

function hideBackendBanner() {
  backendOffline = false;
  const banner = document.getElementById('backend-banner');
  if (banner) banner.classList.add('hidden');
  if (backendRetryTmr) { clearInterval(backendRetryTmr); backendRetryTmr = null; }
}

async function retryBackend() {
  try {
    const s = await window.api.getStatus();
    if (s && typeof s === 'object' && ('ollama_connected' in s || 'installed' in s)) {
      lastSystemStatus = s;
      applyStatusUI(s);
      hideBackendBanner();
    }
  } catch (_) {}
}

// ── sendMessage ───────────────────────────────────────────────────────────────
async function sendMessage() {
  const text = chatInput.value.trim();
  if (!text) return;

  hideSuggestions();

  // Voice on-demand
  const VOICE_RE = /\b(bolo|bolein|bol|batao|padhein|parho|parh|awaaz mein|voice mein|audio mein|read aloud|read out|speak|say it|out loud|sunao|suna do)\b/i;
  if (VOICE_RE.test(text)) {
    chatInput.value = '';
    autoResizeTextarea();
    updateSendBtnState();
    if (lastAuriReply && window.tts && typeof window.tts.speak === 'function') {
      renderMessage('assistant', 'Sure! Bol rahi hoon... 🔊');
      window.tts.speak(lastAuriReply);
    } else {
      renderMessage('assistant', 'Abhi tak kuch nahi kaha maine! Pehle kuch poochho 😊');
    }
    return;
  }

  // Pre-flight admin / disk checks
  const INSTALL_RE = /\b(install|set ?up|download|laga do|install karo)\b/i;
  if (INSTALL_RE.test(text) && lastSystemStatus) {
    if (!lastSystemStatus.is_admin) {
      renderMessage('assistant',
        '⚠️ Heads up! AuriOS may need admin privileges to install software. ' +
        'If installation fails, try restarting as Administrator 🔐');
    } else if (lastSystemStatus.free_disk_gb < 1.0) {
      renderMessage('assistant',
        `⚠️ You only have ${lastSystemStatus.free_disk_gb}GB free — ` +
        `installations need ~2GB. Consider freeing up space first 💾`);
    }
  }

  // Switch to chat view before rendering
  showChat();

  renderMessage('user', text);
  addRecentItem(text);

  chatInput.value = '';
  autoResizeTextarea();
  updateSendBtnState();

  await new Promise(resolve => setTimeout(resolve, 3500 + Math.random() * 1000));
  showTyping(true);

  try {
    const res = await window.api.sendMessage(text);
    showTyping(false);

    const reply = res.response_text || res.response || res.message || JSON.stringify(res);

    if (
      res.error === 'ollama_offline' ||
      (typeof reply === 'string' && /ollama.*not.*running|cannot.*reach.*ollama/i.test(reply))
    ) {
      const offlineMsg = "Hmm, main apne brain tak nahi pahunch rahi! Ollama chal raha hai? 🧠 Try: ollama serve";
      lastAuriReply = offlineMsg;
      renderMessage('assistant', offlineMsg);
    } else {
      lastAuriReply = reply;
      renderMessage('assistant', reply);
    }

    if (res.task_id) {
      const presetName = res.preset_or_software || 'Software';
      const steps = ['detection', 'download', 'install', 'configure', 'validate', 'environment'];
      if (window.progressPanel && typeof window.progressPanel.showPanel === 'function') {
        window.progressPanel.showPanel(presetName, steps, res.task_id);
      }
      connectProgressSocket(res.task_id);
    }
  } catch (err) {
    showTyping(false);
    showBackendBanner();
    renderMessage('assistant', '⚠️ Could not reach backend. Is the server running?');
  }
}

// ── renderMessage ─────────────────────────────────────────────────────────────
function renderMessage(role, content, timestamp) {
  const wrapper = document.createElement('div');
  wrapper.className = `message ${role === 'user' ? 'user' : 'auri'}`;

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = content;

  const ts = document.createElement('span');
  ts.className = 'msg-timestamp';
  const t = timestamp ? new Date(timestamp) : new Date();
  ts.textContent = t.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

  wrapper.appendChild(bubble);
  wrapper.appendChild(ts);
  chatMessages.appendChild(wrapper);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ── showTyping ────────────────────────────────────────────────────────────────
function showTyping(show) {
  typingEl.classList.toggle('hidden', !show);
  if (show) chatMessages.scrollTop = chatMessages.scrollHeight;
}

// ── connectProgressSocket ─────────────────────────────────────────────────────
function connectProgressSocket(taskId) {
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsBase = window.location.host ? `${wsProto}//${window.location.host}` : 'ws://127.0.0.1:8000';
  const ws = new WebSocket(`${wsBase}/ws/progress/${taskId}`);
  let completed   = false;
  let dlFailCount = 0;

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.step === 'download') {
        const msg = (data.message || '').toLowerCase();

        if (msg.includes('no internet') || msg.includes('connection error') ||
            msg.includes('network') || msg.includes('connectionerror')) {
          data.message = 'Oops! No internet connection 📡';
          if (window.progressPanel) window.progressPanel.updateStep(data);
          renderMessage('assistant', "Looks like we're offline! Already downloaded files still work 📦");
          return;
        }

        if (msg.includes('retrying') || msg.includes('retry')) {
          dlFailCount++;
          const match = data.message.match(/\((\d+)\/(\d+)\)/);
          const cur = match ? match[1] : dlFailCount;
          const max = match ? match[2] : 3;
          data.message = `Download failed. Retrying... (${cur}/${max}) 🔄`;
          if (window.progressPanel) window.progressPanel.updateStep(data);
          return;
        }

        if ((data.status === 'failed' || data.status === 'error') && dlFailCount >= 3) {
          data.message = '❌ Download failed after 3 attempts';
          if (window.progressPanel) window.progressPanel.updateStep(data);
          return;
        }
      }

      if (data.status === 'completed' || data.status === 'done') completed = true;
      if (window.progressPanel && typeof window.progressPanel.updateStep === 'function') {
        window.progressPanel.updateStep(data);
      }
      // Stash the backend's final message so progress-panel can render it
      if (data.final_message) {
        window.__auriFinalMsg = data.final_message;
      }
    } catch (_) {}
  };

  ws.onclose = () => {
    if (!completed) renderMessage('assistant', '⚠️ Task connection closed unexpectedly.');
  };
}

// ── applyStatusUI ─────────────────────────────────────────────────────────────
function applyStatusUI(s) {
  const ollamaEl = document.getElementById('status-ollama');
  if (ollamaEl) {
    const ok = !!s.ollama_connected;
    ollamaEl.textContent = ok ? '● Ollama: Connected' : '● Ollama: Offline';
    ollamaEl.className   = `status-item ${ok ? 'status-ok' : 'status-error'}`;
  }

  const adminEl = document.getElementById('status-admin');
  if (adminEl) {
    const ok = !!s.is_admin;
    adminEl.textContent = ok ? '● Admin: Active' : '● Admin: Inactive';
    adminEl.className   = `status-item ${ok ? 'status-ok' : 'status-error'}`;
  }

  const diskEl = document.getElementById('status-disk');
  if (diskEl) {
    const gb  = typeof s.free_disk_gb === 'number' ? s.free_disk_gb : 0;
    const low = gb < 5;
    diskEl.textContent = `● Disk: ${gb}GB free`;
    diskEl.className   = `status-item ${low ? 'status-error' : 'status-ok'}`;
  }

  const pythonEl = document.getElementById('status-python');
  if (pythonEl) {
    const ok = !!(s.installed && s.installed.python);
    pythonEl.textContent = ok ? '● Python: Found' : '● Python: Not found';
    pythonEl.className   = `status-item ${ok ? 'status-ok' : 'status-error'}`;
  }
}

// ── updateStatusBar ───────────────────────────────────────────────────────────
async function updateStatusBar() {
  try {
    const s = await window.api.getStatus();
    lastSystemStatus = s;
    applyStatusUI(s);
    hideBackendBanner();
  } catch (_) {
    showBackendBanner();
  }
}

// ── Status-item click → tooltip ───────────────────────────────────────────────
const STATUS_TIPS = {
  'status-ollama': 'Run: ollama serve in your terminal',
  'status-admin':  'Restart AuriOS as Administrator',
  'status-disk':   'Free up space in Windows Settings → Storage',
  'status-python': "Say 'install python' to get started! 😊",
};

['status-ollama', 'status-admin', 'status-disk', 'status-python'].forEach(id => {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.position = 'relative';
  el.addEventListener('click', () => {
    if (!el.classList.contains('status-error')) return;
    const existing = el.querySelector('.status-tooltip');
    if (existing) { existing.remove(); return; }
    document.querySelectorAll('.status-tooltip').forEach(t => t.remove());
    const tip = document.createElement('div');
    tip.className   = 'status-tooltip';
    tip.textContent = STATUS_TIPS[id] || 'Check the logs.';
    el.appendChild(tip);
    setTimeout(() => tip.remove(), 4000);
  });
});

// ── Clear chat ────────────────────────────────────────────────────────────────
const clearBtn = document.getElementById('clear-chat-btn');
if (clearBtn) {
  clearBtn.addEventListener('click', async () => {
    if (!confirm('Clear all chat history?')) return;
    try { await window.api.clearHistory(); } catch (_) {}
    chatMessages.innerHTML = '';
    showDashboard();
  });
}

// ── Init ──────────────────────────────────────────────────────────────────────
(async () => {
  // Set greeting on dashboard
  const greetingEl = document.querySelector('.greeting-text');
  const dashUsernameEl = document.getElementById('dash-username');

  try {
    const profile = await window.api.getProfile();
    if (profile && profile.user_name) {
      userName = profile.user_name;
      const title = `AuriOS — ${userName}`;
      document.title = title;
      const titleEl = document.getElementById('app-title');
      if (titleEl) titleEl.textContent = title;
      if (window.api.setTitle) window.api.setTitle(title);
      if (dashUsernameEl) dashUsernameEl.textContent = userName;
    }
  } catch (_) {}

  // Update greeting text with time of day
  if (greetingEl && dashUsernameEl) {
    greetingEl.innerHTML = `${getGreeting()}, <span id="dash-username">${userName}</span> 👋`;
  }

  // Load conversation history
  try {
    const history = await window.api.getHistory();
    if (Array.isArray(history) && history.length > 0) {
      history.forEach(m => renderMessage(m.role, m.content, m.timestamp));
      // Populate recent items from user messages
      history
        .filter(m => m.role === 'user')
        .slice(-5)
        .reverse()
        .forEach(m => addRecentItem(m.content));
      showChat();
    } else {
      showDashboard();
    }
  } catch (_) {
    showDashboard();
  }

  // Status bar — immediate then every 30 s
  updateStatusBar();
  setInterval(updateStatusBar, 30000);
})();
