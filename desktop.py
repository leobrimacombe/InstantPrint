"""
Lanceur de l'application desktop InstantPrint.

Démarre le serveur FastAPI sur un port local libre dans un thread de fond,
attend qu'il réponde, puis affiche le frontend dans une fenêtre native
(WebView2 sur Windows). Aucune console, aucun navigateur.

C'est ce fichier qui est empaqueté en .exe par PyInstaller (voir instantprint.spec).
"""
import sys
import time
import socket
import threading
from pathlib import Path

# Rendre les modules du backend importables (main.py, repair.py),
# aussi bien en dev qu'une fois empaqueté.
if getattr(sys, "frozen", False):
    BACKEND = Path(sys._MEIPASS) / "backend"
else:
    BACKEND = Path(__file__).parent / "backend"
sys.path.insert(0, str(BACKEND))

import shutil
import uvicorn
import webview
import main
from main import app


class Api:
    """API native exposée au frontend (window.pywebview.api).

    Dans la fenêtre WebView2, les téléchargements par lien <a> sont bloqués :
    on passe donc par une vraie boîte de dialogue « Enregistrer sous » + copie
    du fichier produit par le backend.
    """

    def save_repaired(self, job: str) -> dict:
        src = main._JOBS.get(job)
        if not src or not Path(src).exists():
            return {"ok": False, "error": "Résultat introuvable ou expiré"}
        window = webview.active_window()
        chosen = window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="modele_repare.stl",
            file_types=("Fichier STL (*.stl)", "Tous les fichiers (*.*)"),
        )
        if not chosen:
            return {"ok": False, "cancelled": True}
        dest = chosen if isinstance(chosen, str) else chosen[0]
        try:
            shutil.copyfile(src, dest)
        except OSError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "path": dest}


# Mutex nommé : permet à l'installeur (Inno Setup, réglage AppMutex) de détecter
# que l'app tourne, de la fermer pour la mise à jour, puis de la relancer.
# Doit correspondre exactement à AppMutex dans installer/instantprint.iss.
APP_MUTEX = "InstantPrint_SingleInstance"


def claim_mutex() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # Handle volontairement non fermé : le mutex vit tant que le process vit.
        ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)
    except Exception:
        pass


def find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORT = find_free_port()


def run_server() -> None:
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def wait_for_server(port: int, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main() -> None:
    claim_mutex()
    threading.Thread(target=run_server, daemon=True).start()
    wait_for_server(PORT)
    webview.create_window(
        "InstantPrint",
        f"http://127.0.0.1:{PORT}",
        js_api=Api(),
        width=1200,
        height=850,
        min_size=(820, 600),
    )
    webview.start()


if __name__ == "__main__":
    main()
