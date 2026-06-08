"""
Mises à jour automatiques via GitHub Releases.

- check_for_update() interroge l'API GitHub pour la dernière release et compare
  son tag à la version locale. Échoue toujours en silence (réseau coupé, quota
  d'API, dépôt non configuré) : on ne bloque jamais le démarrage de l'app.
- start_update() télécharge l'installeur en tâche de fond puis le lance en mode
  silencieux. L'installeur (Restart Manager d'Inno Setup) ferme l'app, applique
  la mise à jour, puis la relance. La barre de progression est exposée via
  progress() et interrogée par le frontend.

Aucune donnée n'est envoyée : on ne fait que des GET (manifeste + binaire).
"""
import os
import sys
import ssl
import json
import tempfile
import threading
import subprocess
import urllib.request

from version import __version__

# ====== À CONFIGURER ======================================================
# Ton dépôt GitHub au format "utilisateur/depot". Tant que ça vaut OWNER/REPO,
# la vérification est désactivée (et ne plante pas).
GITHUB_REPO = "leobrimacombe/InstantPrint"
# ==========================================================================

_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_CTX = ssl.create_default_context()

# État partagé lu par /api/update/progress
_progress = {"phase": "idle", "percent": 0, "error": None, "version": None}
_lock = threading.Lock()


def _parse(v: str) -> tuple:
    """'v1.2.3' -> (1, 2, 3). Tolérant aux suffixes (-beta, +build)."""
    v = v.lstrip("vV").split("+")[0].split("-")[0]
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(remote: str, local: str) -> bool:
    return _parse(remote) > _parse(local)


def _http_json(url: str, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "InstantPrint-Updater",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return json.loads(r.read())


def check_for_update() -> dict:
    """Renvoie un dict décrivant l'état des mises à jour. Ne lève jamais."""
    result = {"current": __version__, "update_available": False}
    if "OWNER/REPO" in GITHUB_REPO:
        result["error"] = "Dépôt GitHub non configuré (voir GITHUB_REPO)"
        return result
    try:
        rel = _http_json(_API)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    latest = (rel.get("tag_name") or "").lstrip("vV")
    # On prend le premier asset .exe (l'installeur).
    asset = next((a for a in rel.get("assets", [])
                  if a.get("name", "").lower().endswith(".exe")), None)
    result.update({
        "latest": latest,
        "notes": rel.get("body") or "",
        "name": rel.get("name") or latest,
        "download_url": asset["browser_download_url"] if asset else None,
        "update_available": bool(latest and asset and is_newer(latest, __version__)),
    })
    return result


def progress() -> dict:
    with _lock:
        return dict(_progress)


def _set(**kw) -> None:
    with _lock:
        _progress.update(kw)


def _download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "InstantPrint-Updater"})
    with urllib.request.urlopen(req, timeout=30, context=_CTX) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        read = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            read += len(chunk)
            if total:
                _set(percent=int(read * 100 / total))


def _launch_installer(path: str) -> None:
    """Lance l'installeur en silencieux et se détache pour survivre à la
    fermeture de l'app par le Restart Manager."""
    flags = ["/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS", "/NOCANCEL", "/SP-"]
    creation = 0
    if sys.platform == "win32":
        creation = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path] + flags, creationflags=creation, close_fds=True)


def _worker(url: str, version: str) -> None:
    try:
        _set(phase="downloading", percent=0, error=None, version=version)
        dest = os.path.join(tempfile.gettempdir(), f"InstantPrint-Setup-{version}.exe")
        _download(url, dest)
        _set(phase="launching", percent=100)
        _launch_installer(dest)
        _set(phase="done")
        # L'installeur va fermer cette app sous peu (Restart Manager).
    except Exception as e:
        _set(phase="error", error=f"{type(e).__name__}: {e}")


def start_update(url: str, version: str) -> bool:
    """Démarre le téléchargement + l'installation en tâche de fond."""
    with _lock:
        if _progress["phase"] in ("downloading", "launching"):
            return False  # déjà en cours
    threading.Thread(target=_worker, args=(url, version), daemon=True).start()
    return True
