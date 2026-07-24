# AuriOS — Complete Project Explanation
### For Presentation, Jury, and Personal Understanding
**Version 1.1 | April 2026**

---

## What Is AuriOS?

AuriOS is a **Windows desktop application** that acts as an AI-powered assistant for setting up developer environments. Instead of a new developer spending hours downloading software, running installers, fixing PATH errors, and configuring tools — they just talk to AuriOS in plain language.

**Example:**
> User: "I want to do machine learning with Python"
> AuriOS: "For machine learning you'll need Python, TensorFlow, PyTorch, and scikit-learn. Want me to set everything up?"
> User: "yes"
> AuriOS: *Downloads, installs, configures, and verifies everything silently. Opens Jupyter Notebook when done.*

That's the core idea. Everything else in the project supports making that experience work reliably.

---

## The Problem It Solves

Setting up a development environment on Windows is genuinely painful:

- You need to know which software to download
- You need to find the right download links
- You need to run installers with the right settings
- You need to add things to PATH manually
- You need to verify everything actually works
- If something fails, you need to debug it yourself

For a beginner, this can take a full day. AuriOS reduces it to a 5-minute conversation.

---

## High-Level Architecture

AuriOS has **5 layers** that work together:

```
┌─────────────────────────────────────────────────┐
│              USER INTERFACE (Electron)           │
│   Chat window, progress panel, admin console     │
└────────────────────┬────────────────────────────┘
                     │ HTTP / WebSocket
┌────────────────────▼────────────────────────────┐
│              BACKEND (Python FastAPI)            │
│   Receives messages, manages tasks, routes logic │
└──────┬─────────────┬──────────────┬─────────────┘
       │             │              │
┌──────▼──────┐ ┌────▼────┐ ┌──────▼──────────────┐
│   OLLAMA    │ │ SQLite  │ │  AGENT PIPELINE      │
│  (Local AI) │ │  (DB)   │ │  6 specialized agents│
└─────────────┘ └─────────┘ └─────────────────────┘
```

Each layer has a specific job. They don't overlap.

---

## Layer 1 — The User Interface (Electron)

**What it is:** Electron is a framework that lets you build desktop apps using web technologies (HTML, CSS, JavaScript). Think of it as a Chrome browser window that runs as a standalone app.

**Why Electron was chosen:**
- Cross-platform capable (Windows, Mac, Linux)
- Allows using web technologies for the UI
- Has built-in IPC (Inter-Process Communication) for secure communication between the UI and the system
- Large ecosystem, well-documented

**What the UI contains:**

| Screen | Purpose |
|--------|---------|
| Splash screen | Animated intro, checks if user is logged in |
| Auth screen | Login / Sign up |
| Onboarding | First-run setup (name, experience level, interests) |
| Main chat | The conversation interface with Auri |
| Progress panel | Real-time installation progress (slides in from right) |
| Admin console | Full management dashboard (admin users only) |

**Key files:**
- `electron/main.js` — starts the app, spawns the Python backend, manages the window
- `electron/preload.js` — security bridge between UI and system (contextBridge)
- `electron/renderer/scripts/app.js` — all chat logic, sidebar, status bar
- `electron/renderer/scripts/admin.js` — entire admin dashboard
- `electron/renderer/scripts/splash.js` — startup animation and auth routing

**Security note:** Electron uses `contextIsolation: true` and `nodeIntegration: false`. This means the UI cannot directly access Node.js or the file system — it can only use the specific functions exposed through `preload.js`. This is a security best practice.

---

## Layer 2 — The Backend (Python + FastAPI)

**What it is:** A REST API server written in Python using the FastAPI framework, running locally on port 8000.

**Why FastAPI was chosen:**
- Extremely fast (built on Starlette and Pydantic)
- Automatic request validation via Pydantic models
- Built-in async support (needed for WebSockets and background tasks)
- Auto-generates API documentation
- Much faster to write than Flask for structured APIs

