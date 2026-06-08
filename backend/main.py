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

app = FastAPI(title="Mesh Repair")

# Formats lisibles par trimesh
ALLOWED = {".stl", ".obj", ".ply", ".glb", ".gltf", ".off", ".3mf", ".dae"}

# Dossier temporaire pour les résultats (token -> chemin)
WORK = Path(tempfile.gettempdir()) / "mesh_repair_jobs"
WORK.mkdir(exist_ok=True)
_JOBS: dict[str, Path] = {}

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
    pitch_ratio: float = Form(0.015),
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

    # Stats AVANT
    try:
        before = repair.stats(repair._load(str(in_path)))
    except Exception as e:
        in_path.unlink(missing_ok=True)
        raise HTTPException(400, f"Impossible de lire le modèle : {e}")

    # Réparer
    fn = repair.METHODS[method]["fn"]
    try:
        if method == "voxel":
            result = fn(str(in_path), pitch_ratio=pitch_ratio)
        else:
            result = fn(str(in_path))
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
    })


@app.get("/api/download/{job}")
def download(job: str):
    path = _JOBS.get(job)
    if not path or not path.exists():
        raise HTTPException(404, "Résultat introuvable ou expiré")
    return FileResponse(str(path), filename="modele_repare.stl",
                        media_type="application/octet-stream")


# Servir le front (doit être monté en dernier pour ne pas masquer /api)
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
