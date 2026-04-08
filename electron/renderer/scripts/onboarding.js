/* onboarding.js — First-run onboarding logic */

const BASE = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';

// Check if already onboarded — retry a few times to give the backend time to start
(async () => {
  for (let attempt = 0; attempt < 6; attempt++) {
    try {
      const res = await fetch(`${BASE}/preferences`);
      if (res.ok) {
        const list = await res.json();
        const prefs = Object.fromEntries(list.map(p => [p.key, p.value]));
        if (prefs.onboarded === 'true') {
          window.location.href = 'index.html';
          return;
        }
        break; // Got a valid response; not onboarded — show the form
      }
    } catch (_) {}
    // Backend not ready yet — wait 600ms before next attempt
    await new Promise(r => setTimeout(r, 600));
  }
})();

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
      await fetch(`${BASE}/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_name: name, experience, interests }),
      });

      await fetch(`${BASE}/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'onboarded', value: 'true' }),
      });

      await fetch(`${BASE}/preferences`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'setup_date', value: new Date().toISOString() }),
      });

      window.location.href = 'index.html';
    } catch (err) {
      startBtn.disabled    = false;
      startBtn.textContent = 'Get Started →';
      console.error('[AuriOS] Onboarding save error:', err);
    }
  });
});