**What the backend does:**
1. Receives chat messages from the UI
2. Parses the user's intent (what do they want to install?)
3. Creates a task in the database
4. Starts the installation pipeline in the background
5. Streams progress back to the UI via WebSocket
6. Handles all authentication (login, signup, token verification)
7. Serves the admin API endpoints

**Key file:** `backend/server.py` — 1,800+ lines, contains every API route

**Authentication system:**
- Regular users: bcrypt-hashed passwords, session tokens stored in SQLite
- Admin: special `admin@jarvis.local` account, password hash stored in `.env` file
- Rate limiting: 5 failed login attempts → 60-second lockout (prevents brute force)
- All admin endpoints require a valid `admin_` prefixed token

---

## Layer 3 — The Database (SQLite)

**What it is:** A lightweight, file-based database. The entire database is a single file: `data/aurjos.db`.

**Why SQLite was chosen:**
- No separate database server needed (everything runs locally)
- Perfect for a single-user desktop application
- Zero configuration
- Python has built-in support via `sqlite3`
- Used `aiosqlite` for async operations (non-blocking)

**Tables in the database:**

| Table | What it stores |
|-------|---------------|
| `users` | User accounts (name, email, bcrypt password hash, role, status) |
| `sessions` | Active login tokens linked to users |
| `preferences` | Per-user settings (theme, voice enabled, onboarding status, window size) |
| `conversations` | Every chat message (role: user/assistant, content, timestamp) |
| `tasks` | Installation jobs (status, progress %, current step, final message) |
| `installation_history` | Audit log of every install (what, when, success/fail, duration) |
| `software_catalog` | Available software from GitHub (slug, name, download URL, version, size) |

**WAL Mode:** The database runs in Write-Ahead Logging mode. This allows multiple reads to happen simultaneously while a write is in progress — important because the WebSocket is reading task progress while the installer is writing updates.

---

## Layer 4 — The AI (Ollama + Llama 3.2)

**What Ollama is:** A tool that runs large language models (LLMs) locally on your machine. No internet required, no API keys, no cost per request.

**Why Ollama instead of ChatGPT/OpenAI:**
- Privacy: user conversations never leave the machine
- Cost: completely free, no API billing
- Offline: works without internet
- Control: the system prompt and behavior are fully customizable

**Model used:** `llama3.2:3b` — a 3-billion parameter model. Small enough to run on a laptop CPU, capable enough for the narrow task of understanding install requests.

**What the AI actually does in AuriOS:**

The AI is NOT the brain of the installation system. The installation logic is handled by deterministic code (rules and regex). The AI has two specific jobs:

**Job 1 — Pre-install explanation (Touch Point 1):**
When a user says something like "I want to do machine learning", the system detects the category and calls the AI to generate a natural, contextual explanation:
> "For machine learning you'll need Python as the base, TensorFlow and PyTorch for building models, scikit-learn for classical algorithms, and Jupyter to run experiments interactively. Want me to install and configure all of this?"

**Job 2 — Post-install completion message (Touch Point 2):**
After a successful installation, the AI generates a helpful "here's what's ready and how to start" message:
> "Your machine learning environment is fully set up. To start, open a terminal and run: jupyter notebook — your browser will open with a ready-to-use notebook. You're all set to start building models."

**Everything else** (routing, installation decisions, error handling) is pure code — no AI involved.

**Why this design?** The `llama3.2:3b` model is too small to reliably make installation decisions. It would hallucinate software names, invent wrong commands, and be inconsistent. So the architecture uses rules for decisions and AI only for generating human-friendly text — where occasional imperfection is acceptable.

---

## Layer 5 — The Agent Pipeline (The Orchestrator)

This is the most technically interesting part of AuriOS. When an installation is triggered, the **Orchestrator** runs 6 specialized agents in sequence.

**What an "agent" is:** A Python class with a specific, narrow responsibility. Each agent does one thing and returns a result. The Orchestrator coordinates them.

