# AuriOS — Complete Technical Documentation

> Version 1.1.0 | Generated from source code analysis of all backend, frontend, and config files.

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Database Layer — Complete Deep Dive](#2-database-layer--complete-deep-dive)
3. [Agent Architecture — Each Agent Individually](#3-agent-architecture--each-agent-individually)
4. [Ollama Integration](#4-ollama-integration)
5. [API / Backend Layer](#5-api--backend-layer)
6. [Frontend / Electron Layer](#6-frontend--electron-layer)
7. [Module & Function Reference](#7-module--function-reference)
8. [Request Lifecycle — End to End](#8-request-lifecycle--end-to-end)
9. [Flags, Constants, Config Variables](#9-flags-constants-config-variables)
10. [Inter-Agent Communication Map](#10-inter-agent-communication-map)
11. [Error Handling & Edge Cases](#11-error-handling--edge-cases)
12. [Install & Startup Sequence](#12-install--startup-sequence)
13. [Glossary](#13-glossary)

---

## 1. System Architecture Overview

### Application Type

AuriOS is a **hybrid desktop application** combining:
- **Electron** (Chromium-based renderer + Node.js main process) for the GUI
- **FastAPI** (Python/uvicorn) for the backend REST API and WebSocket server
- **SQLite** (via `aiosqlite`) for persistent storage
- **Ollama** (local LLM server) for natural-language understanding

The Electron main process spawns the Python backend as a child process on startup. All renderer-to-backend communication goes over HTTP (`http://127.0.0.1:8000`) and WebSocket (`ws://127.0.0.1:8000`). The renderer never has direct Node.js access — it communicates through the `contextBridge` API exposed in `electron/preload.js`.

### Folder / Module Structure

```
AuriOS/
├── electron/
│   ├── main.js                  # Electron main process: window, tray, IPC, backend spawn
│   ├── preload.js               # contextBridge: exposes window.api to renderer
│   └── renderer/
│       ├── index.html           # Single-page app shell (all views in one HTML file)
│       ├── assets/              # icon.png, cinematic_robot.png, abstract_core.png
│       ├── scripts/
│       │   ├── app.js           # Chat logic, sidebar, status bar, software browser
│       │   ├── admin.js         # Admin dashboard (users, installs, system, catalog)
│       │   ├── auth.js          # Login / signup form logic
│       │   ├── splash.js        # Splash animation + auth/onboarding routing
│       │   ├── onboarding.js    # First-run profile collection
│       │   ├── profile.js       # Profile pill, dropdown, modals
│       │   ├── progress-panel.js# Sliding installation progress panel
│       │   ├── tts.js           # Text-to-speech output (SpeechSynthesis)
│       │   ├── agent-animation.js # Canvas particle avatar (4 states)
│       │   ├── web-api.js       # Browser shim for window.api (non-Electron)
│       │   └── speech.js        # Voice input (Web Speech API / WAV fallback)
│       └── styles/
│           ├── main.css         # Layout, titlebar, sidebar, chat, status bar
│           ├── auth.css         # Auth card, tabs, inputs
│           ├── admin.css        # Admin dashboard layout and tables
│           ├── components.css   # Modals, dropdowns, badges, toasts
│           ├── progress-panel.css # Sliding progress panel
│           ├── splash.css       # Splash animation keyframes
│           ├── onboarding.css   # Onboarding card
│           └── agent.css        # Agent avatar canvas wrapper
├── backend/
│   ├── server.py                # FastAPI app: all routes, DB schema, WebSocket
│   ├── __init__.py              # Empty package marker
│   ├── .env                     # ADMIN_PASSWORD_HASH (bcrypt)
│   ├── core/
│   │   ├── orchestrator.py      # 6-stage pipeline coordinator
│   │   ├── task_manager.py      # SQLite-backed task CRUD singleton
│   │   └── models.py            # (Pydantic models, not directly imported by server)
│   ├── agents/
│   │   ├── base_agent.py        # Abstract ReAct base class
│   │   ├── detection_agent.py   # Detects installed software + system info
│   │   ├── download_agent.py    # Downloads installers from GitHub repo
│   │   ├── install_agent.py     # Runs silent installers (local → winget → choco)
│   │   ├── configure_agent.py   # Updates PATH via winreg, runs pip installs
│   │   ├── validate_agent.py    # Re-runs DetectionAgent to confirm install
│   │   └── environment_agent.py # Creates project folder + Python venv
│   ├── llm/
│   │   ├── intent_parser.py     # Rule-based + Ollama intent classification
│   │   └── __init__.py
│   └── utils/
│       ├── repo_sync.py         # GitHub releases catalog sync + SQLite cache
│       ├── admin_check.py       # Windows UAC / admin privilege helpers
│       ├── platform_utils.py    # is_windows(), is_simulated_host(), free_disk_gb()
│       ├── crypto.py            # Fernet symmetric encryption for GitHub tokens
│       └── __init__.py
├── data/
│   ├── aurjos.db                # Primary SQLite database
│   └── .secret.key              # Fernet encryption key (hidden file)
├── installers/                  # Pre-bundled installer binaries
├── logs/
│   └── aurjos.log               # Shared log file for all agents
├── package.json                 # Electron app config, build settings
└── requirements.txt             # Python dependencies
```

### ASCII Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ELECTRON RENDERER                            │
│  (app://app/index.html — Chromium, contextIsolation=true)           │
│                                                                     │
│  splash.js → auth.js → onboarding.js → app.js / admin.js           │
│  profile.js  tts.js  agent-animation.js  progress-panel.js         │
│                          │                                          │
│              window.api (contextBridge)                             │
└──────────────────────────┼──────────────────────────────────────────┘
                           │ IPC (ipcRenderer.send)
┌──────────────────────────┼──────────────────────────────────────────┐
│                    ELECTRON MAIN PROCESS                            │
│  electron/main.js                                                   │
│  • BrowserWindow (frame=false, app:// protocol)                     │
│  • Tray icon + context menu                                         │
│  • IPC: window-minimize/maximize/close, set-title, request-admin    │
│  • Spawns Python backend via child_process.spawn()                  │
└──────────────────────────┼──────────────────────────────────────────┘
                           │ HTTP / WebSocket (127.0.0.1:8000)
┌──────────────────────────┼──────────────────────────────────────────┐
│                    FASTAPI BACKEND (uvicorn)                        │
│  backend/server.py                                                  │
│  • POST /chat → parse_intent() → Orchestrator.run()                 │
│  • GET/POST /auth/* → bcrypt, sessions table                        │
│  • GET/POST /profile, /preferences, /history                        │
│  • GET /system-status-full, /available-software                     │
│  • GET /admin/* (require admin_ token)                              │
│  • WS  /ws/progress/{task_id}                                       │
│                          │                                          │
│  ┌───────────────────────┼──────────────────────────────────────┐   │
│  │              ORCHESTRATOR (orchestrator.py)                  │   │
│  │  Stage 1: DetectionAgent  → installed map + disk + admin     │   │
│  │  Stage 2: DownloadAgent   → installer file paths             │   │
│  │  Stage 3: InstallAgent    → silent install (exe/msi/winget)  │   │
│  │  Stage 4: ConfigureAgent  → PATH (winreg) + pip packages     │   │
│  │  Stage 5: ValidationAgent → re-detect to confirm             │   │
│  │  Stage 6: EnvironmentAgent→ venv + project folder            │   │
│  └───────────────────────┼──────────────────────────────────────┘   │
│                          │                                          │
│  ┌───────────────────────┼──────────────────────────────────────┐   │
│  │              SQLITE DATABASE (data/aurjos.db)                │   │
│  │  conversations │ preferences │ users │ sessions              │   │
│  │  installation_history │ software_catalog │ tasks             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                          │                                          │
│  ┌───────────────────────┼──────────────────────────────────────┐   │
│  │              OLLAMA (http://localhost:11434)                  │   │
│  │  Model: llama3.2:3b (OLLAMA_MODEL env var)                   │   │
│  │  POST /api/chat — intent parsing, pre/post install messages  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---
## 2. Database Layer — Complete Deep Dive

### Database Engine

- **Engine:** SQLite 3
- **Driver:** `aiosqlite` (async wrapper) for all server.py routes; `sqlite3` (sync) for `task_manager.py` and `repo_sync.py`
- **File path:** `data/aurjos.db` (resolved as `BASE_DIR / "data" / "aurjos.db"` where `BASE_DIR = Path(__file__).resolve().parent.parent`)
- **WAL mode:** Enabled on every connection via `PRAGMA journal_mode=WAL`
- **Busy timeout:** 30 seconds via `PRAGMA busy_timeout=30000`

### Connection Method: `_RowFactoryDB`

Defined in `backend/server.py`:

```python
class _RowFactoryDB:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def __aenter__(self) -> aiosqlite.Connection:
        self._conn = await aiosqlite.connect(self._path, timeout=30)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=30000")
        return self._conn

    async def __aexit__(self, *args: Any) -> None:
        if self._conn:
            await self._conn.close()
```

Used via `get_db()` factory: `async with get_db() as db:`. The `aiosqlite.Row` factory means rows are accessible by column name (e.g., `row["email"]`).

### Schema Initialization

All tables are created in the `lifespan()` async context manager in `backend/server.py`, which runs once before the FastAPI app starts serving requests:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        # ... CREATE TABLE IF NOT EXISTS for all 7 tables
        # ... migrations
        # ... backfill
        await db.commit()
    await asyncio.to_thread(repo_sync.sync)
    yield
```

### Tables

#### `conversations`

Stores every chat message exchanged between the user and AuriOS.

| Column      | Type     | Constraints                    | Description                          |
|-------------|----------|--------------------------------|--------------------------------------|
| `id`        | INTEGER  | PRIMARY KEY AUTOINCREMENT      | Row identifier                       |
| `timestamp` | DATETIME | DEFAULT CURRENT_TIMESTAMP      | When the message was saved           |
| `role`      | TEXT     |                                | `"user"` or `"assistant"`            |
| `content`   | TEXT     |                                | The message text                     |
| `metadata`  | TEXT     |                                | Reserved JSON field (currently NULL) |

**Created:** On every `POST /chat` call — one row for the user message, one for the assistant reply.
**Read:** `GET /history` (last 50, reversed), `GET /admin/conversations` (last 300).
**Deleted:** `DELETE /history`, `DELETE /admin/conversations`.

---

#### `preferences`

Key-value store for per-user and system-level settings.

| Column       | Type     | Constraints               | Description                                    |
|--------------|----------|---------------------------|------------------------------------------------|
| `id`         | INTEGER  | PRIMARY KEY AUTOINCREMENT | Row identifier                                 |
| `user_id`    | INTEGER  | (nullable FK → users.id)  | NULL for system/admin keys                     |
| `key`        | TEXT     |                           | Preference name (e.g., `"onboarded"`)          |
| `value`      | TEXT     |                           | Preference value (always stored as string)     |
| `updated_at` | DATETIME | DEFAULT CURRENT_TIMESTAMP | Last write time                                |

**Known keys:**
- `onboarded` — `"true"` after first-run onboarding completes
- `setup_date` — ISO timestamp of onboarding completion
- `voice_enabled` — `"true"` / `"false"` for TTS output
- `windowBounds` — JSON `{width, height, x, y}` for window position persistence
- `admin_session` — active admin bearer token (value = `"admin_XXXX"`)
- `gh_owner`, `gh_repo`, `gh_token_enc` — GitHub repository configuration (token is Fernet-encrypted)

**Migration:** `ALTER TABLE preferences ADD COLUMN user_id INTEGER` runs if the column is missing (older DB schemas).

**Backfill logic:** On startup, orphaned rows (`user_id IS NULL`) that are not system keys (`admin_session`, `gh_owner`, `gh_repo`, `gh_token_enc`, `windowBounds`) are assigned to the first user in the `users` table:

```python
_system_keys = ("admin_session", "gh_owner", "gh_repo", "gh_token_enc", "windowBounds")
await db.execute(
    f"UPDATE preferences SET user_id = ? "
    f"WHERE user_id IS NULL AND key NOT IN ({_placeholders})",
    (_first_user[0], *_system_keys),
)
```

---

#### `users`

Registered user accounts.

| Column          | Type     | Constraints                        | Description                          |
|-----------------|----------|------------------------------------|--------------------------------------|
| `id`            | INTEGER  | PRIMARY KEY AUTOINCREMENT          | User identifier                      |
| `name`          | TEXT     | NOT NULL                           | Display name                         |
| `email`         | TEXT     | UNIQUE NOT NULL                    | Login email                          |
| `password_hash` | TEXT     | NOT NULL                           | bcrypt hash of password              |
| `role`          | TEXT     | NOT NULL DEFAULT `'user'`          | `"user"` or `"admin"`                |
| `status`        | TEXT     | NOT NULL DEFAULT `'active'`        | `"active"` or `"inactive"`           |
| `created_at`    | DATETIME | DEFAULT CURRENT_TIMESTAMP          | Account creation time                |

**Note:** The System Admin (`admin@jarvis.local`) is **not** stored in this table. It is validated against `ADMIN_PASSWORD_HASH` in `backend/.env`.

**Migrations:**
```python
if "role" not in _cols:
    await db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
if "status" not in _cols:
    await db.execute("ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
```

---

#### `sessions`

Active login tokens for regular users.

| Column       | Type     | Constraints                              | Description                    |
|--------------|----------|------------------------------------------|--------------------------------|
| `token`      | TEXT     | PRIMARY KEY                              | 64-char hex token (`secrets.token_hex(32)`) |
| `user_id`    | INTEGER  | NOT NULL, FK → users(id) ON DELETE CASCADE | Owning user                  |
| `created_at` | DATETIME | DEFAULT CURRENT_TIMESTAMP                | Login time                     |

**Created:** `POST /auth/login` (regular users only; admin uses `preferences.admin_session`).
**Deleted:** `POST /auth/logout`, `DELETE /admin/users/{id}`, `POST /admin/users/{id}/deactivate`, `POST /admin/accounts/revoke/{id}`.

---

#### `installation_history`

Audit log of every installation pipeline run.

| Column        | Type     | Constraints               | Description                                  |
|---------------|----------|---------------------------|----------------------------------------------|
| `id`          | INTEGER  | PRIMARY KEY AUTOINCREMENT | Row identifier                               |
| `timestamp`   | DATETIME | DEFAULT CURRENT_TIMESTAMP | When the install ran                         |
| `preset_name` | TEXT     |                           | Preset key (e.g., `"python_basic"`) or slug  |
| `software`    | TEXT     |                           | Comma-separated list of software slugs       |
| `status`      | TEXT     |                           | `"success"`, `"failed"`, etc.                |
| `duration_s`  | REAL     |                           | Wall-clock seconds for the full pipeline     |
| `error_log`   | TEXT     |                           | Reserved for error details (currently NULL)  |

**Created:** In `run_orchestrator_background()` after the pipeline completes.
**Read:** `GET /installation-history`, `GET /admin/installations`.

---

#### `software_catalog`

Cache of available software from the GitHub releases API.

| Column         | Type     | Constraints          | Description                                    |
|----------------|----------|----------------------|------------------------------------------------|
| `slug`         | TEXT     | PRIMARY KEY          | Normalized identifier (e.g., `"python"`)       |
| `display_name` | TEXT     |                      | Human-readable name (e.g., `"Python"`)         |
| `filename`     | TEXT     |                      | Installer filename (e.g., `"python-3.11.7-amd64.exe"`) |
| `url`          | TEXT     |                      | Direct download URL                            |
| `version`      | TEXT     |                      | Version string extracted from filename or tag  |
| `size_mb`      | REAL     | DEFAULT 0            | File size in megabytes                         |
| `source`       | TEXT     |                      | `"github.com"` or `"local"`                    |
| `category`     | TEXT     | DEFAULT `'Other'`    | Software category                              |
| `status`       | TEXT     | DEFAULT `'available'`| `"available"` or `"unavailable"`               |
| `updated_at`   | DATETIME | DEFAULT CURRENT_TIMESTAMP | Last sync time                            |

**Populated:** By `repo_sync.sync()` at startup and on `POST /admin/catalog/refresh`. Uses `INSERT OR REPLACE` (upsert) pattern. Entries not present in the latest GitHub sync are set to `status='unavailable'`.

---

#### `tasks`

Tracks in-progress and completed installation pipeline runs for WebSocket streaming.

| Column          | Type     | Constraints               | Description                                        |
|-----------------|----------|---------------------------|----------------------------------------------------|
| `id`            | TEXT     | PRIMARY KEY               | UUID v4 string                                     |
| `preset`        | TEXT     |                           | Preset or software slug being installed            |
| `status`        | TEXT     | DEFAULT `'pending'`       | `pending`, `running`, `done`, `failed`, `cancelled`|
| `progress`      | INTEGER  | DEFAULT 0                 | Overall percentage 0–100                           |
| `current_step`  | TEXT     |                           | Encoded as `"step_id:step_status"` (e.g., `"download:running"`) |
| `final_message` | TEXT     |                           | LLM-generated completion or error message          |
| `created_at`    | DATETIME | DEFAULT CURRENT_TIMESTAMP | Task creation time                                 |
| `updated_at`    | DATETIME | DEFAULT CURRENT_TIMESTAMP | Last update time                                   |

**Migration:** `ALTER TABLE tasks ADD COLUMN final_message TEXT` runs if the column is missing.

**Created:** `task_manager.create_task(preset)` — called from `POST /chat` when an install intent is detected.
**Updated:** `task_manager.update_task(task_id, status, progress, current_step)` — called by the Orchestrator at each pipeline stage.
**Read:** `GET /ws/progress/{task_id}` polls every 0.5 seconds; `GET /admin/tasks`.

---
## 3. Agent Architecture — Each Agent Individually

All agents inherit from `BaseAgent` (`backend/agents/base_agent.py`) which implements the **ReAct pattern** (Reason → Act → Observe).

### BaseAgent (`backend/agents/base_agent.py`)

```python
class BaseAgent:
    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

    def reason(self, context: Dict[str, Any]) -> str: ...
    def act(self, action: Dict[str, Any]) -> Any: ...
    def observe(self, result: Any) -> Dict[str, Any]: ...

    def run(self, task: Dict[str, Any]) -> Any:
        thought = self.reason(task)
        raw_result = self.act({"thought": thought, "task": task})
        observation = self.observe(raw_result)
        return observation
```

**Logging:** All agents share a single file handler writing to `logs/aurjos.log`. Log format: `%(asctime)s [%(levelname)s] %(name)s — %(message)s`.

---

### Agent 1: DetectionAgent (`backend/agents/detection_agent.py`)

**Class:** `DetectionAgent`
**Responsibility:** Detect which developer tools are installed on the host system, check admin privileges, and measure free disk space.

**Input:** Empty dict `{}`
**Output:**
```python
{
    "installed": {"python": bool, "nodejs": bool, "git": bool, ...},
    "is_admin": bool,
    "free_disk_gb": float
}
```

**Detection Strategy (3-tier):**

1. **CLI probe** (`_probe(cmd)`): Runs `shutil.which(cmd[0])` then `subprocess.run(cmd, timeout=10)`. Zero exit code = installed.
2. **File-system path check** (`_check_paths(slug)`): Checks known install paths in `_WIN_PATHS` dict (e.g., `%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe`).
3. **Windows Registry check** (`_check_registry(slug)`): Scans `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` and `HKCU` equivalent for display name matches using `_REGISTRY_NAMES` patterns.

**Probed tools via CLI (`_PROBE_COMMANDS`):**
```python
{
    "python":     ["python", "--version"],
    "nodejs":     ["node", "--version"],
    "git":        ["git", "--version"],
    "vscode":     ["code", "--version"],
    "docker":     ["docker", "--version"],
    "java":       ["java", "-version"],
    "mysql":      ["mysql", "--version"],
    "postgresql": ["psql", "--version"],
    "mongodb":    ["mongod", "--version"],
    "redis":      ["redis-server", "--version"],
}
```

**GUI-only apps** (no CLI): `rufus`, `vlc`, `7zip`, `notepadpp`, `wiztree`, `windsurf`, `greenshot`, `everything`, `lm` — detected via `_is_installed_gui()` (path + registry).

**Special cases:**
- `python3` on Linux counts as `python`
- Postman: checks `%LOCALAPPDATA%\Programs\Postman\Postman.exe` on Windows, `shutil.which("postman")` elsewhere
- Rufus: also scans `~/Downloads/rufus*.exe` and `~/Desktop/rufus*.exe` via glob

**ASCII Flow:**
```
DetectionAgent.run({})
    │
    ├─ reason() → logs "Scanning PATH for CLI tools..."
    │
    ├─ act()
    │   ├─ for each tool in _PROBE_COMMANDS:
    │   │   ├─ _probe(cmd) → shutil.which + subprocess.run
    │   │   └─ if False: _is_installed_gui(slug) → _check_paths OR _check_registry
    │   ├─ python3 fallback
    │   ├─ postman special case
    │   ├─ GUI-only slugs loop
    │   ├─ _platform_is_admin() → PowerShell IsInRole check
    │   └─ _platform_free_disk_gb() → shutil.disk_usage("C:/")
    │
    └─ observe() → logs found/missing lists
```

---

### Agent 2: DownloadAgent (`backend/agents/download_agent.py`)

**Class:** `DownloadAgent`
**Responsibility:** Download installer binaries from the AuriOS GitHub repository to the local `installers/` directory.

**Input:** `software_name: str`, `progress_callback: callable`
**Output:** Local file path string (e.g., `"installers/python-3.11.7-amd64.exe"`)

**Key method:** `download(software_name, progress_callback) -> str`

**Logic:**
1. Calls `repo_sync.get_download_info(software_name.lower())` to get `{filename, url, size_mb}`.
2. If `is_simulated_host()` (non-Windows): writes a stub file to `/tmp/auri-simulated/`, ticks progress 10→30→60→90→100 with 0.3s delays, returns stub path.
3. Checks if `installers/{filename}` already exists — if so, calls `progress_callback(100)` and returns immediately.
4. Downloads with `requests.get(url, stream=True, timeout=30)`, writing to `{dest}.part` then renaming on completion.
5. Validates `Content-Type` — rejects HTML responses (broken links).
6. Reports progress via `progress_callback(pct)` based on `Content-Length`.

**Retry logic:** 3 attempts with exponential backoff (2s, 4s). On final failure, cleans up partial file and raises `RuntimeError("Download failed after 3 attempts: {e}")`.

**ASCII Flow:**
```
DownloadAgent.download(software_name, cb)
    │
    ├─ repo_sync.get_download_info(slug) → {filename, url}
    │
    ├─ is_simulated_host()? → write stub, tick progress, return
    │
    ├─ file exists? → cb(100), return path
    │
    └─ for attempt in 1..3:
        ├─ requests.get(url, stream=True)
        ├─ check Content-Type (reject HTML)
        ├─ stream to .part file, report progress
        ├─ rename .part → final
        ├─ success → return path
        └─ failure → sleep(2^attempt), retry
            └─ attempt 3 failed → cleanup + raise RuntimeError
```

---

### Agent 3: InstallAgent (`backend/agents/install_agent.py`)

**Class:** `InstallAgent`
**Responsibility:** Execute silent software installation using local installer, winget, or chocolatey as fallback.

**Input:** `software_name: str`, `installer_path: str`
**Output:** `{"success": bool, "error": dict | None}`

**Key method:** `install(software_name, installer_path) -> dict`

**Installation strategy (3-tier):**

**Tier 1 — Local installer:**
- Looks up `CUSTOM_FLAGS[filename]` or falls back to `SILENT_FLAGS[ext]`
- `.msi` files: `msiexec.exe /i {path} {flags}`
- `.exe` files: `{path} {flags}`
- Exit codes 0 and 3010 (reboot required) = success
- Exit code 1620 = corrupted MSI → deletes file, returns structured error
- Error codes 1392, 193, 225 in exception string = corrupted installer → deletes file
- 3 attempts with 2s/4s backoff; on timeout also retries

**Tier 2 — winget fallback:**
```
winget install --id {WINGET_IDS[software]} -e --silent
    --accept-package-agreements --accept-source-agreements
```

**Tier 3 — Chocolatey last resort:**
```
choco install {software_name} -y
```

**Simulation mode:** `is_simulated_host()` → `time.sleep(1.0)`, returns `{"success": True}`.

**`CUSTOM_FLAGS` dict (selected entries):**
```python
"python-3.11.7-amd64.exe":  ["/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0"]
"Git-2.43.0-64-bit.exe":    ["/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-", "/CLOSEAPPLICATIONS"]
"VSCodeSetup-x64-1.85.0.exe": ["/VERYSILENT", "/MERGETASKS=!runcode,addcontextmenufiles,..."]
"postgresql-16.1-1-windows-x64.exe": ["--mode", "unattended", "--unattendedmodeui", "none", ...]
"WindsurfSetup.exe": []   # Squirrel installer, no flags needed
```

**ASCII Flow:**
```
InstallAgent.install(software_name, installer_path)
    │
    ├─ is_simulated_host()? → sleep(1), return success
    │
    ├─ file exists at installer_path?
    │   └─ for attempt in 1..3:
    │       ├─ build cmd (msiexec or direct exe)
    │       ├─ subprocess.run(cmd, timeout=600)
    │       ├─ returncode 0 or 3010 → return success
    │       ├─ returncode 1620 → delete file, return corrupted error
    │       ├─ exception with 1392/193/225 → delete file, return corrupted error
    │       └─ other failure → sleep(2^attempt), retry
    │
    ├─ winget available? → winget install --id {WINGET_IDS[name]}
    │   └─ returncode 0 or 3010 → return success
    │
    ├─ choco available? → choco install {name} -y
    │   └─ returncode 0 or 3010 → return success
    │
    └─ all failed → return {"success": False, "error": {...}}
```

---

### Agent 4: ConfigureAgent (`backend/agents/configure_agent.py`)

**Class:** `ConfigureAgent`
**Responsibility:** Add installed software directories to the Windows user PATH via the registry, and install pip packages.

**Input:** `{"pip_packages": [...], "software_list": [...]}`
**Output:**
```python
{
    "path_updated": bool,
    "path_error": str | None,
    "pip_results": {"package_name": {"success": bool, "error": str | None}}
}
```

**PATH update (`_update_system_path`):**
- Opens `HKEY_CURRENT_USER\Environment` via `winreg`
- Builds list of directories to add based on `software_list`:
  - `python` → Python executable dir + Scripts dir
  - `vscode` → `%LOCALAPPDATA%\Programs\Microsoft VS Code\bin`
  - `nodejs` → `%ProgramFiles%\nodejs`
  - `git` → `%ProgramFiles%\Git\cmd`
  - `docker` → `%ProgramFiles%\Docker\Docker\resources\bin`
- Filters to directories that actually exist on disk
- Appends new entries to existing PATH (deduplicates case-insensitively)
- Broadcasts `WM_SETTINGCHANGE` via `ctypes.windll.user32.SendMessageTimeoutW` so running processes pick up the new PATH
- On non-Windows: returns `(False, "winreg unavailable")`

**pip install (`_pip_install`):**
- Runs `[sys.executable, "-m", "pip", "install", package]`
- Timeout: 300 seconds
- Returns `(True, None)` on success, `(False, stderr)` on failure

**ASCII Flow:**
```
ConfigureAgent.run({"pip_packages": [...], "software_list": [...]})
    │
    ├─ reason() → logs planned PATH dirs and packages
    │
    ├─ act()
    │   ├─ _update_system_path(software_list)
    │   │   ├─ import winreg (Windows only)
    │   │   ├─ build dirs_to_add from software_list
    │   │   ├─ filter to existing dirs
    │   │   ├─ open HKCU\Environment, read PATH
    │   │   ├─ append new entries
    │   │   └─ _broadcast_setting_change() → WM_SETTINGCHANGE
    │   │
    │   └─ for each pip_package:
    │       └─ _pip_install(package) → subprocess python -m pip install
    │
    └─ observe() → logs path_updated, pip_ok, pip_fail
```

---

### Agent 5: ValidationAgent (`backend/agents/validate_agent.py`)

**Class:** `ValidationAgent`
**Responsibility:** Re-run `DetectionAgent` after installation to confirm all expected software is now present.

**Input:** `{"expected_software": ["python", "git", ...]}`
**Output:**
```python
{
    "validation": {"python": bool, "git": bool, ...},
    "full_detection": {"python": bool, "nodejs": bool, ...}
}
```

**Retry loop:** Up to 30 attempts with 2-second sleep between each (total up to 60 seconds). This handles background/forking installers that register themselves after the installer process exits.

**Simulation mode:** `is_simulated_host()` → returns `{"validation": {s: True for s in expected}, "full_detection": {}}` immediately.

**ASCII Flow:**
```
ValidationAgent.run({"expected_software": [...]})
    │
    ├─ reason() → logs expected software list
    │
    ├─ act()
    │   ├─ is_simulated_host()? → return all True
    │   │
    │   └─ for attempt in 0..29:
    │       ├─ DetectionAgent().run({}) → installed_map
    │       ├─ build validation dict from expected vs installed_map
    │       ├─ all(validation.values())? → break
    │       └─ sleep(2)
    │
    └─ observe() → logs passed/failed lists
```

---

### Agent 6: EnvironmentAgent (`backend/agents/environment_agent.py`)

**Class:** `EnvironmentAgent`
**Responsibility:** Create a project folder structure and Python virtual environment at `~/AuriOS_Projects/my_project`.

**Input:** `{"project_path": str}` (optional; defaults to `~/AuriOS_Projects/my_project`)
**Output:**
```python
{
    "project_root": str,
    "venv_created": bool,
    "venv_error": str | None,
    "dirs_created": [str, ...]
}
```

**Project subdirectories created:** `src`, `tests`, `data`, `notebooks`, `docs`

**venv creation:** `subprocess.run([sys.executable, "-m", "venv", str(venv_path)], timeout=120)`

**ASCII Flow:**
```
EnvironmentAgent.run({})
    │
    ├─ reason() → logs planned venv path and subdirs
    │
    ├─ act()
    │   ├─ for subdir in ["", "src", "tests", "data", "notebooks", "docs"]:
    │   │   └─ target.mkdir(parents=True, exist_ok=True)
    │   │
    │   └─ subprocess.run([python, "-m", "venv", venv_path], timeout=120)
    │       ├─ returncode 0 → venv_created = True
    │       └─ returncode != 0 → venv_error = stderr
    │
    └─ observe() → logs project_root and venv_created
```

---
## 4. Ollama Integration

### What Ollama Is

Ollama is a local LLM inference server that runs open-source language models on the user's machine without internet access. AuriOS uses it for natural-language understanding and response generation.

- **Server URL:** `http://localhost:11434` (configurable via `OLLAMA_URL` env var)
- **Model:** `llama3.2:3b` (configurable via `OLLAMA_MODEL` env var)
- **API endpoint used:** `POST /api/chat`

### HTTP Call Parameters

All Ollama calls in `backend/llm/intent_parser.py` use `requests.post()` with:

```python
{
    "model": OLLAMA_MODEL,          # "llama3.2:3b"
    "messages": [...],              # system + history + user
    "stream": False,
    "options": {
        "temperature": 0.3,         # low = deterministic
        "num_predict": 100,         # max tokens in response
        "repeat_penalty": 1.1       # discourage repetition
    }
}
```

Pre-install explanations use `temperature: 0.4, num_predict: 120`. Post-install messages use `temperature: 0.3, num_predict: 100`.

### System Prompt (`_SYSTEM_PROMPT`)

Defined in `backend/llm/intent_parser.py`:

```
You are AuriOS, an AI assistant that helps users install and set up developer software on Windows.

STRICT RULES:
1. Only discuss: (a) installing/setting up software, (b) briefly explaining known tools.
   Known tools: Python, Git, VS Code, Docker, Node.js, Java, MySQL, PostgreSQL, MongoDB,
   Redis, Postman, TensorFlow, PyTorch, scikit-learn, Jupyter, npm, yarn.
2. Off-topic requests → reply with exactly:
   "I'm AuriOS — I can only help with developer software. Try saying 'install Python'..."
3. Tool explanations: 1-2 sentences max, then suggest installing.
4. Keep every reply to 1-3 sentences maximum.
5. NEVER invent facts, software names, version numbers, URLs, or features.
6. NEVER pretend to perform actions you cannot do.
7. Reply in the same language the user used (English, Hinglish, or Urdu).
8. Do NOT output JSON, markdown, bullet points — plain text only.
9. If asked who made you: "I was built by The Automators team."
10. Do NOT repeat the user's message back to them.
```

### Touch Point 1: `_llm_explain_preset(user_message, tools, category)`

Called when a **category intent** is detected (e.g., user says "I need database tools"). Asks the LLM to explain the tools in context and ask for confirmation.

```python
# System prompt fragment:
f"The user wants to set up a {category} environment. "
f"The tools that will be installed are: {tools_str}. "
"In 2-3 sentences: briefly explain what each tool is for, "
"then ask if they want to proceed."
```

**Fallback:** Returns `_CATEGORY_CONVERSATIONS[category].replace("{tools}", tools_str)` if Ollama is offline or response is too short (<20 chars).

### Touch Point 2: `_llm_completion_message(preset, software_list, pip_packages, duration_s)`

Called in `run_orchestrator_background()` after a **successful installation**. Generates a practical completion message with a "how to start" hint.

```python
# System prompt fragment:
f"You just finished a successful installation. "
f"Installed: {tools_str}. Total time: {duration_s} seconds. "
f"To get started: {hint}. "
"In 2-3 sentences: confirm what's ready, give the exact command to get started, "
"and add one encouraging sentence."
```

**Start hints per preset:**
- `python_basic` → `"open a terminal and type: python --version"`
- `python_ml` → `"open a terminal and type: jupyter notebook"`
- `web_dev` → `"open a terminal and type: node --version"`
- `java` → `"open a terminal and type: java --version"`

**Fallback:** `f"Your {preset} environment is ready. Everything installed successfully in {duration_s}s."`

### `_llm_chat(user_message, history)` — General Conversation

Used for all conversational responses that don't match rules or canned replies. Passes the full `_SYSTEM_PROMPT` plus up to 6 recent history messages.

**Fallback on `ConnectionError`:** Returns `"I can't reach Ollama right now. Make sure it's running with: ollama serve"`

**Fallback on other exceptions:** Returns `_GENERAL_FALLBACK` constant.

### Fallback Behavior When Ollama Is Offline

| Scenario | Fallback |
|---|---|
| `_llm_explain_preset()` | Hardcoded `_CATEGORY_CONVERSATIONS[category]` string |
| `_llm_completion_message()` | `"Your {preset} environment is ready..."` |
| `_llm_chat()` | `"I can't reach Ollama right now. Make sure it's running with: ollama serve"` |
| Frontend detects `ollama_offline` error | `"Cannot reach Ollama. Is it running? Try: ollama serve"` |

---
## 5. API / Backend Layer

### Framework

- **FastAPI** with **uvicorn** (ASGI server)
- **Version:** 1.1.0
- **Entry point:** backend/server.py
- **Run command:** python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000

### CORS Middleware

Allows origins: null, http://localhost, http://127.0.0.1, http://localhost:3000, http://127.0.0.1:3000, http://localhost:5173, http://127.0.0.1:5173, app://app. All methods and headers allowed. Credentials allowed.

### Authentication

**Regular users:** Bearer token in Authorization header. Token is a 64-char hex string (secrets.token_hex(32)) stored in the sessions table.

**System Admin:** Token starts with 'admin_' (format: 'admin_' + secrets.token_hex(26)). Validated against preferences.admin_session in the DB.

**_require_admin(authorization):** Checks token starts with 'admin_', then verifies it matches preferences.admin_session. Raises HTTP 403 or 401 on failure.

### Rate Limiting

Brute-force protection on POST /auth/login:

- _login_attempts: dict = defaultdict(list) — ip -> [timestamp, ...]
- _LOGIN_WINDOW = 300 (5 minutes)
- _LOGIN_MAX = 5 (max failed attempts)
- _LOGIN_LOCKOUT = 60 (lockout seconds)

_check_rate_limit(ip) purges old entries, raises HTTP 429 with remaining seconds if locked out.
_record_failed_login(ip) appends timestamp on failure.
_clear_login_attempts(ip) resets on successful login.

### Complete Route Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /auth/signup | None | Create new user. Body: {name, email, password}. |
| POST | /auth/login | None | Login with rate limiting. Returns {token, user}. Admin bypass via admin@jarvis.local. |
| POST | /auth/verify | None | Verify token. Returns {valid, user}. |
| POST | /auth/logout | None | Invalidate session token. |
| POST | /auth/change-password | User token | Change password. Body: {token, current_password, new_password}. |
| POST | /chat | None | Main chat. Body: {message}. Returns {response, task_id, intent, preset_or_software, needs_clarification}. |
| GET | /history | None | Last 50 conversation rows. |
| DELETE | /history | None | Delete all conversations. |
| GET | /system-status | None | Platform info + DetectionAgent results. |
| GET | /system-status-full | None | Ollama + admin + disk + 7 software checks (parallel, 5s timeout). |
| GET | /profile | Bearer optional | user_name + experience + interests. |
| POST | /profile | Bearer optional | Upsert user_name, experience, interests. |
| POST | /profile/reset | None | Delete all preferences. |
| GET | /preferences | None | All key-value preference rows. |
| POST | /preferences | Bearer optional | Upsert single key-value. |
| GET | /installation-history | None | All installation_history rows. |
| GET | /available-software | None | Sorted software catalog. |
| GET | /ping | None | Health check. Returns {status: ok}. |
| POST | /speech/transcribe | None | WAV bytes -> Windows System.Speech transcription. |
| POST | /cancel/{task_id} | None | Mark task cancelled. |
| WS | /ws/progress/{task_id} | None | Stream install progress every 0.5s. |
| GET | /admin/stats | Admin | User/session/install/conversation counts. |
| GET | /admin/dashboard-stats | Admin | Full dashboard: totals, by-day charts, top software, success/fail. |
| GET | /admin/users | Admin | All users + synthetic System Admin row. |
| DELETE | /admin/users/{user_id} | Admin | Delete user + sessions. |
| POST | /admin/users/{user_id}/deactivate | Admin | Set status=inactive, revoke sessions. |
| POST | /admin/users/{user_id}/reactivate | Admin | Set status=active. |
| GET | /admin/sessions | Admin | All active sessions with user info. |
| POST | /admin/sessions/revoke | Admin | Delete specific session. Body: {token}. |
| GET | /admin/installations | Admin | Last 200 installation_history rows. |
| GET | /admin/conversations | Admin | Last 300 conversations (truncated to 120 chars). |
| DELETE | /admin/conversations | Admin | Delete all conversations. |
| GET | /admin/preferences | Admin | All preferences with user join. |
| PUT | /admin/preferences/{key} | Admin | Update preference value. |
| DELETE | /admin/preferences | Admin | Delete all preferences except admin_session. |
| GET | /admin/tasks | Admin | Last 100 tasks. |
| GET | /admin/system-status | Admin | CPU%, RAM%, disk, Ollama, installed software. |
| POST | /admin/catalog/refresh | Admin | Re-run repo_sync.sync(). |
| POST | /admin/catalog/local | Admin | Add/update local catalog entry. |
| DELETE | /admin/catalog/local/{slug} | Admin | Remove catalog entry. |
| GET | /admin/catalog/sync-status | Admin | Last sync timestamp and sync_ok flag. |
| POST | /admin/accounts | Admin | Create admin user. |
| POST | /admin/accounts/reset-password | Admin | Reset user password. user_id=0 rewrites .env. |
| POST | /admin/accounts/revoke/{user_id} | Admin | Demote admin to user, revoke sessions. |
| GET | /admin/config/github | Admin | Read GitHub config. |
| POST | /admin/config/github | Admin | Save GitHub config (token Fernet-encrypted). |
| POST | /admin/config/github/validate | Admin | Validate GitHub token against api.github.com/user. |
| POST | /admin/software/download | Admin | Download via winget -> choco -> GitHub search. |
| POST | /admin/software/upload | Admin | Upload to GitHub release, add to catalog. |

### WebSocket /ws/progress/{task_id}

Polls task_manager.get_task(task_id) every 0.5s. Sends JSON only on state change:
- step: step_id (e.g. "download") or null for terminal signals
- status: step_status (e.g. "running", "done", "failed")
- progress: overall percentage 0-100
- message: human-readable step description
- final_message: LLM-generated completion/error text (only on done/failed/cancelled)

Closes WebSocket when task status is done, cancelled, or failed.

---
## 6. Frontend / Electron Layer

### Electron Main Process (electron/main.js)

Registers 'app://' as a privileged secure scheme before app.whenReady() so Web Speech API works. Creates BrowserWindow with frame=false, titleBarStyle='hidden', contextIsolation=true, nodeIntegration=false. Loads app://app/index.html. Grants microphone permission. Persists window bounds to /preferences on resize/move (500ms debounce). Minimizes to tray on close.

startBackend(): Checks if backend already running by fetching /preferences with 2s timeout. If not: spawns python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 with windowsHide=true.

createTray(): Icon from electron/renderer/assets/icon.png. Context menu: Open AuriOS + Quit. Double-click shows window.

IPC channels:
- window-minimize: mainWindow.minimize()
- window-maximize: toggle maximize/unmaximize
- window-close: mainWindow.hide()
- set-title: mainWindow.setTitle(title)
- request-admin: PowerShell Start-Process -Verb RunAs, then app.quit()

App lifecycle: app.whenReady() -> startBackend() -> createWindow() -> createTray(). window-all-closed is prevented. before-quit: killBackend().

### Preload Script (electron/preload.js)

Exposes window.api via contextBridge.exposeInMainWorld. All methods are HTTP fetch calls to http://127.0.0.1:8000:

| window.api method | HTTP call |
|---|---|
| sendMessage(text) | POST /chat |
| getHistory() | GET /history |
| getProfile(token) | GET /profile with Authorization header |
| getStatus() | GET /system-status-full |
| clearHistory() | DELETE /history |
| setPreference(key, value) | POST /preferences |
| getPreferences() | GET /preferences |
| postProfile(data, token) | POST /profile with Authorization header |
| changePassword(data) | POST /auth/change-password |
| resetProfile() | POST /profile/reset |
| getInstallationHistory() | GET /installation-history |
| cancelTask(taskId) | POST /cancel/{taskId} |
| getAvailableSoftware() | GET /available-software |
| minimize() | ipcRenderer.send('window-minimize') |
| maximize() | ipcRenderer.send('window-maximize') |
| close() | ipcRenderer.send('window-close') |
| setTitle(title) | ipcRenderer.send('set-title', title) |
| requestAdmin() | ipcRenderer.send('request-admin') |

### Renderer Scripts

**app.js** - Main chat logic: sendMessage(), renderMessage(), connectProgressSocket(), conversationManager (localStorage), renderSidebar(), showSoftwareBrowser(), updateStatusBar(), showBackendBanner/hideBackendBanner(), initApp(). SUGGESTIONS array (15 items). Template cards with data-prompt. Status polling every 30s.

**admin.js** - Admin dashboard: loadStats(), loadUsers(), loadInstallations(), loadConversations(), loadSystemStatus(), loadPreferences(), loadSessions(), loadCatalog(). Pure SVG charts: drawLineChart(), drawAreaChart(), drawSparkline(), drawTopSoftwareBars(), drawSuccessFailBars(). apiFetch() adds Bearer token. showToast() with 3.2s dismiss. adminConfirm() promise-based dialog.

**auth.js** - Login/signup: switchTab(), login submit (POST /auth/login, stores token+role in localStorage), signup submit (POST /auth/signup, validates name/password). Password visibility toggle.

**splash.js** - 18s animation sequence: line draw (0-3s), block build (3-7s), text reveal (7-12s), logo lock (12-14s), subtitle typewriter (14-16s), fade (16-18s). Backend polling every 1s via /ping. checkAuthAndOnboarding() verifies token via POST /auth/verify. transitionOut() fades views. Session storage key aurios_splash_played skips animation on reload.

**onboarding.js** - Collects name/experience/interests. POSTs to /profile and /preferences (onboarded=true, setup_date). Transitions to app-view, calls initApp().

**profile.js** - Profile pill toggle, dropdown actions: showMyProfile() (read/edit), showChangePassword(), showInstallHistory(), showPreferences() (voice toggle), logoutUser() (POST /auth/logout + localStorage clear), resetProfile().

**progress-panel.js** - Injected panel: showPanel(presetName, steps, taskId), updateStep(data) with sequential enforcement, hidePanel(), _onAllDone(hadFailures). Cancel button calls cancelTask(). STATUS_ICONS SVGs. STEP_DISPLAY_NAMES map.

**tts.js** - SpeechSynthesis wrapper: speak(text) strips emojis, picks female voice (Zira > Google UK Female > Hazel > en-GB), rate=0.9 pitch=1.15 volume=0.9. stop(), setEnabled(bool). Voice preference from /preferences.

**agent-animation.js** - Canvas particle avatar (240x240): 100 particles, 4 states (idle/listening/processing/speaking), 30-frame smooth transitions, color gradient #6366f1->#a78bfa, center glow, 'A' glyph. setState(state) exported as window.agentAnimation.setState.

**web-api.js** - Browser shim: defines window.api with relative URLs when not already defined by Electron preload. Window controls are no-ops.

### Views in index.html

| Element ID | View | Shown when |
|---|---|---|
| #splash-overlay | Splash animation | App startup |
| #auth-view | Login/Signup | No valid session |
| #onboarding-view | First-run setup | Logged in, onboarded != true |
| #app-view | Main chat app | Logged in and onboarded |
| #admin-view | Admin dashboard | Logged in as admin |

Within #app-view: #dashboard-view (greeting + cards), #chat-messages (bubbles), #progress-panel (injected), #modal-overlay (profile/history/browser).

### CSS Architecture

| File | Purpose |
|---|---|
| main.css | Variables, reset, titlebar, sidebar, chat, status bar, input bar, dashboard |
| auth.css | Auth card, tabs, inputs, password toggle |
| admin.css | Admin sidebar, nav, tables, badges, charts, toast, confirm |
| components.css | Modals, dropdowns, profile pill, install history, preferences |
| progress-panel.css | Sliding panel, step rows, progress bars |
| splash.css | Splash animation keyframes |
| onboarding.css | Onboarding card, radio/checkbox groups |
| agent.css | Avatar canvas wrapper |

Key CSS variables: --bg-primary: #f1f5f9, --accent: #f97316, --text-primary: #0f172a, --titlebar-h: 40px, --statusbar-h: 28px, --sidebar-w: 240px

---

## 7. Module & Function Reference

### backend/server.py

| Function/Class | Signature | Description |
|---|---|---|
| _RowFactoryDB | class | Async context manager for aiosqlite with Row factory, WAL mode, 30s busy timeout |
| get_db() | () -> _RowFactoryDB | Returns context manager for DB_PATH |
| lifespan(app) | async context manager | Creates all 7 tables, runs migrations, backfills preferences, calls repo_sync.sync() |
| _get_admin_hash() | () -> str | Reads ADMIN_PASSWORD_HASH from backend/.env, generates default if missing |
| _check_rate_limit(ip) | (str) -> None | Raises HTTP 429 if IP has >= 5 failed logins in 300s window |
| _record_failed_login(ip) | (str) -> None | Appends current timestamp to _login_attempts[ip] |
| _clear_login_attempts(ip) | (str) -> None | Removes IP from _login_attempts dict |
| _require_admin(authorization) | async (str) -> None | Validates admin_ token against preferences.admin_session |
| _format_software_list() | () -> str | Returns formatted bullet list from repo_sync.get_catalog() |
| run_orchestrator_background(preset, task_id) | async (str, str) -> None | Runs Orchestrator.run(), records installation_history, calls _llm_completion_message on success |

### backend/core/orchestrator.py

| Function/Class | Description |
|---|---|
| Orchestrator.run(preset_name, task_id, progress_callback) | async: runs 6-stage pipeline, calls _cb() at each stage |
| _cb(step, status, pct, msg) | Inner function: calls task_manager.update_task() + progress_callback() |
| _launch(software) | Tries to open GUI app after install. Best-effort, non-blocking |
| _launch_candidates(software) | Returns list of candidate exe paths including portable glob paths |
| PRESET_CONFIGS | dict: preset_name -> {software: [...], pip_packages: [...]} |
| PRETTY | dict: slug -> display name |

### backend/core/task_manager.py

| Method | Description |
|---|---|
| TaskManager.create_task(preset) | Inserts task row, returns UUID string |
| TaskManager.update_task(task_id, status, progress, current_step) | Updates task row |
| TaskManager.get_task(task_id) | Returns task dict or None |
| TaskManager.set_final_message(task_id, msg) | Updates final_message column |
| TaskManager.cancel_task(task_id) | Sets status=cancelled |
| _connect() | Returns sqlite3.Connection with WAL + busy_timeout |
| _ensure_tasks_table() | Creates tasks table if missing, migrates final_message column |

### backend/llm/intent_parser.py

| Function | Description |
|---|---|
| parse_intent(text, history) | Main entry: routes through 6 stages, returns {intent, preset_or_software, needs_clarification, response_text} |
| _rule_based_intent(text) | Deterministic classifier: checks question/negative/status filters, card prompts, install verbs, preset patterns, software patterns |
| _detect_category_intent(text) | Matches category keywords + project clarify regex, calls _llm_explain_preset |
| _resolve_confirmation(text, history) | Checks if 'yes/sure/ok' follows a category prompt in history |
| _canned_reply(text) | Returns pre-canned response for common phrases, or None |
| _llm_chat(user_message, history) | Calls Ollama /api/chat with _SYSTEM_PROMPT + history |
| _llm_explain_preset(user_message, tools, category) | Touch Point 1: pre-install explanation |
| _llm_completion_message(preset, software_list, pip_packages, duration_s) | Touch Point 2: post-install summary |
| _extract_slug(text) | Extracts first word after install verb as slug |
| _normalize_intent(raw) | Maps LLM-invented intent strings to canonical vocabulary |
| _is_url(text) | Returns True if text looks like a URL/domain |
| _is_general_conversation(text) | Returns True if text matches casual/small-talk patterns |
| _sanitize(text) | Removes template placeholder artifacts from LLM output |

### backend/utils/repo_sync.py

| Function | Description |
|---|---|
| sync() | Fetches GitHub releases API, builds catalog, upserts to software_catalog table, updates module-level _catalog cache |
| get_catalog() | Reads software_catalog WHERE status='available' from SQLite, falls back to _catalog cache |
| is_available(slug) | Returns slug in get_catalog() |
| get_download_info(slug) | Returns catalog entry dict or None |
| _slug_from_filename(filename) | Matches filename against _ASSET_PATTERNS to get slug |
| _extract_version(filename, tag) | Extracts version string from filename or tag |

### backend/utils/admin_check.py

| Function | Description |
|---|---|
| is_admin() | Returns True if process has admin privileges. On non-Windows: always True. Uses PowerShell IsInRole check. |
| relaunch_as_admin() | Relaunches current script with UAC via ShellExecuteW. No-op on non-Windows. |
| run_as_admin(executable, args) | Runs specific exe with admin via ShellExecuteW. No-op on non-Windows. |

### backend/utils/platform_utils.py

| Function | Description |
|---|---|
| is_windows() | Returns platform.system() == 'Windows' |
| is_simulated_host() | Returns True on non-Windows or if AURIOS_SIMULATE_INSTALL=1 |
| free_disk_gb() | Returns free disk space in GB for C:/ (Windows) or / (Linux) |

### backend/utils/crypto.py

| Function | Description |
|---|---|
| _get_or_create_key() | Loads or generates Fernet key at data/.secret.key. Sets FILE_ATTRIBUTE_HIDDEN on Windows. |
| get_fernet() | Returns Fernet instance with loaded key |
| encrypt_data(plain_text) | Encrypts string to URL-safe base64 |
| decrypt_data(cipher_text) | Decrypts URL-safe base64 to string. Raises ValueError on failure. |

---

## 8. Request Lifecycle -- End to End

### Example: User types "install python"

Step-by-step walkthrough from keypress to completed installation:

1. User types "install python" in #chat-input and presses Enter
2. sendMessage() in app.js is called
3. isGenerating is set to true, typing indicator shown
4. window.api.sendMessage("install python") -> POST /chat {message: "install python"}

5. POST /chat handler in server.py:
   a. Fetches last 6 conversation rows for context
   b. Inserts user message into conversations table
   c. Calls parse_intent("install python", history) in a thread

6. parse_intent() routing:
   a. Stage 0: _resolve_confirmation() -> None (not a confirmation)
   b. Stage 1: _is_url() -> False
   c. Stage 2: _canned_reply() -> None (not a canned phrase)
   d. Stage 3: _LIST_SOFTWARE_RE -> no match
   e. Stage 3.5: _detect_category_intent() -> None (no category keyword)
   f. Stage 4: _rule_based_intent("install python"):
      - Not a question, not negative, not status query
      - No card prompt match
      - _INSTALL_VERBS matches "install"
      - No preset pattern matches
      - _SOFTWARE_PATTERNS: re.compile(r"\bpython\b") matches
      - Returns {intent: "single_software", preset_or_software: "python", needs_clarification: False}
   g. Returns {intent: "single_software", preset_or_software: "python", response_text: ""}

7. Back in POST /chat:
   a. intent is "single_software" -> in _INSTALL_INTENTS
   b. is_admin() check -> True (or False -> return error message)
   c. free_disk_gb() check -> >= 1.0 GB
   d. repo_sync.is_available("python") -> True
   e. DetectionAgent().run({}) -> installed["python"] = False (not installed)
   f. label = PRETTY["python"] = "Python"
   g. response_text = "Got it! Starting Python setup now. Watch the progress panel on the right."
   h. task_id = task_manager.create_task("python") -> UUID
   i. asyncio.create_task(run_orchestrator_background("python", task_id))
   j. Inserts assistant response into conversations table
   k. Returns {response: "Got it!...", task_id: "uuid-...", intent: "single_software", ...}

8. Frontend receives response:
   a. isGenerating = false, typing indicator hidden
   b. renderMessage('assistant', "Got it!...") -> bubble added to chat
   c. res.task_id is set -> progressPanel.showPanel("python", [...steps...], task_id)
   d. connectProgressSocket(task_id) -> new WebSocket("ws://127.0.0.1:8000/ws/progress/{task_id}")

9. Orchestrator.run("python", task_id, callback) runs in background:

   Stage 1 - Detection (5% -> 15%):
   - _cb("detection", "running", 5, "Resolving package...")
   - DetectionAgent().run({}) -> {installed: {python: False, ...}, free_disk_gb: 45.2, is_admin: True}
   - repo_sync.get_download_info("python") -> {filename: "python-3.11.7-amd64.exe", url: "...", size_mb: 0}
   - to_install = ["python"]
   - _cb("detection", "done", 15, "Need to install: ['python']")

   Stage 2 - Download (20% -> 40%):
   - _cb("download", "running", 20, "Downloading...")
   - DownloadAgent().download("python", cb) -> "installers/python-3.11.7-amd64.exe"
   - _cb("download", "done", 40, "Downloads complete.")

   Stage 3 - Install (42% -> 60%):
   - _cb("install", "running", 42, "Installing silently...")
   - InstallAgent().install("python", "installers/python-3.11.7-amd64.exe")
   - cmd = ["installers/python-3.11.7-amd64.exe", "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0"]
   - subprocess.run(cmd, timeout=600) -> returncode 0
   - _cb("install", "done", 60, "Installation complete.")

   Stage 4 - Configure (62% -> 75%):
   - _cb("configure", "running", 62, "Finalizing setup...")
   - ConfigureAgent().run({pip_packages: [], software_list: ["python"]})
   - _update_system_path(["python"]) -> adds Python dir + Scripts to HKCU\Environment\PATH
   - _cb("configure", "done", 75, "PATH updated")

   Stage 5 - Validate (77% -> 90%):
   - _cb("validate", "running", 77, "Verifying ['python']...")
   - ValidationAgent().run({expected_software: ["python"]})
   - DetectionAgent().run({}) -> installed["python"] = True
   - _cb("validate", "done", 90, "v ['python']")

   Stage 6 - Environment (92% -> 100%):
   - _cb("environment", "running", 92, "Setting up project folder and venv...")
   - EnvironmentAgent().run({}) -> creates ~/AuriOS_Projects/my_project + venv
   - _cb("environment", "done", 100, "venv ready at ~/AuriOS_Projects/my_project")

   Stage 7 - Launch:
   - python not in _LAUNCH_STATIC -> skip

   Completion:
   - task_manager.set_final_message(task_id, "Installation complete.")
   - task_manager.update_task(task_id, "done", 100, "complete")

10. WebSocket streams each _cb() call to frontend:
    - progressPanel.updateStep({step: "detection", status: "running", progress: 5, ...})
    - ... (each stage update)
    - progressPanel.updateStep({step: null, status: "done", progress: 100, final_message: "..."})

11. progressPanel._onAllDone(false):
    - All step bars set to 100% / done
    - Title changes to "All Done!"
    - After 3s: hidePanel(), renderMessage('assistant', final_message)

12. run_orchestrator_background() completes:
    - Inserts row into installation_history (preset_name="python", status="success", duration_s=...)
    - Calls _llm_completion_message("python", ["python"], [], duration_s) -> LLM generates completion text
    - task_manager.set_final_message(task_id, llm_completion_text)

### ASCII Flow Diagram

`
User: "install python"
        |
        v
[app.js sendMessage()]
        |
        v
POST /chat {message: "install python"}
        |
        v
[parse_intent()] -- Stage 4: _rule_based_intent()
        |              -> {intent: "single_software", preset_or_software: "python"}
        v
[server.py /chat handler]
  - admin check
  - disk check
  - repo_sync.is_available("python") -> True
  - DetectionAgent -> not installed
  - task_manager.create_task("python") -> task_id
  - asyncio.create_task(run_orchestrator_background)
  - return {response: "Got it!...", task_id: "..."}
        |
        v
[Frontend]
  - renderMessage('assistant', "Got it!...")
  - progressPanel.showPanel(...)
  - connectProgressSocket(task_id)
        |
        v
[WebSocket /ws/progress/{task_id}] <-- polls DB every 0.5s
        |
        v
[Orchestrator.run() in background]
  Detection -> Download -> Install -> Configure -> Validate -> Environment
        |
        v
[WebSocket sends progress updates]
        |
        v
[progressPanel.updateStep()] on each update
        |
        v
[_onAllDone()] -> hidePanel() -> renderMessage(final_message)
`

---
## 9. Flags, Constants, Config Variables

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| OLLAMA_URL | http://localhost:11434 | Ollama server base URL |
| OLLAMA_MODEL | llama3.2:3b | Model name for all LLM calls |
| AURIOS_SIMULATE_INSTALL | (unset) | Set to '1' to force simulation mode on any OS |

### Rate Limiting Constants (backend/server.py)

| Constant | Value | Description |
|---|---|---|
| _LOGIN_WINDOW | 300 | Seconds to track failed login attempts |
| _LOGIN_MAX | 5 | Max failed attempts before lockout |
| _LOGIN_LOCKOUT | 60 | Lockout duration in seconds |

### PRESET_CONFIGS (backend/core/orchestrator.py)

| Preset | Software | pip_packages |
|---|---|---|
| python_basic | python, vscode, git | [] |
| python_ml | python, vscode, git | tensorflow==2.15.0, torch, scikit-learn, jupyter |
| web_dev | nodejs, vscode, git | [] |
| data_science | python, vscode, git | jupyter, pandas, numpy, matplotlib |
| full_stack | python, nodejs, git, vscode, docker, java, mysql, postgresql, mongodb, redis, postman | [] |
| java | java, vscode, git | [] |

### PRETTY dict (backend/core/orchestrator.py)

Maps slugs to display names: python->Python, nodejs->Node.js, git->Git, vscode->VS Code, docker->Docker, java->Java, mysql->MySQL, postgresql->PostgreSQL, mongodb->MongoDB, redis->Redis, postman->Postman, lm->LM Studio, python_basic->Python basics, python_ml->Python ML, web_dev->web dev, full_stack->full stack, data_science->data science

### CUSTOM_FLAGS (backend/agents/install_agent.py)

Per-installer silent flags keyed by exact filename:
- python-3.11.7-amd64.exe: ['/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0']
- Git-2.43.0-64-bit.exe: ['/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-', '/CLOSEAPPLICATIONS']
- VSCodeSetup-x64-1.85.0.exe: ['/VERYSILENT', '/MERGETASKS=!runcode,addcontextmenufiles,addcontextmenufolders,addtopath']
- node-v20.10.0-x64.msi: ['/quiet', '/norestart']
- vlc-3.0.20-win64.exe: ['/S', '/L=1033']
- WindsurfSetup.exe: [] (Squirrel, no flags)
- WizTree-Setup.exe: ['/S']
- postgresql-16.1-1-windows-x64.exe: ['--mode', 'unattended', '--unattendedmodeui', 'none', '--disable-components', 'stackbuilder']
- mysql-9.5.0-winx64.msi: ['/qn', '/norestart', 'INSTALLDIR=C:\\MySQL']
- Redis-x64-3.0.504.msi: ['/qn', '/norestart']
- mongodb-windows-x86_64-7.0.4-signed.msi: ['/qn', '/norestart']
- amazon-corretto-17-x64-windows-jdk.msi: ['/qn', '/norestart', 'ADDLOCAL=FeatureMain,...']

### SILENT_FLAGS (backend/agents/install_agent.py)

Default flags by extension: .exe -> ['/S'], .msi -> ['/qn', '/norestart']

### WINGET_IDS (backend/agents/install_agent.py)

| Slug | Winget ID |
|---|---|
| python | Python.Python.3.11 |
| nodejs | OpenJS.NodeJS |
| git | Git.Git |
| vscode | Microsoft.VisualStudioCode |
| docker | Docker.DockerDesktop |
| java | Oracle.JDK.17 |
| mysql | Oracle.MySQL |
| postgresql | PostgreSQL.PostgreSQL.17 |
| mongodb | MongoDB.Server |
| redis | Redis.Redis |
| postman | Postman.Postman |
| vlc | VideoLAN.VLC |
| rufus | Rufus.Rufus |
| 7zip | 7zip.7zip |
| notepadpp | Notepad++.Notepad++ |

### _CANNED dict (backend/llm/intent_parser.py)

Pre-canned responses for ~50 common phrases. Key examples:
- 'hi' -> 'Hi! I'm AuriOS...'
- 'how are you' -> 'All systems go! What would you like to install today?'
- 'thanks' -> 'You're welcome! Let me know if you need anything else installed.'
- 'weather' -> _OFFTOPIC_REPLY
- 'i am sad' -> warm redirect to dev tools

### _OFFTOPIC_REPLY (backend/llm/intent_parser.py)

'I'm AuriOS -- I can only help with installing developer software on Windows. Try install Python, install Git, or show available software.'

### _GENERAL_FALLBACK (backend/llm/intent_parser.py)

'I'm AuriOS, your Windows dev-environment assistant! I can install software like Python, Git, VS Code, Docker, and more. Try: install Python or show available software.'

### _CATEGORY_MAP (backend/llm/intent_parser.py)

| Category | Tools |
|---|---|
| database | MySQL, PostgreSQL, MongoDB, Redis |
| ml | Python, TensorFlow, PyTorch, scikit-learn |
| coding | VS Code, Python, Node.js, Java, Git |
| api | Postman, Node.js |
| devops | Docker, Git |
| design | [] |

### _CATEGORY_PATTERNS (backend/llm/intent_parser.py)

Regex patterns mapping text to categories:
- database/sql/nosql/db/storage -> 'database'
- ml/ai/machine learning/deep learning/data science -> 'ml'
- coding/programming/ide/editor/development environment -> 'coding'
- design/ui/ux/graphics/vector/image -> 'design'
- api/rest/graphql/endpoints -> 'api'
- devops/containers/deployment/ci/cd/version control -> 'devops'

### _CARD_PROMPT_PATTERNS (backend/llm/intent_parser.py)

Direct matches for 6 preset cards that bypass install-verb requirement:
- 'create...react' or 'react...project' -> intent: web_dev
- 'configure...postgres/database' -> intent: single_software, postgresql
- 'install...machine learning' -> intent: python_ml
- 'set up...git...github' -> intent: single_software, git

### _CONFIRM_RE (backend/llm/intent_parser.py)

Matches: yes, yeah, yep, yup, sure, ok, okay, go ahead, do it, start, begin, let's go, let's do it, sounds good, go for it, please, haan, ha, bilkul, zaroor, theek hai, chalo

### _CATEGORY_TO_INTENT (backend/llm/intent_parser.py)

| Category | Intent triggered on confirmation |
|---|---|
| ml | python_ml |
| database | database_clarify (still needs clarification) |
| coding | python_basic |
| api | web_dev |
| devops | full_stack |

### _INSTALL_INTENTS set (backend/server.py)

python_basic, python_ml, web_dev, full_stack, data_science, java, single_software

---

## 10. Inter-Agent Communication Map

### Orchestrator -> Agent Data Flow

``nOrchestrator.run(preset_name, task_id, progress_callback)
|
+-- PRESET_CONFIGS[preset_name]
|   -> software_list: [str]
|   -> pip_packages: [str]
|
+-- Stage 1: DetectionAgent().run({})
|   INPUT:  {}
|   OUTPUT: {
|     installed: {python: bool, nodejs: bool, git: bool, ...},
|     is_admin: bool,
|     free_disk_gb: float
|   }
|   USED FOR:
|   - to_install = [s for s in software_list if not installed[s]]
|   - failed_installs if not is_admin or not enough disk
|
+-- Stage 2: DownloadAgent().download(software, cb) [per software]
|   INPUT:  software_name: str, progress_callback: callable
|   OUTPUT: local_filepath: str
|   USED FOR:
|   - installer_paths[software] = filepath
|
+-- Stage 3: InstallAgent().install(software, filepath) [per software]
|   INPUT:  software_name: str, installer_path: str
|   OUTPUT: {success: bool, error: dict|None}
|   USED FOR:
|   - if not success: set_final_message + return
|
+-- Stage 4: ConfigureAgent().run({pip_packages, software_list})
|   INPUT:  {pip_packages: [str], software_list: [str]}
|   OUTPUT: {
|     path_updated: bool,
|     path_error: str|None,
|     pip_results: {pkg: {success: bool, error: str|None}}
|   }
|   USED FOR:
|   - configure_msg construction
|
+-- Stage 5: ValidationAgent().run({expected_software})
|   INPUT:  {expected_software: [str]}
|   OUTPUT: {
|     validation: {software: bool},
|     full_detection: {software: bool}
|   }
|   USED FOR:
|   - if not all_ok: set_final_message + return
|
+-- Stage 6: EnvironmentAgent().run({})
|   INPUT:  {}
|   OUTPUT: {
|     project_root: str,
|     venv_created: bool,
|     venv_error: str|None,
|     dirs_created: [str]
|   }
|   USED FOR:
|   - env_msg construction
|
+-- task_manager.set_final_message(task_id, final_msg)
+-- task_manager.update_task(task_id, 'done', 100, 'complete')
`

### TaskManager <-> WebSocket Data Flow

``nOrchestrator._cb(step, status, pct, msg)
    |
    v
task_manager.update_task(task_id, task_status, pct, f'{step}:{status}')
    |
    v
SQLite tasks table (current_step = 'download:running')
    ^
    | polls every 0.5s
    |
WebSocket /ws/progress/{task_id}
    |
    v
JSON payload -> Frontend WebSocket.onmessage
    |
    v
progressPanel.updateStep(data)
`

---

## 11. Error Handling & Edge Cases

### DetectionAgent

- All subprocess calls wrapped in try/except (FileNotFoundError, TimeoutExpired, OSError)
- Registry access wrapped in try/except ImportError (winreg not available on Linux) and OSError
- python3 fallback: if python probe fails, checks shutil.which('python3')
- Postman: separate path check for Windows vs shutil.which for Linux

### DownloadAgent

- 3 retry attempts with exponential backoff: sleep(2^attempt) = 2s, 4s
- HTML content-type detection: raises RuntimeError if server returns HTML (broken link)
- Partial file cleanup: removes .part file on final failure
- Simulated host: returns stub file immediately, no network call
- ValueError if software not in catalog

### InstallAgent

**Corrupted installer detection:**
- Exit code 1620 (invalid MSI package): deletes installer file, returns structured error with suggestion to re-download
- Exception string contains '1392' (file corrupt), '193' (not valid Win32 app), or '225' (operation not supported): deletes installer, returns corrupted error

**Retry logic:**
- 3 attempts for local installer with sleep(2^attempt) between retries
- TimeoutExpired (600s) also triggers retry
- After 3 local failures: falls through to winget
- winget failure: falls through to choco
- All 3 methods fail: returns {success: False, error: {reason: 'All install methods failed', ...}}

**Error codes:**
- 1603: Permission issue or existing installation conflict
- 1618: Another installation already running
- 3010: Success but reboot required (treated as success)

### ConfigureAgent

- winreg ImportError on non-Windows: returns (False, 'winreg unavailable') gracefully
- PATH update exception: logs error, returns (False, str(exc))
- pip install timeout (300s): returns (False, 'pip install timed out')
- WM_SETTINGCHANGE broadcast failure: logged but not fatal

### ValidationAgent

**Retry loop:** 30 attempts x 2s sleep = up to 60 seconds total wait. Handles background/forking installers that register after the installer process exits.

- Simulated host: returns all True immediately
- If all(validation.values()) after any attempt: breaks early
- Orchestrator checks all_ok: if False, calls set_final_message and returns (pipeline aborts)

### EnvironmentAgent

- Directory creation: each mkdir wrapped in try/except, logs warning on failure but continues
- venv creation: subprocess timeout 120s, captures stderr on failure
- Non-fatal: Orchestrator continues even if venv_created=False

### Orchestrator

- failed_installs (no catalog entry, no admin, insufficient disk): calls set_final_message and returns early
- Download failure: calls set_final_message and returns
- Install failure: calls set_final_message, update_task('failed'), returns
- Validation failure: calls set_final_message, update_task('failed'), returns
- All stages wrapped in asyncio.to_thread() so blocking operations don't block the event loop

### Intent Parser

- Ollama ConnectionError: returns offline message without crashing
- Ollama timeout/HTTP error: returns fallback message
- JSON decode error from LLM: falls back to _GENERAL_FALLBACK
- Template placeholder artifacts (e.g., <current weather>): stripped by _sanitize()
- URL inputs: blocked before reaching LLM
- Off-topic regex: returns _OFFTOPIC_REPLY without LLM call

### Frontend

**Backend offline banner:**
- showBackendBanner(): shown when fetch to /chat or /system-status-full fails
- retryBackend(): called every 10s, hides banner if backend responds
- Graceful degradation: applyStatusUI({ollama_connected: false, is_admin: false, ...}) shows all red indicators

**WebSocket error handling:**
- ws.onerror: sets completed=true
- ws.onclose without completion: renderMessage('assistant', 'Installation did not complete. Please try again.')
- Download retry messages: dlFailCount tracked, shows 'Retrying... (N/3)' messages
- No internet detection: checks message for 'no internet'/'connection error'/'network'

**Auth error handling:**
- Token invalid (401/403 from /auth/verify): purges localStorage token and role, shows auth view
- Network error on login/signup: shows 'Network error. Is the backend running?'
- Rate limit (429): shows error message with wait time

### Admin

- apiFetch() throws on non-OK responses with detail from JSON body
- All section loaders have try/catch: show errRow() on failure
- adminConfirm() prevents accidental destructive actions
- setBtnLoading() prevents double-submit

---

## 12. Install & Startup Sequence

### Electron Startup Sequence

1. protocol.registerSchemesAsPrivileged for 'app://' scheme (secure, standard, supportFetchAPI, corsEnabled) - BEFORE app.whenReady()
2. app.commandLine.appendSwitch for WebSpeechAPI and speech-input
3. app.whenReady() fires:
   - startBackend(): checks if backend running, spawns uvicorn if not
   - createWindow(): loadPrefs() for bounds, creates BrowserWindow, registers protocol handler, loads app://app/index.html
   - createTray(): icon, context menu, double-click handler

### Backend Startup Sequence (lifespan function in server.py)

1. Connect to data/aurjos.db with WAL mode and 30s busy timeout
2. CREATE TABLE IF NOT EXISTS: conversations, preferences, users, sessions, installation_history, software_catalog, tasks
3. Migration: PRAGMA table_info(preferences) -> ALTER TABLE ADD COLUMN user_id if missing
4. Backfill: UPDATE preferences SET user_id=first_user WHERE user_id IS NULL AND key NOT IN system_keys
5. Migration: PRAGMA table_info(users) -> ALTER TABLE ADD COLUMN role, status if missing
6. Migration: tasks table final_message column (handled by task_manager._ensure_tasks_table)
7. db.commit()
8. await asyncio.to_thread(repo_sync.sync) -> fetches GitHub releases API, upserts software_catalog
9. yield -> FastAPI starts serving requests

### Frontend Startup Sequence

1. index.html loads all CSS and script files
2. progress-panel.js injects panel HTML into body
3. splash.js runs:
   - Checks sessionStorage 'aurios_splash_played'
   - If not set: runs 18s animation (line draw -> block build -> text reveal -> logo lock -> subtitle typewriter -> fade)
   - If set: fast path, waits for nextView then transitionOut()
   - setInterval every 1s: fetch /ping
   - On /ping success: starts background /system-status-full fetch, runs checkAuthAndOnboarding()
   - checkAuthAndOnboarding(): POST /auth/verify -> sets nextView (adminView/onboardingView/appView/authView)
   - At 18s (or click/keypress after 3s): transitionOut() fades views, removes overlay after 3s
4. If nextView == appView: window.initApp()
   - GET /profile -> set userName, title, greeting, avatar
   - conversationManager.cleanup()
   - showDashboard(), renderSidebar()
   - Apply cached system status from localStorage
   - updateStatusBar() -> GET /system-status-full -> applyStatusUI()
   - setInterval(updateStatusBar, 30000)
5. If nextView == adminView: window.initAdmin()
   - Loads overview section, starts clock

---

## 13. Glossary

| Term | Definition |
|---|---|
| AuriOS | The application: an Electron + FastAPI desktop AI assistant for Windows developer environment setup |
| Auri | The AI persona name used in the UI (short for AuriOS) |
| Agent | A Python class inheriting BaseAgent that performs one stage of the installation pipeline using the ReAct pattern |
| ReAct | Reason-Act-Observe pattern: each agent has reason(), act(), observe() methods called in sequence |
| Orchestrator | backend/core/orchestrator.py: coordinates all 6 agents in sequence for a given preset |
| Preset | A named configuration of software + pip packages (e.g., python_basic, python_ml, web_dev) |
| Slug | Normalized lowercase identifier for a software package (e.g., 'python', 'nodejs', 'vscode') |
| Task | A UUID-identified installation run tracked in the tasks SQLite table |
| task_manager | Singleton TaskManager instance in backend/core/task_manager.py |
| DetectionAgent | Agent that probes installed software via CLI, file paths, and Windows registry |
| DownloadAgent | Agent that downloads installer binaries from the GitHub software repository |
| InstallAgent | Agent that runs silent installers (local exe/msi -> winget -> choco) |
| ConfigureAgent | Agent that updates Windows PATH via winreg and installs pip packages |
| ValidationAgent | Agent that re-runs DetectionAgent to confirm installation succeeded |
| EnvironmentAgent | Agent that creates project folder structure and Python venv |
| Ollama | Local LLM inference server running llama3.2:3b for natural language understanding |
| llama3.2:3b | The specific LLM model used (3 billion parameters, small/fast) |
| intent | Classified purpose of a user message (e.g., single_software, python_ml, greeting) |
| parse_intent() | Main function in intent_parser.py that routes messages through 6 classification stages |
| _rule_based_intent() | Deterministic regex-based classifier for install requests (no LLM) |
| _llm_chat() | Ollama API call for conversational responses using _SYSTEM_PROMPT |
| Touch Point 1 | _llm_explain_preset(): LLM-generated pre-install explanation for category intents |
| Touch Point 2 | _llm_completion_message(): LLM-generated post-install summary |
| _CANNED | Dict of pre-written responses for common phrases (greetings, acks, farewells) |
| _OFFTOPIC_REPLY | Fixed response for off-topic questions (weather, news, etc.) |
| repo_sync | backend/utils/repo_sync.py: syncs software catalog from GitHub releases API |
| software_catalog | SQLite table caching available software from GitHub releases |
| _FALLBACK_CATALOG | Hardcoded catalog used when GitHub API is unreachable |
| WINGET_IDS | Dict mapping software slugs to Windows Package Manager IDs |
| CUSTOM_FLAGS | Dict mapping installer filenames to their specific silent install flags |
| SILENT_FLAGS | Default silent flags by file extension (.exe -> /S, .msi -> /qn /norestart) |
| _RowFactoryDB | Async context manager for aiosqlite connections with Row factory |
| lifespan | FastAPI async context manager that runs DB setup before serving requests |
| _require_admin() | FastAPI dependency that validates admin_ bearer tokens |
| _LOGIN_WINDOW | 300s window for tracking failed login attempts |
| _LOGIN_MAX | 5 max failed logins before lockout |
| _LOGIN_LOCKOUT | 60s lockout duration after exceeding _LOGIN_MAX |
| contextBridge | Electron API for safely exposing Node.js functionality to renderer |
| window.api | Object exposed by preload.js containing all backend communication methods |
| progress-panel | Sliding UI panel showing real-time installation stage progress |
| progressPanel | window.progressPanel: JS object with showPanel(), updateStep(), hidePanel() |
| connectProgressSocket() | Opens WebSocket to /ws/progress/{taskId} and routes updates to progressPanel |
| conversationManager | localStorage-based conversation store in app.js |
| app:// | Custom Electron protocol serving renderer files as a secure origin |
| WAL mode | SQLite Write-Ahead Logging: allows concurrent reads during writes |
| bcrypt | Password hashing algorithm used for user passwords and admin hash |
| Fernet | Symmetric encryption (from cryptography library) used for GitHub token storage |
| admin@jarvis.local | Special email for the System Admin account (not stored in users table) |
| admin_ prefix | Token prefix for admin sessions (stored in preferences, not sessions table) |
| is_simulated_host() | Returns True on non-Windows or AURIOS_SIMULATE_INSTALL=1; agents skip real operations |
| agentAnimation | window.agentAnimation: canvas particle avatar with setState(idle/listening/processing/speaking) |
| tts | window.tts: text-to-speech wrapper with speak(), stop(), setEnabled() |
| onboarded | preferences key set to 'true' after first-run onboarding completes |
| windowBounds | preferences key storing JSON window position/size for persistence |
| final_message | tasks table column storing LLM-generated completion or error message |
| current_step | tasks table column encoded as 'step_id:step_status' (e.g., 'download:running') |
| _LAUNCH_STATIC | Dict mapping software slugs to GUI executable paths for post-install launch |
| PRETTY | Dict mapping slugs to human-readable display names |
| PRESET_CONFIGS | Dict mapping preset names to {software, pip_packages} configurations |

---

*End of AuriOS Technical Documentation v1.1.0*

