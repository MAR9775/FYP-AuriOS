/* profile.js — Profile pill, dropdown, and modal panels */

const _BASE = 'http://127.0.0.1:8000';

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

async function showMyProfile(editMode = false) {
  if (editMode !== true) toggleProfileDropdown();
  
  if (editMode !== true) {
    showModal('<h2 class="modal-title">My Profile</h2><p class="modal-loading">Loading…</p>');
  }

  try {
    const [profile, prefs] = await Promise.all([
      window.api.getProfile(localStorage.getItem('aurios_auth_token')),
      window.api.getPreferences(),
    ]);

    const name       = profile?.user_name || 'Unknown';
    const exp        = profile?.experience || '—';
    const rawInterests = profile?.interests;
    const interests  = Array.isArray(rawInterests)
      ? (rawInterests.length ? rawInterests.join(', ') : '—')
      : (rawInterests || '—');
    const rawDate = profile?.created_at || prefs?.setup_date;
    const setupDate  = rawDate
      ? new Date(rawDate).toLocaleDateString(undefined, {
          year: 'numeric', month: 'long', day: 'numeric',
        })
      : 'Unknown';

    if (editMode === true) {
      showModal(`
        <h2 class="modal-title">Edit Profile</h2>
        <div class="modal-field">
          <span class="modal-field-label">Name</span>
          <input type="text" id="edit-name" class="modal-input" value="${name === 'Unknown' ? '' : name}" />
        </div>
        <div class="modal-field">
          <span class="modal-field-label">Experience</span>
          <input type="text" id="edit-exp" class="modal-input" value="${exp === '—' ? '' : exp}" />
        </div>
        <div class="modal-field">
          <span class="modal-field-label">Interests</span>
          <input type="text" id="edit-interests" class="modal-input" value="${interests === '—' ? '' : interests}" />
        </div>
        <div id="edit-profile-error" style="display:none;color:#f87171;font-size:0.85rem;margin-top:4px;"></div>
        <div class="modal-buttons">
          <button id="btn-save-profile" class="modal-btn modal-btn-primary">Save</button>
          <button id="btn-cancel-edit" class="modal-btn modal-btn-secondary">Cancel</button>
        </div>
      `);
      
      document.getElementById('btn-save-profile').addEventListener('click', async () => {
        const newName = document.getElementById('edit-name').value.trim();
        const newExp = document.getElementById('edit-exp').value.trim();
        const newInterests = document.getElementById('edit-interests').value.trim();
        const errEl = document.getElementById('edit-profile-error');
        
        document.getElementById('btn-save-profile').disabled = true;
        document.getElementById('btn-save-profile').textContent = 'Saving...';
        if (errEl) errEl.style.display = 'none';
        
        try {
          await window.api.postProfile({
            user_name: newName,
            experience: newExp,
            interests: newInterests
          }, localStorage.getItem('aurios_auth_token'));
          
          // Update pill name and dropdown header
          const nameEl = document.getElementById('profile-name');
          if (nameEl) nameEl.textContent = newName || 'User';
          const avatarEl = document.getElementById('profile-avatar');
          if (avatarEl) avatarEl.textContent = (newName || 'User').charAt(0).toUpperCase();
          const ddUsernameEl = document.getElementById('dd-username');
          if (ddUsernameEl) ddUsernameEl.textContent = newName || 'User';

          showMyProfile(false); // Reload read-only mode
        } catch (e) {
          document.getElementById('btn-save-profile').disabled = false;
          document.getElementById('btn-save-profile').textContent = 'Save';
          if (errEl) { errEl.textContent = e.message || 'Failed to save profile.'; errEl.style.display = 'block'; }
        }
      });
      
      document.getElementById('btn-cancel-edit').addEventListener('click', () => {
        showMyProfile(false);
      });
      
    } else {
      showModal(`
        <h2 class="modal-title">My Profile</h2>
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
        <div class="modal-buttons">
          <button id="btn-edit-profile" class="modal-btn modal-btn-primary">Edit</button>
          <button id="btn-change-password" class="modal-btn modal-btn-secondary">Change Password</button>
        </div>
      `);

      document.getElementById('btn-edit-profile').addEventListener('click', () => {
        showMyProfile(true);
      });
      
      document.getElementById('btn-change-password').addEventListener('click', () => {
        showChangePassword();
      });
    }
  } catch (_) {
    showModal('<h2 class="modal-title">My Profile</h2><p class="modal-empty">Could not load profile.</p>');
  }
}

