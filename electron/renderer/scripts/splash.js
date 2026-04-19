/* scripts/splash.js */
(function () {
  const overlay = document.getElementById('splash-overlay');
  if (!overlay) return;

  const fill   = document.getElementById('splash-progress-fill');
  const status = document.getElementById('splash-status-line');
  const appView = document.getElementById('app-view');
  const onboardingView = document.getElementById('onboarding-view');
  
  let pct  = 0;
  let done = false;
  let nextView = appView; // default

  function setProgress(v) {
    pct = Math.max(pct, Math.min(v, 100));
    fill.style.width = pct + '%';
  }

  // Very subtle, smooth drift
  const drift = setInterval(() => {
    if (pct < 70 && !done) {
      setProgress(pct + (Math.random() * 1.5 + 0.3));
    }
  }, 60);

  // Poll backend — 350ms interval, max 8 tries (~2.8s)
  let polls = 0;
  const MAX_POLLS = 8;

  async function checkOnboarding() {
    try {
      const res = await fetch('http://127.0.0.1:8000/preferences');
      if (res.ok) {
        const list = await res.json();
        const prefs = Object.fromEntries(list.map(p => [p.key, p.value]));
        if (prefs.onboarded !== 'true') {
          nextView = onboardingView;
        }
      } else {
        nextView = onboardingView;
      }
    } catch (_) {
      nextView = onboardingView;
    }
  }

  const poll = setInterval(async () => {
    polls++;
    try {
      const r = await fetch('http://127.0.0.1:8000/system-status-full', {
        signal: AbortSignal.timeout(1200),
      });
      if (r.ok && !done) {
        done = true;
        clearInterval(drift);
        clearInterval(poll);
        status.textContent = 'System Online';
        status.className   = 'splash-status-line ready';
        await checkOnboarding();
        sprintToEnd();
      }
    } catch (_) {
      if (polls >= MAX_POLLS && !done) {
        done = true;
        clearInterval(drift);
        clearInterval(poll);
        await checkOnboarding();
        sprintToEnd();
      }
    }
  }, 350);

  function sprintToEnd() {
    const sprint = setInterval(() => {
      setProgress(pct + 2);
      if (pct >= 100) {
        clearInterval(sprint);
        setTimeout(transitionOut, 400); // Give it a moment to settle
      }
    }, 16);
  }

  function transitionOut() {
    // Unhide the appropriate underlying view
    if (nextView) {
      nextView.classList.remove('hidden');
    }
    
    // Smoothly fade out the splash overlay
    overlay.classList.add('fade-out');
    
    // Only load the dashboard AFTER the animation completion event triggers
    if (nextView === appView && typeof window.initApp === 'function') {
      window.initApp();
    }

    // Remove it from DOM completely after fade out to save memory and pointer-events
    setTimeout(() => {
      overlay.remove();
    }, 850);
  }

  // Skip on click or key after 1200ms (prevent skipping too fast so animation can play)
  let skipOk = false;
  setTimeout(() => { skipOk = true; }, 1200);

  async function skip() {
    if (!skipOk || done) return;
    done = true;
    clearInterval(drift);
    clearInterval(poll);
    setProgress(100);
    await checkOnboarding();
    transitionOut();
  }

  document.addEventListener('click',    skip);
  document.addEventListener('keypress', skip);
})();
