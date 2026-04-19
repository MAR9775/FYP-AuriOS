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
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/python-3.11.7-amd64.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "nodejs": {
        "slug": "nodejs", "display_name": "Node.js",
        "filename": "node-v20.10.0-x64.msi", "version": "20.10.0",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/node-v20.10.0-x64.msi",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "git": {
        "slug": "git", "display_name": "Git",
        "filename": "Git-2.43.0-64-bit.exe", "version": "2.43.0",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/Git-2.43.0-64-bit.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "vscode": {
        "slug": "vscode", "display_name": "Visual Studio Code",
        "filename": "VSCodeSetup-x64-1.85.0.exe", "version": "1.85.0",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/VSCodeSetup-x64-1.85.0.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "docker": {
        "slug": "docker", "display_name": "Docker Desktop",
        "filename": "Docker-Desktop-Installer.exe", "version": "latest",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/Docker-Desktop-Installer.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "java": {
        "slug": "java", "display_name": "Java (JDK 17)",
        "filename": "jdk-17_windows-x64_bin.exe", "version": "17",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/jdk-17_windows-x64_bin.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "mysql": {
        "slug": "mysql", "display_name": "MySQL",
        "filename": "mysql-installer-community-8.0.35.0.msi", "version": "8.0.35",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/mysql-installer-community-8.0.35.0.msi",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "postgresql": {
        "slug": "postgresql", "display_name": "PostgreSQL",
        "filename": "postgresql-16.1-1-windows-x64.exe", "version": "16.1",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/postgresql-16.1-1-windows-x64.exe",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "mongodb": {
        "slug": "mongodb", "display_name": "MongoDB",
        "filename": "mongodb-windows-x86_64-7.0.4-signed.msi", "version": "7.0.4",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/mongodb-windows-x86_64-7.0.4-signed.msi",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "redis": {
        "slug": "redis", "display_name": "Redis",
        "filename": "Redis-x64-3.0.504.msi", "version": "3.0.504",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/Redis-x64-3.0.504.msi",
        "size_mb": 0.0, "tag": "v1.0",
    },
    "postman": {
        "slug": "postman", "display_name": "Postman",
        "filename": "Postman-win64-Setup.exe", "version": "latest",
        "url": "https://github.com/MAR9775/AuriOS-Software-Repository/releases/download/v1.0/Postman-win64-Setup.exe",
        "size_mb": 0.0, "tag": "v1.0",
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
    (re.compile(r"jdk.*\.exe$",               re.I), "java"),
    (re.compile(r"mysql.*\.(exe|msi)$",       re.I), "mysql"),
    (re.compile(r"postgresql.*\.exe$",        re.I), "postgresql"),
    (re.compile(r"mongodb.*\.(exe|msi)$",     re.I), "mongodb"),
    (re.compile(r"redis.*\.(exe|msi)$",       re.I), "redis"),
    (re.compile(r"postman.*\.exe$",           re.I), "postman"),
    (re.compile(r"vlc.*\.(exe|msi)$",         re.I), "vlc"),
    (re.compile(r"rufus.*\.exe$",             re.I), "rufus"),
    (re.compile(r"7z.*\.exe$",                re.I), "7zip"),
    (re.compile(r"notepad\+\+.*\.exe$",       re.I), "notepadpp"),
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
    """Fetch GitHub releases and rebuild the catalog. Thread-safe.

    Always returns a catalog (falls back to hardcoded values on failure).
    """
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
        releases: List[Dict[str, Any]] = resp.json()
    except Exception:
        # Return stale cache or hardcoded fallback — never crash startup
        with _lock:
            return dict(_catalog) if _catalog else dict(_FALLBACK_CATALOG)

    new_catalog: Dict[str, Dict[str, Any]] = {}

    for release in releases:
        tag = release.get("tag_name", "")
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            slug = _slug_from_filename(name)
            if slug and slug not in new_catalog:
                new_catalog[slug] = {
                    "slug":         slug,
                    "display_name": _DISPLAY_NAMES.get(slug, slug),
                    "filename":     name,
                    "url":          asset.get("browser_download_url", ""),
                    "version":      _extract_version(name, tag),
                    "size_mb":      round(asset.get("size", 0) / (1024 * 1024), 1),
                    "tag":          tag,
                }

    # Merge with fallback so any slug missing from GitHub still works
    merged = dict(_FALLBACK_CATALOG)
    merged.update(new_catalog)

    with _lock:
        _catalog   = merged
        _last_sync = time.time()
        _sync_ok   = True

    return dict(merged)


def get_catalog() -> Dict[str, Dict[str, Any]]:
    """Return the current catalog, seeding from hardcoded values if empty."""
    with _lock:
        if not _catalog:
            return dict(_FALLBACK_CATALOG)
        return dict(_catalog)


def is_available(slug: str) -> bool:
    return slug in get_catalog()


def get_download_info(slug: str) -> Optional[Dict[str, Any]]:
    """Return catalog entry for *slug*, or None if not in the repo."""
    return get_catalog().get(slug.lower())


def startup_sync() -> None:
    """Fire a background sync on app startup (non-blocking)."""
    threading.Thread(target=sync, daemon=True, name="repo-sync").start()
