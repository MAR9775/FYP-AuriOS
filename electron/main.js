
const { app, BrowserWindow, Tray, Menu, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow = null;
let tray = null;
let backendProcess = null;
const BACKEND_URL = 'http://127.0.0.1:8000';

// ── Backend ────────────────────────────────────────────────────────────────

function startBackend() {
  backendProcess = require('child_process').spawn(
    'python',
    ['-m', 'uvicorn', 'backend.server:app', '--host', '127.0.0.1', '--port', '8000'],
    {
      cwd: path.join(__dirname, '..'),
      stdio: 'pipe',
      windowsHide: true
    }
  )

  backendProcess.stderr.on('data', (data) => {
    console.error('Backend error:', data.toString())
  })

  backendProcess.on('error', (err) => {
    console.error('[AuriOS] Failed to start backend:', err.message);
  });

  backendProcess.on('exit', (code) => {
    console.log('[AuriOS] Backend exited with code', code);
  });
}

function killBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

// ── Window bounds + onboarding check ──────────────────────────────────────

const DEFAULT_BOUNDS = { width: 900, height: 650, x: undefined, y: undefined };

async function loadPrefs() {
  try {
    const res = await fetch(`${BACKEND_URL}/preferences`);
    if (!res.ok) return { bounds: DEFAULT_BOUNDS, onboarded: false };
    const list = await res.json();
    const prefs = Object.fromEntries(list.map(p => [p.key, p.value]));
    let b = null;
    try { b = prefs.windowBounds ? JSON.parse(prefs.windowBounds) : null; } catch (_) {}
    return {
      bounds: (b && b.width && b.height) ? b : DEFAULT_BOUNDS,
      onboarded: prefs.onboarded === 'true',
    };
  } catch (_) {}
  return { bounds: DEFAULT_BOUNDS, onboarded: false };
}

async function saveBounds(bounds) {
  try {
    await fetch(`${BACKEND_URL}/preferences`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: 'windowBounds', value: JSON.stringify(bounds) }),
    });
  } catch (_) {}
}

// ── Window ─────────────────────────────────────────────────────────────────

async function createWindow() {
  const { bounds, onboarded } = await loadPrefs();

  mainWindow = new BrowserWindow({
    width: bounds.width || 900,
    height: bounds.height || 650,
    x: bounds.x,
    y: bounds.y,
    minWidth: 800,
    minHeight: 600,
    backgroundColor: '#1a1a1a',
    frame: false,
    titleBarStyle: 'hidden',
    icon: path.join(__dirname, 'renderer', 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  const startPage = onboarded ? 'index.html' : 'onboarding.html';
  mainWindow.loadFile(path.join(__dirname, 'renderer', startPage));

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Save bounds on resize / move
  const persistBounds = () => {
    if (!mainWindow || mainWindow.isMinimized() || mainWindow.isMaximized()) return;
    saveBounds(mainWindow.getBounds());
  };
  mainWindow.on('resize', persistBounds);
  mainWindow.on('move', persistBounds);

  // Minimise to tray instead of closing
  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
}

// ── Tray ───────────────────────────────────────────────────────────────────

function createTray() {
  const iconPath = path.join(__dirname, 'renderer', 'assets', 'icon.png');
  tray = new Tray(iconPath);
  tray.setToolTip('AuriOS');

  const menu = Menu.buildFromTemplate([
    {
      label: 'Open AuriOS',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => {
        app.isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(menu);

  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ── IPC ────────────────────────────────────────────────────────────────────

ipcMain.on('window-minimize', () => mainWindow && mainWindow.minimize());
ipcMain.on('window-maximize', () => {
  if (!mainWindow) return;
  mainWindow.isMaximized() ? mainWindow.unmaximize() : mainWindow.maximize();
});
ipcMain.on('window-close', () => mainWindow && mainWindow.hide());
ipcMain.on('set-title', (_, title) => {
  if (mainWindow) mainWindow.setTitle(title);
});

// ── App lifecycle ──────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  startBackend();
  await createWindow();
  createTray();

  app.on('activate', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
});

app.on('window-all-closed', (event) => {
  // Keep app alive in tray on all platforms when window is closed
  event.preventDefault && event.preventDefault();
});

app.on('before-quit', () => {
  app.isQuitting = true;
  killBackend();
});
