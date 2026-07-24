/* scripts/splash.js */
(function () {
  const overlay = document.getElementById('splash-overlay');
  if (!overlay) return;

  const appView = document.getElementById('app-view');
  const onboardingView = document.getElementById('onboarding-view');
  const adminView = document.getElementById('admin-view');
  let nextView = null; // Default to null, explicitly wait for auth check

  const authView = document.getElementById('auth-view');

  window.checkOnboardingAndProceed = async function() {
    const role = localStorage.getItem('aurios_user_role');
    if (role === 'admin') {
      authView.classList.add('hidden');
      adminView.classList.remove('hidden');
      if (typeof window.initAdmin === 'function') window.initAdmin();
      return;
    }

    try {
      const res = await fetch('http://127.0.0.1:8000/preferences');
      if (res.ok) {
        const list = await res.json();
        const prefs = Object.fromEntries(list.map(p => [p.key, p.value]));
        if (prefs.onboarded !== 'true') {
          authView.classList.add('hidden');
          onboardingView.classList.remove('hidden');
          return;
        }
      }
    } catch (_) {}

    authView.classList.add('hidden');
    appView.classList.remove('hidden');
    if (typeof window.initApp === 'function') window.initApp();
  };

  async function checkAuthAndOnboarding() {
    const token = localStorage.getItem('aurios_auth_token');
    let validSession = false;
    
    if (token) {
      try {
        const verifyRes = await fetch('http://127.0.0.1:8000/auth/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token })
        });
        if (verifyRes.ok) {
          const verifyData = await verifyRes.json();
          if (verifyData.valid) {
            validSession = true;
            if (verifyData.user && verifyData.user.role) {
              localStorage.setItem('aurios_user_role', verifyData.user.role);
            }
          } else {
            // Token exists but backend says it is invalid — purge stale session
            localStorage.removeItem('aurios_auth_token');
            localStorage.removeItem('aurios_user_role');
          }
        } else {
          // Server rejected token (401/403) — purge stale session
          localStorage.removeItem('aurios_auth_token');
          localStorage.removeItem('aurios_user_role');
        }
      } catch (_) {}
    }
    
    if (validSession) {
      const role = localStorage.getItem('aurios_user_role');
      if (role === 'admin') {
        nextView = adminView;
      } else {
        try {
          const res = await fetch('http://127.0.0.1:8000/preferences');
          if (res.ok) {
            const list = await res.json();
            const prefs = Object.fromEntries(list.map(p => [p.key, p.value]));
            if (prefs.onboarded !== 'true') nextView = onboardingView;
          } else {
            nextView = onboardingView;
          }
        } catch (_) {
          nextView = onboardingView;
        }
      }
    } else {
      nextView = authView;
    }
  }

  const poll = setInterval(async () => {
    try {
      const r = await fetch('http://127.0.0.1:8000/ping', { signal: AbortSignal.timeout(1200) });
      if (r.ok) {
        clearInterval(poll);
        
        // Start background fetch for full status immediately
        window.__bgStatusPromise = fetch('http://127.0.0.1:8000/system-status-full')
          .then(res => res.json())
          .then(status => {
            try {
              localStorage.setItem('aurios_system_status', JSON.stringify(status));
            } catch(e) {}
            return status;
          })
          .catch(() => null);
          
        await checkAuthAndOnboarding();
      }
    } catch (_) {}
  }, 1000);

  let transitioned = false;
  
  function transitionOut() {
    if (transitioned) return;
    
    // If transitionOut is called before auth check finishes, fallback to authView
    if (!nextView) nextView = authView;

    transitioned = true;
    
    document.removeEventListener('click', skip);
    document.removeEventListener('keypress', skip);

    // Fade in the underlying view
    if (nextView) {
      nextView.style.opacity = '0';
      nextView.classList.remove('hidden');
      // Trigger reflow
      void nextView.offsetWidth;
      nextView.style.transition = 'opacity 2s ease';
      nextView.style.opacity = '1';
    }

    // Fade out the overlay background
    overlay.classList.add('transparent-bg');

    if (nextView === appView && typeof window.initApp === 'function') window.initApp();
    if (nextView === adminView && typeof window.initAdmin === 'function') window.initAdmin();
    
    // Remove the overlay from DOM entirely after the 3s background transition
    setTimeout(() => overlay.remove(), 3000);
  }

  const at = (timeMs, fn) => setTimeout(fn, timeMs);

  function runAnimation() {
    const line = document.getElementById('intro-line');
    const chars = document.querySelectorAll('.char');
    const underline = document.getElementById('splash-underline');
    const subtitle = document.getElementById('splash-subtitle');

    // [0:00 - 0:03] LINE DRAW
    if (line) line.classList.add('animate-line');

    at(100, () => {
      overlay.classList.add('init-bg');
    });

    // [0:03 - 0:07] BLOCK BUILD (Symmetrical slide in)
    at(3000, () => {
      if (line) line.classList.add('hide-line');
      const lefts = [
        document.querySelector('.intro-block.block-l1'),
        document.querySelector('.intro-block.block-l2'),
        document.querySelector('.intro-block.block-l3')
      ];
      const rights = [
        document.querySelector('.intro-block.block-r1'),
        document.querySelector('.intro-block.block-r2'),
        document.querySelector('.intro-block.block-r3')
      ];
      
      lefts.forEach((b, i) => {
        at(i * 600, () => {
          if (b) b.classList.add('block-slide-in');
          if (rights[i]) rights[i].classList.add('block-slide-in');
        });
      });
    });

    // [0:07 - 0:12] TEXT REVEAL
    at(7000, () => {
      const blockContainer = document.getElementById('intro-blocks');
      if (blockContainer) blockContainer.classList.add('hide-blocks');

      chars.forEach((c, i) => {
        at(i * 800, () => c.classList.add('char-flash'));
      });
    });

    // [0:12 - 0:14] LOGO LOCK
    at(12000, () => {
      if (underline) underline.classList.add('underline-visible');
    });

    // [0:14 - 0:16] SUBTITLE TYPE-ON
    at(14000, () => {
      if (!subtitle) return;
      const textToType = "AuriOS  —  The Environment Expert";
      
      // Create and append cursor
      const cursor = document.createElement('span');
      cursor.className = 'cursor';
      subtitle.appendChild(cursor);

      // Typewriter effect
      let idx = 0;
      const typeInterval = setInterval(() => {
        if (idx < textToType.length) {
          const charSpan = document.createElement('span');
          charSpan.textContent = textToType[idx];
          subtitle.insertBefore(charSpan, cursor);
          idx++;
        } else {
          clearInterval(typeInterval);
          // Cursor blinks for a bit, then hides
          at(1000, () => {
            cursor.classList.add('cursor-hidden');
          });
        }
      }, 55); // ~1.8s total for 33 chars
    });

    // [0:16 - 0:18] HOLD + FADE
    at(17500, () => {
      const anchor = document.getElementById('splash-center-anchor');
      if (anchor) {
        anchor.style.transition = 'opacity 0.5s ease';
        anchor.style.opacity = '0';
      }
    });

    // [0:18.0] Transition into Dashboard
    at(18000, () => {
      transitionOut();
    });
  }

  // Ensure DOM is fully painted
  const splashPlayed = sessionStorage.getItem('aurios_splash_played');
  if (splashPlayed) {
    // Fast path: wait for checkAuthAndOnboarding to set nextView, then transition
    const p = setInterval(() => {
      if (nextView) {
        clearInterval(p);
        transitionOut();
      }
    }, 100);
  } else {
    sessionStorage.setItem('aurios_splash_played', 'true');
    setTimeout(() => requestAnimationFrame(runAnimation), 10);
  }

  let skipOk = false;
  setTimeout(() => { skipOk = true; }, 3000);

  function skip() {
      if (!skipOk || !nextView) return; // Wait for skip timeout AND auth check
      transitionOut();
  }
  document.addEventListener('click', skip);
  document.addEventListener('keypress', skip);

})();
