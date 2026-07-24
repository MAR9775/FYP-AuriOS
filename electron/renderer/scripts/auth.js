/* scripts/auth.js */

document.addEventListener('DOMContentLoaded', () => {
  const tabLogin = document.getElementById('tab-login');
  const tabSignup = document.getElementById('tab-signup');
  const loginForm = document.getElementById('login-form');
  const signupForm = document.getElementById('signup-form');
  const errorMsg = document.getElementById('auth-error-msg');

  if (!tabLogin || !tabSignup || !loginForm || !signupForm) return;

  function switchTab(mode) {
    errorMsg.classList.add('hidden');
    errorMsg.classList.remove('success-text', 'error-text');
    if (mode === 'login') {
      tabLogin.classList.add('active');
      tabSignup.classList.remove('active');
      loginForm.classList.remove('hidden');
      signupForm.classList.add('hidden');
    } else {
      tabSignup.classList.add('active');
      tabLogin.classList.remove('active');
      signupForm.classList.remove('hidden');
      loginForm.classList.add('hidden');
    }
  }

  tabLogin.addEventListener('click', () => switchTab('login'));
  tabSignup.addEventListener('click', () => switchTab('signup'));

  function showError(msg) {
    errorMsg.classList.remove('success-text');
    errorMsg.classList.add('error-text');
    errorMsg.textContent = msg;
    errorMsg.classList.remove('hidden');
  }

  function showSuccess(msg) {
    errorMsg.classList.add('success-text');
    errorMsg.classList.remove('error-text');
    errorMsg.textContent = msg;
    errorMsg.classList.remove('hidden');
  }

  // Password visibility toggle
  document.querySelectorAll('.password-toggle').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const input = btn.previousElementSibling;
      if (input && input.tagName === 'INPUT') {
        const type = input.getAttribute('type') === 'password' ? 'text' : 'password';
        input.setAttribute('type', type);
        btn.style.color = type === 'text' ? '#6366f1' : '#64748b';
      }
    });
  });

  // Handle Login
  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    errorMsg.classList.add('hidden');
    
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    const btn = document.getElementById('login-btn');
    
    if (!email || !password) return showError('Please fill in all fields');
    
    btn.disabled = true;
    btn.textContent = 'Logging in...';
    
    try {
      const res = await fetch('http://127.0.0.1:8000/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      
      const data = await res.json();
      if (res.ok && data.token) {
        localStorage.setItem('aurios_auth_token', data.token);
        const role = data.user?.role || 'user';
        localStorage.setItem('aurios_user_role', role);

        if (role === 'admin') {
          document.getElementById('auth-view')?.classList.add('hidden');
          const adminView = document.getElementById('admin-view');
          if (adminView) adminView.classList.remove('hidden');
          if (typeof window.initAdmin === 'function') window.initAdmin();
        } else if (typeof window.checkOnboardingAndProceed === 'function') {
          window.checkOnboardingAndProceed();
        }
      } else {
        showError('Invalid email or password. Please try again.');
      }
    } catch (err) {
      showError('Network error. Is the backend running?');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Login';
    }
  });

  // Handle Signup
  signupForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    errorMsg.classList.add('hidden');
    
    const name = document.getElementById('signup-name').value.trim();
    const email = document.getElementById('signup-email').value.trim();
    const password = document.getElementById('signup-password').value;
    const confirm = document.getElementById('signup-confirm').value;
    const btn = document.getElementById('signup-btn');
    
    if (!name || !email || !password || !confirm) return showError('Please fill in all fields');
    
    const nameRegex = /^[a-zA-Z\s]+$/;
    if (name.length < 2 || !nameRegex.test(name)) return showError('Name must contain only letters and be at least 2 characters long');
    
    if (password !== confirm) return showError('Passwords do not match');
    if (password.length < 6) return showError('Password must be at least 6 characters');
    
    btn.disabled = true;
    btn.textContent = 'Signing up...';
    
    try {
      const res = await fetch('http://127.0.0.1:8000/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, email, password })
      });
      
      const data = await res.json();
      if (res.ok) {
        signupForm.reset();
        switchTab('login');
        showSuccess('Account created successfully! Please log in.');
      } else {
        showError(data.detail || 'Signup failed');
      }
    } catch (err) {
      showError('Network error. Is the backend running?');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Sign Up';
    }
  });
});