**The 6 agents:**

### Agent 1: DetectionAgent
**File:** `backend/agents/detection_agent.py`
**Job:** Check what's already installed on the system.

How it detects software:
1. **CLI probe** — runs `python --version`, `git --version` etc. and checks exit code
2. **File path check** — looks for known install paths like `C:\Program Files\Git\cmd\git.exe`
3. **Windows Registry** — scans `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` for display names

Why this matters: If Python is already installed, we skip downloading and installing it. Saves time and bandwidth.

### Agent 2: DownloadAgent
**File:** `backend/agents/download_agent.py`
**Job:** Download the installer files.

Key feature — **local cache:** If `installers/python-3.11.7-amd64.exe` already exists on disk, it skips the download entirely and uses the cached file. This means if you uninstall Python and reinstall it, the second install is instant — no re-download needed.

Downloads with retry logic: 3 attempts with exponential backoff (2s, 4s). Validates that the server didn't return an HTML error page instead of a binary file.

### Agent 3: InstallAgent
**File:** `backend/agents/install_agent.py`
**Job:** Run the installers silently.

**Three-tier installation strategy:**
1. **Local installer first** — uses the downloaded `.exe`/`.msi` with specific silent flags
2. **Winget fallback** — if local installer fails, tries Windows Package Manager
3. **Chocolatey last resort** — if winget also fails

**Silent flags** — each installer has different flags for silent installation:
- Python: `/quiet InstallAllUsers=1 PrependPath=1`
- Git: `/VERYSILENT /NORESTART /NOCANCEL`
- VS Code: `/VERYSILENT /MERGETASKS=addtopath`
- PostgreSQL: `--mode unattended --unattendedmodeui none` (BitRock installer, different format)

**Error handling:** Detects corrupted installers (error codes 1392, 193, 1620), deletes the corrupt file, and returns a structured error with a suggestion.

### Agent 4: ConfigureAgent
**File:** `backend/agents/configure_agent.py`
**Job:** Add installed software to the Windows PATH.

Uses `winreg` (Windows Registry API) to write to `HKEY_CURRENT_USER\Environment\PATH`. After updating, broadcasts a `WM_SETTINGCHANGE` message so running applications (like PowerShell) pick up the new PATH without needing a restart.

Also runs `pip install` for Python packages (TensorFlow, PyTorch, etc.).

### Agent 5: ValidationAgent
**File:** `backend/agents/validate_agent.py`
**Job:** Confirm the installation actually worked.

Re-runs DetectionAgent after installation. Retries up to 30 times with 2-second gaps (60 seconds total) — this handles installers that run in the background and register themselves after the installer process exits.

### Agent 6: EnvironmentAgent
**File:** `backend/agents/environment_agent.py`
**Job:** Create a project folder and Python virtual environment.

Creates `~/AuriOS_Projects/my_project/` with subdirectories (`src`, `tests`, `data`, `notebooks`, `docs`) and runs `python -m venv` to create an isolated Python environment.

---

## Real-Time Progress Streaming (WebSocket)

While the 6 agents are running, the user sees a live progress panel. This works via WebSocket:

```
Orchestrator updates task in SQLite every step
         ↓
WebSocket endpoint polls SQLite every 500ms
         ↓
Sends JSON to frontend: {step, status, progress%, message}
         ↓
Frontend animates progress bars in real time
```

The WebSocket closes automatically when the task reaches `done`, `failed`, or `cancelled`.

---

## The Software Catalog System

AuriOS maintains a catalog of available software synced from a GitHub repository.

**How it works:**
1. On startup, `repo_sync.py` calls the GitHub Releases API for the `MAR9775/AuriOS-Software-Repository` repository
2. Parses each release asset (filename → software slug mapping)
3. Stores everything in the `software_catalog` SQLite table
4. Falls back to a hardcoded catalog if GitHub is unreachable

