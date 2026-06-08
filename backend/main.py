"""
Backend FastAPI pour la réparation de modèles 3D.
Lance :  uvicorn main:app --reload   (depuis le dossier backend/)
Ou simplement :  python main.py
"""
import os
import sys
import uuid
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import repair
import updater
from version import __version__

app = FastAPI(title="InstantPrint")

# Formats lisibles par trimesh
ALLOWED = {".stl", ".obj", ".ply", ".glb", ".gltf", ".off", ".3mf", ".dae"}

# Dossier temporaire pour les résultats (token -> chemin)
WORK = Path(tempfile.gettempdir()) / "instantprint_jobs"
WORK.mkdir(exist_ok=True)
_JOBS: dict[str, Path] = {}        # job -> STL réparé (téléchargeable)
_PREVIEWS: dict[str, Path] = {}    # job -> STL "avant" (pour le viewer 3D)


def _write_preview(mesh, path: Path, cap: int = 400000) -> None:
    """Écrit un STL d'aperçu. Décime si le maillage est énorme pour garder
    le viewer 3D fluide (n'affecte que l'aperçu, pas le fichier réparé)."""
    pv = mesh
    if len(mesh.faces) > cap:
        try:
            pv = mesh.simplify_quadric_decimation(face_count=cap)
        except Exception:
            pv = mesh
    pv.export(str(path))

# En mode normal le front est dans ../frontend ; une fois empaqueté par
# PyInstaller il est extrait dans sys._MEIPASS/frontend.
if getattr(sys, "frozen", False):
    FRONTEND = Path(sys._MEIPASS) / "frontend"
else:
    FRONTEND = Path(__file__).parent.parent / "frontend"


@app.get("/api/methods")
def list_methods():
    """Liste les méthodes dispo + leurs paramètres pour construire l'UI."""
    return {
        k: {"label": v["label"], "desc": v["desc"], "params": v["params"]}
        for k, v in repair.METHODS.items()
    }


@app.post("/api/repair")
async def do_repair(
    file: UploadFile = File(...),
    method: str = Form(...),
    pitch_ratio: float = Form(0.01),
    depth: int = Form(9),
):
    if method not in repair.METHODS:
        raise HTTPException(400, f"Méthode inconnue : {method}")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Format non supporté : {ext}. Acceptés : {sorted(ALLOWED)}")

    # Sauver l'upload
    job = uuid.uuid4().hex[:12]
    in_path = WORK / f"{job}_in{ext}"
    in_path.write_bytes(await file.read())

    # Stats AVANT + aperçu 3D du modèle d'origine
    try:
        before_mesh = repair._load(str(in_path))
        before = repair.stats(before_mesh)
        prev_path = WORK / f"{job}_before.stl"
        _write_preview(before_mesh, prev_path)
        _PREVIEWS[job] = prev_path
    except Exception as e:
        in_path.unlink(missing_ok=True)
        raise HTTPException(400, f"Impossible de lire le modèle : {e}")

    # Réparer — on ne passe que les paramètres déclarés par la méthode choisie
    spec = repair.METHODS[method]
    available = {"pitch_ratio": pitch_ratio, "depth": depth}
    kwargs = {p["name"]: available[p["name"]]
              for p in spec["params"] if p["name"] in available}
    try:
        result = spec["fn"](str(in_path), **kwargs)
    except Exception as e:
        in_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Échec de la réparation : {e}")

    # Exporter en STL (format universel pour l'impression)
    out_path = WORK / f"{job}_repaired.stl"
    result.export(str(out_path))
    after = repair.stats(result)

    _JOBS[job] = out_path
    in_path.unlink(missing_ok=True)

    return JSONResponse({
        "job": job,
        "method": method,
        "before": before,
        "after": after,
        "download_url": f"/api/download/{job}",
        "preview_before_url": f"/api/preview/{job}",
        "preview_after_url": f"/api/download/{job}",
    })


@app.get("/api/preview/{job}")
def preview(job: str):
    """STL du modèle d'origine, servi en ligne pour le viewer 3D."""
    path = _PREVIEWS.get(job)
    if not path or not path.exists():
        raise HTTPException(404, "Aperçu introuvable ou expiré")
    return FileResponse(str(path), media_type="model/stl")


@app.get("/api/download/{job}")
def download(job: str):
    path = _JOBS.get(job)
    if not path or not path.exists():
        raise HTTPException(404, "Résultat introuvable ou expiré")
    return FileResponse(str(path), filename="modele_repare.stl",
                        media_type="application/octet-stream")


@app.get("/api/version")
def version():
    return {"version": __version__}


@app.get("/api/update/check")
def update_check():
    """Y a-t-il une nouvelle version ? Ne lève jamais (échec réseau = pas de MAJ)."""
    return updater.check_for_update()


@app.post("/api/update/install")
def update_install():
    """Télécharge et lance l'installeur de la dernière version."""
    info = updater.check_for_update()
    if not info.get("update_available") or not info.get("download_url"):
        raise HTTPException(400, "Aucune mise à jour disponible")
    updater.start_update(info["download_url"], info["latest"])
    return {"started": True}


@app.get("/api/update/progress")
def update_progress():
    return updater.progress()


# Servir le front (doit être monté en dernier pour ne pas masquer /api)
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
