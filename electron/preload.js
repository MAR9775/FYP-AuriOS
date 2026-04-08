const { contextBridge, ipcRenderer } = require('electron');

const BASE = 'http://127.0.0.1:8000';

contextBridge.exposeInMainWorld('api', {
  // Chat
  sendMessage: (text) =>
    fetch(`${BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    }).then((r) => r.json()),

  // History
  getHistory: () =>
    fetch(`${BASE}/history`).then((r) => r.json()),

  // Profile
  getProfile: () =>
    fetch(`${BASE}/profile`).then((r) => r.json()),

  // System status
  getStatus: () =>
    fetch(`${BASE}/system-status-full`).then((r) => r.json()),

  // Clear history
  clearHistory: () =>
    fetch(`${BASE}/history`, { method: 'DELETE' }).then((r) => r.json()),

  // Preferences
  setPreference: (key, value) =>
    fetch(`${BASE}/preferences`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, value }),
    }).then((r) => r.json()),

  getPreferences: () =>
    fetch(`${BASE}/preferences`).then((r) => r.json()),

  // Profile (write + reset)
  postProfile: (data) =>
    fetch(`${BASE}/profile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then((r) => r.json()),

  resetProfile: () =>
    fetch(`${BASE}/profile/reset`, { method: 'POST' }).then((r) => r.json()),

  // Installation history
  getInstallationHistory: () =>
    fetch(`${BASE}/installation-history`).then((r) => r.json()),

  // Cancel a running installation task
  cancelTask: (taskId) =>
    fetch(`${BASE}/cancel/${taskId}`, { method: 'POST' }).then((r) => r.json()),

  // Window controls (custom titlebar)
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),

  // Update native window title (called after profile loads)
  setTitle: (title) => ipcRenderer.send('set-title', title),
});
