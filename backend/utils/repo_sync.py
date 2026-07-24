"""repo_sync.py — Syncs the AuriOS Software Repository catalog from GitHub.

Fetches the GitHub releases API at startup and caches a mapping of
software slug → {filename, download_url, version, size_mb, display_name}.

The download_agent imports ``get_download_info()`` to get live URLs.
The /available-software endpoint exposes ``get_catalog()`` to the frontend.

Falls back to a hardcoded catalog if GitHub is unreachable (rate-limited,
offline, etc.) so the installation pipeline always works.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional

import requests

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "data" / "aurjos.db"


GITHUB_API_URL = (
    "https://api.github.com/repos/MAR9775/AuriOS-Software-Repository/releases"
)

# ---------------------------------------------------------------------------
# Hardcoded fallback catalog (used when GitHub API is unavailable)
# ---------------------------------------------------------------------------

_FALLBACK_CATALOG: Dict[str, Dict[str, Any]] = {
    "python": {
        "slug": "python", "display_name": "Python",
        "filename": "python-3.11.7-amd64.exe", "version": "3.11.7",
        "url": "https://www.python.org/ftp/python/3.11.7/python-3.11.7-amd64.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "nodejs": {
        "slug": "nodejs", "display_name": "Node.js",
        "filename": "node-v20.10.0-x64.msi", "version": "20.10.0",
        "url": "https://nodejs.org/dist/v20.10.0/node-v20.10.0-x64.msi",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "git": {
        "slug": "git", "display_name": "Git",
        "filename": "Git-2.43.0-64-bit.exe", "version": "2.43.0",
        "url": "https://github.com/git-for-windows/git/releases/download/v2.43.0.windows.1/Git-2.43.0-64-bit.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "vscode": {
        "slug": "vscode", "display_name": "Visual Studio Code",
        "filename": "VSCodeSetup-x64-1.85.0.exe", "version": "1.85.0",
        "url": "https://az764295.vo.msecnd.net/stable/8b3775030ed1a69b13e4f4c628c612102e30a681/VSCodeUserSetup-x64-1.85.0.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "docker": {
        "slug": "docker", "display_name": "Docker Desktop",
        "filename": "Docker-Desktop-Installer.exe", "version": "latest",
        "url": "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "java": {
        "slug": "java", "display_name": "Java (Amazon Corretto 17)",
        "filename": "amazon-corretto-17-x64-windows-jdk.msi", "version": "17",
        "url": "https://corretto.aws/downloads/latest/amazon-corretto-17-x64-windows-jdk.msi",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "mysql": {
        "slug": "mysql", "display_name": "MySQL",
        "filename": "mysql-9.5.0-winx64.msi", "version": "9.5.0",
        "url": "https://dev.mysql.com/get/Downloads/MySQL-9.5/mysql-9.5.0-winx64.msi",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "postgresql": {
        "slug": "postgresql", "display_name": "PostgreSQL",
        "filename": "postgresql-16.1-1-windows-x64.exe", "version": "16.1",
        "url": "https://get.enterprisedb.com/postgresql/postgresql-16.1-1-windows-x64.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "mongodb": {
        "slug": "mongodb", "display_name": "MongoDB",
        "filename": "mongodb-windows-x86_64-7.0.4-signed.msi", "version": "7.0.4",
        "url": "https://downloads.mongodb.com/compass/mongodb-compass-1.41.0-win32-x64.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "redis": {
        "slug": "redis", "display_name": "Redis",
        "filename": "Redis-x64-3.0.504.msi", "version": "3.0.504",
        "url": "https://github.com/microsoftarchive/redis/releases/download/win-3.0.504/Redis-x64-3.0.504.msi",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "postman": {
        "slug": "postman", "display_name": "Postman",
        "filename": "Postman-win64-Setup.exe", "version": "latest",
        "url": "https://dl.pstmn.io/download/latest/win64",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "lm": {
        "slug": "lm", "display_name": "LM Studio",
        "filename": "LM-Studio-Setup.exe", "version": "latest",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v-lm-studio-setup/LM-Studio-Setup.exe",
        "size_mb": 402.4, "tag": "v1.0",
    },
    "oracle": {
        "slug": "oracle", "display_name": "Oracle VirtualBox",
        "filename": "VirtualBox-7.2.4-170995-Win.exe", "version": "7.2.4",
        "url": "https://download.virtualbox.org/virtualbox/7.2.4/VirtualBox-7.2.4-170995-Win.exe",
        "size_mb": 168.4, "tag": "v1.0",
    },
    "7zip": {
        "slug": "7zip", "display_name": "7-Zip",
        "filename": "7z2301-x64.exe", "version": "23.01",
        "url": "https://www.7-zip.org/a/7z2301-x64.exe",
        "size_mb": 1.5, "tag": "v1.0",
    },
    "notepadpp": {
        "slug": "notepadpp", "display_name": "Notepad++",
        "filename": "npp.8.6.2.Installer.x64.exe", "version": "8.6.2",
        "url": "https://github.com/notepad-plus-plus/notepad-plus-plus/releases/download/v8.6.2/npp.8.6.2.Installer.x64.exe",
        "size_mb": 4.2, "tag": "v1.0",
    },
}
# ---------------------------------------------------------------------------
# Asset → slug pattern matching
# ---------------------------------------------------------------------------

_ASSET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"python.*\.(exe|msi)$",      re.I), "python"),
    (re.compile(r"node.*\.(exe|msi)$",        re.I), "nodejs"),
    (re.compile(r"git[-_].*\.exe$",           re.I), "git"),
    (re.compile(r"vscode.*\.exe$",            re.I), "vscode"),
    (re.compile(r"code[-_].*\.exe$",          re.I), "vscode"),
    (re.compile(r"docker.*\.exe$",            re.I), "docker"),
    (re.compile(r"(jdk|corretto).*\.(exe|msi)$", re.I), "java"),
    (re.compile(r"mysql.*\.(exe|msi)$",       re.I), "mysql"),
    (re.compile(r"postgresql.*\.exe$",        re.I), "postgresql"),
    (re.compile(r"mongodb.*\.(exe|msi)$",     re.I), "mongodb"),
    (re.compile(r"redis.*\.(exe|msi)$",       re.I), "redis"),
    (re.compile(r"postman.*\.exe$",           re.I), "postman"),
    (re.compile(r"vlc.*\.(exe|msi)$",         re.I), "vlc"),
    (re.compile(r"rufus.*\.exe$",             re.I), "rufus"),
    (re.compile(r"7z.*\.exe$",                re.I), "7zip"),
    (re.compile(r"notepad\+\+.*\.exe$",       re.I), "notepadpp"),
    (re.compile(r"lm[-_]?studio.*\.exe$",     re.I), "lm"),
]

_DISPLAY_NAMES: Dict[str, str] = {
    e["slug"]: e["display_name"] for e in _FALLBACK_CATALOG.values()
}

# Pretty names for slugs that come only from GitHub (not in fallback catalog)
_DISPLAY_NAMES.update({
    "vlc":       "VLC Media Player",
    "rufus":     "Rufus",
    "7zip":      "7-Zip",
    "notepadpp": "Notepad++",
})


def _slug_from_filename(filename: str) -> Optional[str]:
    for pat, slug in _ASSET_PATTERNS:
        if pat.search(filename):
            return slug
    return None


def _extract_version(filename: str, tag: str) -> str:
    m = re.search(r"\d+\.\d+[\.\d]*", filename)
    if m:
        return m.group(0)
    return tag.lstrip("v") or "?"


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_lock: threading.Lock = threading.Lock()
_catalog: Dict[str, Dict[str, Any]] = {}
_last_sync: float = 0.0
_sync_ok: bool = False   # True when we've had at least one successful GitHub pull


def sync() -> Dict[str, Dict[str, Any]]:
    global _catalog, _last_sync, _sync_ok

    try:
        resp = requests.get(
            GITHUB_API_URL,
            timeout=10,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "AuriOS/1.1",
            },
        )
        resp.raise_for_status()
        releases = resp.json()
    except Exception:
        releases = []

    new_catalog = {}
    if releases:
        for release in releases:
            tag = release.get("tag_name", "")
            release_name = release.get("name", "").strip()
            for asset in release.get("assets", []):
                name = asset.get("name", "")
                slug = _slug_from_filename(name)

                if not slug and release_name:
                    first_word = release_name.split()[0]
                    slug = re.sub(r"[^a-z0-9]+", "", first_word.lower())

                if not slug:
                    m = re.match(r"^([a-zA-Z0-9]+)", name)
                    if m:
                        slug = m.group(1).lower()

                if slug and slug not in new_catalog:
                    new_catalog[slug] = {
                        "slug":         slug,
                        "display_name": release_name if release_name else _DISPLAY_NAMES.get(slug, slug),
                        "filename":     name,
                        "url":          asset.get("browser_download_url", ""),
                        "version":      _extract_version(name, tag),
                        "size_mb":      round(asset.get("size", 0) / (1024 * 1024), 1),
                        "source":       "github.com",
                    }

        if "vlc" in new_catalog:
            new_catalog["vlc"]["url"] = "https://get.videolan.org/vlc/3.0.20/win64/vlc-3.0.20-win64.exe"
            new_catalog["vlc"]["filename"] = "vlc-3.0.20-win64.exe"

    # Merge with fallback if completely empty
    merged = dict(_FALLBACK_CATALOG)
    merged.update(new_catalog)
    
    # Now sync this with SQLite
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        
        # Mark all as unavailable first, unless they exist in merged
        cur.execute("SELECT slug FROM software_catalog")
        existing_slugs = {row['slug'] for row in cur.fetchall()}
        
        for slug, item in merged.items():
            cur.execute('''
                INSERT INTO software_catalog (slug, display_name, filename, url, version, size_mb, source, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'available')
                ON CONFLICT(slug) DO UPDATE SET
                    display_name=excluded.display_name,
                    filename=excluded.filename,
                    url=excluded.url,
                    version=excluded.version,
                    size_mb=excluded.size_mb,
                    source=excluded.source,
                    status='available',
                    updated_at=CURRENT_TIMESTAMP
            ''', (
                slug, item.get('display_name'), item.get('filename'), item.get('url'),
                item.get('version'), item.get('size_mb', 0), item.get('source', 'github.com')
            ))
            
        # Any existing that weren't in merged -> unavailable
        for ex in existing_slugs:
            if ex not in merged:
                cur.execute("UPDATE software_catalog SET status = 'unavailable', updated_at=CURRENT_TIMESTAMP WHERE slug = ?", (ex,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print("Failed to sync catalog with DB:", e)
        pass

    with _lock:
        _catalog   = merged
        _last_sync = time.time()
        _sync_ok   = True

    return dict(merged)

def get_catalog() -> Dict[str, Dict[str, Any]]:
    # Read directly from DB
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("SELECT * FROM software_catalog WHERE status = 'available'")
        rows = cur.fetchall()
        conn.close()
        cat = {}
        for r in rows:
            cat[r['slug']] = dict(r)
        return cat
    except Exception:
        with _lock:
            return dict(_catalog) if _catalog else dict(_FALLBACK_CATALOG)






# Explicit allowlist of slugs that AuriOS knows how to install and validate.
# Any slug from the GitHub repo that is NOT in this set will be treated as
# unavailable, preventing truly unknown release names from being matched.
_KNOWN_SLUGS = {
    # Core dev tools
    "python", "nodejs", "git", "vscode", "docker", "java",
    # Databases
    "mysql", "postgresql", "mongodb", "redis",
    # API / tools
    "postman",
    # Media / utilities
    "vlc", "rufus", "7zip", "notepadpp", "lm", "oracle",
    # Additional tools present in the GitHub repo catalog
    "everything", "wiztree", "windsurf", "greenshot",
    "githubdesktop", "dbeaver", "dotnet", "notion",
    "powertoys", "powertoysuser", "flux", "solar2d",
    "rapidtyping", "klavaro",
}


def is_available(slug: str) -> bool:
    if slug not in _KNOWN_SLUGS:
        return False
    # Check DB catalog first, then fall back to hardcoded catalog
    cat = get_catalog()
    if slug in cat:
        return True
    # Also accept slugs that exist in the fallback catalog even if not in DB
    return slug in _FALLBACK_CATALOG


def get_download_info(slug: str) -> Optional[Dict[str, Any]]:
    """Return catalog entry for *slug*, or None if not in the repo."""
    # DB catalog first (has live GitHub URLs), then fallback
    info = get_catalog().get(slug.lower())
    if info:
        return info
    return _FALLBACK_CATALOG.get(slug.lower())
