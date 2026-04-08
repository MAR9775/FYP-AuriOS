/* profile.js — Profile pill, dropdown, and modal panels */

const _BASE = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';

let dropdownOpen = false;

// ── Dropdown ──────────────────────────────────────────────────────────────────

function toggleProfileDropdown() {
  const dd = document.getElementById('profile-dropdown');
  if (!dd) return;
  dropdownOpen = !dropdownOpen;
  dd.classList.toggle('hidden', !dropdownOpen);
}

document.addEventListener('click', (e) => {
  if (!e.target.closest('#profile-pill') && !e.target.closest('#profile-dropdown')) {
    const dd = document.getElementById('profile-dropdown');
    if (dd) dd.classList.add('hidden');
    dropdownOpen = false;
  }
});

// ── Modal system ──────────────────────────────────────────────────────────────

function showModal(html) {
  const overlay = document.getElementById('modal-overlay');
  const content = document.getElementById('modal-content');
  if (!overlay || !content) return;
  content.innerHTML = html;
  overlay.classList.remove('hidden');
}

function closeModal() {
  const overlay = document.getElementById('modal-overlay');
  if (overlay) overlay.classList.add('hidden');
}

// ── Dropdown action: My Profile ───────────────────────────────────────────────

async function showMyProfile() {
  toggleProfileDropdown();
  showModal('<h2 class="modal-title">👤 My Profile</h2><p class="modal-loading">Loading…</p>');

  try {
    const [profile, prefs] = await Promise.all([
      window.api.getProfile(),
      window.api.getPreferences(),
    ]);

    const name       = profile?.user_name || 'Unknown';
    const exp        = profile?.experience || '—';
    const rawInterests = profile?.interests;
    const interests  = Array.isArray(rawInterests)
      ? (rawInterests.length ? rawInterests.join(', ') : '—')
      : (rawInterests || '—');
    const setupDate  = prefs?.setup_date
      ? new Date(prefs.setup_date).toLocaleDateString(undefined, {
          year: 'numeric', month: 'long', day: 'numeric',
        })
      : 'Unknown';

    showModal(`
      <h2 class="modal-title">👤 My Profile</h2>
      <div class="modal-field">
        <span class="modal-field-label">Name</span>
        <span>${name}</span>
      </div>
      <div class="modal-field">
        <span class="modal-field-label">Experience</span>
        <span>${exp}</span>
      </div>
      <div class="modal-field">
        <span class="modal-field-label">Interests</span>
        <span>${interests}</span>
      </div>
      <div class="modal-field">
        <span class="modal-field-label">Member since</span>
        <span>${setupDate}</span>
      </div>
    `);
  } catch (_) {
    showModal('<h2 class="modal-title">👤 My Profile</h2><p class="modal-empty">Could not load profile.</p>');
  }
}

// ── Dropdown action: Installation History ─────────────────────────────────────

async function showInstallHistory() {
  toggleProfileDropdown();
  showModal('<h2 class="modal-title">📋 Installation History</h2><p class="modal-loading">Loading…</p>');

  try {
    const history = await window.api.getInstallationHistory();

    if (!Array.isArray(history) || history.length === 0) {
      document.getElementById('modal-content').innerHTML = `
        <h2 class="modal-title">📋 Installation History</h2>
        <p class="modal-empty">No installations yet</p>
      `;
      return;
    }

    const rows = history.map(h => `
      <div class="install-row">
        <span class="install-name">${h.preset_name || h.software || 'Unknown'}</span>
        <span class="install-ts">${new Date(h.timestamp).toLocaleString()}</span>
        <span class="install-status">${h.status === 'success' ? '✅' : '❌'}</span>
      </div>
    `).join('');

    document.getElementById('modal-content').innerHTML = `
      <h2 class="modal-title">📋 Installation History</h2>
      <div class="install-list">${rows}</div>
    `;
  } catch (_) {
    document.getElementById('modal-content').innerHTML = `
      <h2 class="modal-title">📋 Installation History</h2>
      <p class="modal-empty">Could not load history.</p>
    `;
  }
}

// ── Dropdown action: Preferences ──────────────────────────────────────────────

async function showPreferences() {
  toggleProfileDropdown();

  let voiceEnabled = true;
  try {
    const prefs = await window.api.getPreferences();
    voiceEnabled = prefs?.voice_enabled !== 'false';
  } catch (_) {}

  showModal(`
    <h2 class="modal-title">⚙️ Preferences</h2>
    <div class="pref-row">
      <span class="pref-label">Voice output</span>
      <label class="toggle-switch">
        <input type="checkbox" id="pref-voice" ${voiceEnabled ? 'checked' : ''} />
        <span class="toggle-slider"></span>
      </label>
    </div>
  `);

  document.getElementById('pref-voice').addEventListener('change', async (e) => {
    const val = e.target.checked ? 'true' : 'false';
    try {
      await window.api.setPreference('voice_enabled', val);
      if (window.voice && typeof window.voice.setVoiceEnabled === 'function') {
        window.voice.setVoiceEnabled(e.target.checked);
      }
    } catch (_) {}
  });
}

// ── Dropdown action: Reset Profile ───────────────────────────────────────────

async function resetProfile() {
  toggleProfileDropdown();
  if (!confirm('Reset all profile data? This cannot be undone.')) return;
  try {
    await window.api.resetProfile();
  } catch (_) {}
  window.location.reload();
}

// ── Init ──────────────────────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', async () => {
  // Load profile name into pill
  try {
    const profile = await window.api.getProfile();
    if (profile) {
      const name = profile.user_name || 'User';
      const nameEl = document.getElementById('profile-name');
      if (nameEl) nameEl.textContent = name;
      const avatarEl = document.getElementById('profile-avatar');
      if (avatarEl) avatarEl.textContent = name.charAt(0).toUpperCase();
    }
  } catch (_) {}

  // Modal close button
  document.getElementById('modal-close-btn')?.addEventListener('click', closeModal);

  // Close modal on overlay click
  const overlay = document.getElementById('modal-overlay');
  if (overlay) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closeModal();
    });
  }
});
