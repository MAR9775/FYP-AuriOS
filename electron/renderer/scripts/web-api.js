/* web-api.js — Browser shim for window.api (replaces Electron preload.js contextBridge).
 * Only runs when not already defined by Electron's preload.js. */
if (!window.api) {
  window.api = {
    sendMessage: (text) =>
      fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      }).then((r) => r.json()),

    getHistory: () => fetch('/history').then((r) => r.json()),

    getProfile: () => fetch('/profile').then((r) => r.json()),

    getStatus: () => fetch('/system-status-full').then((r) => r.json()),

    clearHistory: () => fetch('/history', { method: 'DELETE' }).then((r) => r.json()),

    setPreference: (key, value) =>
      fetch('/preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, value }),
      }).then((r) => r.json()),

    getPreferences: () => fetch('/preferences').then((r) => r.json()),

    postProfile: (data) =>
      fetch('/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      }).then((r) => r.json()),

    resetProfile: () =>
      fetch('/profile/reset', { method: 'POST' }).then((r) => r.json()),

    getInstallationHistory: () =>
      fetch('/installation-history').then((r) => r.json()),

    cancelTask: (taskId) =>
      fetch(`/cancel/${taskId}`, { method: 'POST' }).then((r) => r.json()),

    // Electron window controls — no-op in browser
    minimize: () => {},
    maximize: () => {},
    close: () => {},
    setTitle: (title) => { document.title = title; },
  };
}