**Installer caching:** Downloaded installers are saved to the `installers/` folder. On reinstall, the cached file is used directly — no re-download.

---

## Tools & Technologies Used — Complete List

| Tool/Library | Category | Why Used |
|---|---|---|
| **Electron v41** | Desktop framework | Wraps web UI as a native Windows app |
| **Python 3.11** | Backend language | Rich ecosystem, async support, Windows API access |
| **FastAPI** | Web framework | Fast, async, auto-validation, WebSocket support |
| **Uvicorn** | ASGI server | Runs FastAPI, supports hot-reload in development |
| **SQLite + aiosqlite** | Database | Local, zero-config, async-compatible |
| **Ollama** | LLM runtime | Runs AI models locally, no internet/API key needed |
| **llama3.2:3b** | AI model | Small enough for laptop CPU, good at text generation |
| **bcrypt** | Password hashing | Industry standard, slow by design (brute-force resistant) |
| **Fernet (cryptography)** | Encryption | Encrypts GitHub tokens stored in database |
| **winreg** | Windows Registry | Reads/writes PATH environment variables |
| **psutil** | System monitoring | CPU%, RAM%, disk usage for admin dashboard |
| **requests** | HTTP client | Downloads installer files from GitHub/official sources |
| **winget** | Package manager | Windows-native software installer (fallback) |
| **Chocolatey** | Package manager | Third-party package manager (last resort fallback) |
| **WebSocket** | Real-time comms | Streams installation progress to frontend |
| **contextBridge** | Electron security | Safely exposes backend API to renderer process |
| **WAL mode (SQLite)** | DB optimization | Allows concurrent reads during writes |
| **secrets module** | Token generation | Cryptographically secure session tokens |

---

## Security Design

| Threat | How AuriOS handles it |
|--------|----------------------|
| Brute force login | Rate limiting: 5 attempts → 60s lockout |
| Weak passwords | Minimum 8 characters enforced on all forms |
| Password storage | bcrypt hashing (not reversible) |
| Session hijacking | 64-char random hex tokens, stored server-side |
| Admin impersonation | Token validated against DB on every request |
| GitHub token exposure | Fernet-encrypted at rest in SQLite |
| XSS in Electron | contextIsolation=true, nodeIntegration=false |
| Privilege escalation | Role checked server-side, not client-side |

---

## What Makes AuriOS Different

**1. Fully local AI** — No data leaves the machine. No subscription. No API costs.

**2. Intelligent caching** — Downloaded installers are reused. Reinstalling after uninstall is instant.

**3. Three-tier installation** — Local installer → Winget → Chocolatey. If one method fails, it automatically tries the next.

**4. Real-time feedback** — WebSocket streaming means the user sees exactly what's happening at every step, not just a spinner.

**5. Admin console** — A full management dashboard for system administrators, completely separate from the user interface.

**6. Multilingual** — The AI responds in the same language the user writes in (English, Urdu, Hinglish).

---

## Limitations & Honest Assessment

| Limitation | Reason |
|-----------|--------|
| Windows only | Uses winreg, Windows PATH, .exe/.msi installers |
| Requires Ollama running | AI features need `ollama serve` to be active |
| 3b model is small | Can't do complex reasoning, only text generation |
| No GPU on test machine | AI responses take 3-6 seconds on CPU |
| Internet needed for downloads | Installers fetched from GitHub/official sources |

---

## Summary — What Was Built

AuriOS is a full-stack desktop application that combines:
- A native Windows desktop UI (Electron)
- A REST API + WebSocket server (FastAPI)
- A local AI model (Ollama/Llama)
- A 6-stage automated installation pipeline
- A complete admin management console
- A local SQLite database with proper security

The project demonstrates practical application of: desktop application development, REST API design, real-time communication, local AI integration, Windows system programming, database design, and security best practices — all working together in a single coherent product.

---

*Document prepared for AuriOS v1.1 — April 2026*
