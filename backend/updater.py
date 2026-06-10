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


def _pick_asset(assets: list) -> dict | None:
    """Choisit l'asset de release adapté à la plateforme courante."""
    if sys.platform == "darwin":
        for ext in (".dmg", ".zip"):
            for a in assets:
                n = a.get("name", "").lower()
                if n.endswith(ext) and ("mac" in n or "darwin" in n or ext == ".dmg"):
                    return a
        return None
    return next((a for a in assets
                 if a.get("name", "").lower().endswith(".exe")), None)


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
    asset = _pick_asset(rel.get("assets", []))
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


# Fonction de fermeture de l'app, fournie par desktop.py (voir set_quit_hook).
_quit_hook = None


def set_quit_hook(fn) -> None:
    """desktop.py enregistre ici de quoi fermer la fenêtre + le process."""
    global _quit_hook
    _quit_hook = fn


def _launch_installer(path: str) -> None:
    """Windows : lance l'installeur Inno Setup en silencieux. macOS : ouvre le
    .zip/.dmg téléchargé dans le Finder (l'utilisateur glisse l'app dans
    Applications)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", path], close_fds=True)
        return
    # /SILENT : barre de progression sans questions. Pas de /RESTARTAPPLICATIONS :
    # l'app se ferme elle-même (ci-dessous) et l'entrée [Run] de l'installeur la
    # relance -> aucun dialogue "fermez l'application".
    flags = ["/SILENT", "/NOCANCEL", "/SP-", "/CLOSEAPPLICATIONS"]
    creation = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path] + flags, creationflags=creation, close_fds=True)


def _worker(url: str, version: str) -> None:
    try:
        _set(phase="downloading", percent=0, error=None, version=version)
        ext = os.path.splitext(url.split("?")[0])[1] or ".exe"
        dest = os.path.join(tempfile.gettempdir(), f"InstantPrint-Setup-{version}{ext}")
        _download(url, dest)
        _set(phase="launching", percent=100)
        _launch_installer(dest)
        _set(phase="done")
        # Windows : on ferme l'app nous-mêmes pour libérer les fichiers et
        # éviter tout dialogue. Délai court : laisse l'UI afficher "redémarrage"
        # et l'installeur démarrer avant qu'on disparaisse.
        if sys.platform == "win32" and _quit_hook:
            threading.Timer(1.5, _quit_hook).start()
    except Exception as e:
        _set(phase="error", error=f"{type(e).__name__}: {e}")


def start_update(url: str, version: str) -> bool:
    """Démarre le téléchargement + l'installation en tâche de fond."""
    with _lock:
        if _progress["phase"] in ("downloading", "launching"):
            return False  # déjà en cours
    threading.Thread(target=_worker, args=(url, version), daemon=True).start()
    return True
