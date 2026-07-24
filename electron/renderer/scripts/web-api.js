/* web-api.js — Browser shim for window.api (replaces Electron preload.js contextBridge).
 * Only runs when not already defined by Electron's preload.js. */
if (!window.api) {
  // Helper: get stored auth token
  function _authHeaders(extra) {
    const token = localStorage.getItem('aurios_auth_token') || '';
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return Object.assign(headers, extra);
  }

  window.api = {
    sendMessage: (text) =>
      fetch('/chat', {
        method: 'POST',
        headers: _authHeaders(),
        body: JSON.stringify({ message: text }),
      }).then((r) => r.json()),

    getHistory: () => fetch('/history', { headers: _authHeaders() }).then((r) => r.json()),

    getProfile: (token) => {
      const headers = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      return fetch('/profile', { headers }).then((r) => r.json());
    },

    getStatus: () => fetch('/system-status-full').then((r) => r.json()),

    clearHistory: () => fetch('/history', { method: 'DELETE', headers: _authHeaders() }).then((r) => r.json()),

    setPreference: (key, value) =>
      fetch('/preferences', {
        method: 'POST',
        headers: _authHeaders(),
        body: JSON.stringify({ key, value }),
      }).then((r) => r.json()),

    getPreferences: () => fetch('/preferences', { headers: _authHeaders() }).then((r) => r.json()),

    postProfile: (data, token) => {
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      return fetch('/profile', {
        method: 'POST',
        headers,
        body: JSON.stringify(data),
      }).then((r) => r.json());
    },

    changePassword: (data) =>
      fetch('/auth/change-password', {
        method: 'POST',
        headers: _authHeaders(),
        body: JSON.stringify(data),
      }).then((r) => {
        if (!r.ok) {
          return r.json().then(err => { throw new Error(err.detail || 'Failed to change password'); });
        }
        return r.json();
      }),

    resetProfile: () =>
      fetch('/profile/reset', { method: 'POST', headers: _authHeaders() }).then((r) => r.json()),

    getInstallationHistory: () =>
      fetch('/installation-history', { headers: _authHeaders() }).then((r) => r.json()),

    cancelTask: (taskId) =>
      fetch(`/cancel/${taskId}`, { method: 'POST', headers: _authHeaders() }).then((r) => r.json()),

    getAvailableSoftware: () =>
      fetch('/available-software', { headers: _authHeaders() }).then((r) => r.json()),

    // Electron window controls — no-op in browser
    minimize: () => {},
    maximize: () => {},
    close: () => {},
    setTitle: (title) => { document.title = title; },
  };
}