async function showChangePassword() {
  showModal(`
    <h2 class="modal-title">Change Password</h2>
    <div class="modal-field">
      <span class="modal-field-label">Current</span>
      <input type="password" id="cp-current" class="modal-input" placeholder="Current password" />
    </div>
    <div class="modal-field">
      <span class="modal-field-label">New</span>
      <input type="password" id="cp-new" class="modal-input" placeholder="New password" />
    </div>
    <div class="modal-field">
      <span class="modal-field-label">Confirm</span>
      <input type="password" id="cp-confirm" class="modal-input" placeholder="Confirm new password" />
    </div>
    <div id="cp-msg" class="modal-msg"></div>
    <div class="modal-buttons">
      <button id="btn-save-password" class="modal-btn modal-btn-primary">Save Password</button>
      <button id="btn-cancel-password" class="modal-btn modal-btn-secondary">Cancel</button>
    </div>
  `);

  document.getElementById('btn-cancel-password').addEventListener('click', () => {
    showMyProfile(false);
  });

  document.getElementById('btn-save-password').addEventListener('click', async () => {
    const current = document.getElementById('cp-current').value;
    const newPass = document.getElementById('cp-new').value;
    const confirm = document.getElementById('cp-confirm').value;
    const msgEl = document.getElementById('cp-msg');
    const btn = document.getElementById('btn-save-password');

    msgEl.className = 'modal-msg error';
    if (!current || !newPass || !confirm) {
      msgEl.textContent = 'Please fill in all fields.';
      return;
    }
    if (newPass !== confirm) {
      msgEl.textContent = 'New passwords do not match.';
      return;
    }
    if (newPass.length < 6) {
      msgEl.textContent = 'Password must be at least 6 characters.';
      return;
    }

    btn.disabled = true;
    btn.textContent = 'Saving...';
    msgEl.textContent = '';

    try {
      const token = localStorage.getItem('aurios_auth_token');
      await window.api.changePassword({ token, current_password: current, new_password: newPass });
      
      msgEl.className = 'modal-msg success';
      msgEl.textContent = 'Password changed successfully.';
      
      setTimeout(() => showMyProfile(false), 2000);
    } catch (e) {
      msgEl.className = 'modal-msg error';
      msgEl.textContent = e.message || 'Failed to change password.';
      btn.disabled = false;
      btn.textContent = 'Save Password';
    }
  });
}

// ── Dropdown action: Installation History ─────────────────────────────────────

async function showInstallHistory() {
  toggleProfileDropdown();
  showModal('<h2 class="modal-title">Installation History</h2><p class="modal-loading">Loading…</p>');

  try {
    const history = await window.api.getInstallationHistory();

    if (!Array.isArray(history) || history.length === 0) {
      document.getElementById('modal-content').innerHTML = `
        <h2 class="modal-title">Installation History</h2>
        <p class="modal-empty">No installations yet</p>
      `;
      return;
    }

    const rows = history.map(h => `
      <div class="install-row">
        <span class="install-name">${h.preset_name || h.software || 'Unknown'}</span>
        <span class="install-ts">${new Date(h.timestamp).toLocaleString()}</span>
        <span class="install-status">${h.status === 'success'
          ? '<svg width="14" height="14" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'
          : '<svg width="14" height="14" fill="none" stroke="#f87171" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
        }</span>
      </div>
    `).join('');

    document.getElementById('modal-content').innerHTML = `
      <h2 class="modal-title">Installation History</h2>
      <div class="install-list">${rows}</div>
    `;
  } catch (_) {
    document.getElementById('modal-content').innerHTML = `
      <h2 class="modal-title">Installation History</h2>
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
    <h2 class="modal-title">Preferences</h2>
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
      // FIX 16: use the correct TTS API (window.tts.setEnabled)
      if (window.tts && typeof window.tts.setEnabled === 'function') {
        window.tts.setEnabled(e.target.checked);
      }
    } catch (_) {}
  });
}

// ── Dropdown action: Logout ───────────────────────────────────────────

async function logoutUser() {
  toggleProfileDropdown();
  const token = localStorage.getItem('aurios_auth_token');
  if (token) {
    try {
      await fetch('http://127.0.0.1:8000/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token })
      });
    } catch (_) {}
  }
  localStorage.removeItem('aurios_auth_token');
  window.location.reload();
}

// ── Dropdown action: Reset Profile ───────────────────────────────────────────

async function resetProfile() {
  toggleProfileDropdown();
  // FIX 7: use custom confirm modal — native confirm() may be blocked by Electron CSP
  if (typeof showCustomConfirm === 'function') {
    showCustomConfirm(
      'Reset all profile data? This will clear your name, experience, and interests. This cannot be undone.',
      async () => {
        try { await window.api.resetProfile(); } catch (_) {}
        window.location.reload();
      },
      'Reset'
    );
  } else {
    // Fallback for safety (browser mode)
    if (!confirm('Reset all profile data? This cannot be undone.')) return;
    try { await window.api.resetProfile(); } catch (_) {}
    window.location.reload();
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', async () => {
  // Load profile name into pill and dropdown header
  try {
    const profile = await window.api.getProfile(localStorage.getItem('aurios_auth_token'));
    if (profile) {
      const name = profile.user_name || 'User';
      const nameEl = document.getElementById('profile-name');
      if (nameEl) nameEl.textContent = name;
      const avatarEl = document.getElementById('profile-avatar');
      if (avatarEl) avatarEl.textContent = name.charAt(0).toUpperCase();
      // FIX 4: populate dd-username header in the dropdown
      const ddUsernameEl = document.getElementById('dd-username');
      if (ddUsernameEl) ddUsernameEl.textContent = name;
    }
  } catch (_) {}

  // Profile pill click — toggle dropdown (replaces inline onclick blocked by CSP)
  document.getElementById('profile-pill')?.addEventListener('click', toggleProfileDropdown);

  // Dropdown items wired via data-action (replaces inline onclick blocked by CSP)
  const ddActions = {
    'my-profile':      showMyProfile,
    'install-history': showInstallHistory,
    'preferences':     showPreferences,
    'logout':          logoutUser,
    'reset':           resetProfile,
  };
  document.querySelectorAll('#profile-dropdown .dropdown-item[data-action]').forEach(item => {
    const handler = ddActions[item.dataset.action];
    if (handler) item.addEventListener('click', handler);
  });

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
