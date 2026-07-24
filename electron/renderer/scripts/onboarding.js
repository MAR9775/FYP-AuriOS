/* onboarding.js — First-run onboarding logic */

const BASE = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';

// Initial state check is now handled by splash.js
document.addEventListener('DOMContentLoaded', () => {
  const nameInput = document.getElementById('name-input');
  const nameError = document.getElementById('name-error');
  const startBtn  = document.getElementById('start-btn');

  // Clear error as user types
  nameInput.addEventListener('input', () => {
    if (nameInput.value.trim()) {
      nameError.classList.add('hidden');
      nameInput.classList.remove('error');
    }
  });

  startBtn.addEventListener('click', async () => {
    const name = nameInput.value.trim();

    // Validate name
    if (!name) {
      nameInput.classList.add('shake', 'error');
      nameError.classList.remove('hidden');
      nameInput.addEventListener('animationend', () => {
        nameInput.classList.remove('shake');
      }, { once: true });
      nameInput.focus();
      return;
    }

    nameError.classList.add('hidden');
    nameInput.classList.remove('error');

    const experience = document.querySelector('input[name="experience"]:checked')?.value || '';
    const interests  = [...document.querySelectorAll('.ob-checkbox-group input[type="checkbox"]:checked')]
                         .map(c => c.value);

    startBtn.disabled    = true;
    startBtn.textContent = 'Setting up…';

    try {
      const _token = localStorage.getItem('aurios_auth_token') || '';
      const _authHeaders = { 'Content-Type': 'application/json', ...(_token ? { 'Authorization': `Bearer ${_token}` } : {}) };

      await fetch(`${BASE}/profile`, {
        method: 'POST',
        headers: _authHeaders,
        body: JSON.stringify({ user_name: name, experience, interests }),
      });

      await fetch(`${BASE}/preferences`, {
        method: 'POST',
        headers: _authHeaders,
        body: JSON.stringify({ key: 'onboarded', value: 'true' }),
      });

      await fetch(`${BASE}/preferences`, {
        method: 'POST',
        headers: _authHeaders,
        body: JSON.stringify({ key: 'setup_date', value: new Date().toISOString() }),
      });

      // Initialize dashboard data if necessary, or just show app-view
      document.getElementById('onboarding-view').style.opacity = '0';
      setTimeout(() => {
        document.getElementById('onboarding-view').classList.add('hidden');
        document.getElementById('app-view').style.opacity = '0';
        document.getElementById('app-view').classList.remove('hidden');
        // trigger reflow
        void document.getElementById('app-view').offsetWidth;
        document.getElementById('app-view').style.transition = 'opacity 0.8s ease';
        document.getElementById('app-view').style.opacity = '1';
        // Reload app data
        if (typeof window.initApp === 'function') window.initApp();
      }, 500);
    } catch (err) {
      startBtn.disabled    = false;
      startBtn.innerHTML = 'Get Started <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>';
      console.error('[AuriOS] Onboarding save error:', err);
      // Show visible error to the user instead of failing silently
      let errEl = document.getElementById('onboarding-save-error');
      if (!errEl) {
        errEl = document.createElement('div');
        errEl.id = 'onboarding-save-error';
        errEl.style.cssText = 'color:#f87171;font-size:0.85rem;margin-top:10px;text-align:center;';
        startBtn.parentNode.insertBefore(errEl, startBtn.nextSibling);
      }
      errEl.textContent = 'Could not save your profile. Please check your connection and try again.';
    }
  });
});
