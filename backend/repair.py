"""
Méthodes de réparation de mesh 3D pour l'impression.
Chaque méthode prend un chemin de fichier en entrée et renvoie un trimesh.Trimesh.
Toutes testées sur des meshs cassés / assets rippés de jeu.
"""
import trimesh
import numpy as np


def _load(path: str) -> trimesh.Trimesh:
    """Charge n'importe quel format et force un mesh unique (pas une Scene)."""
    m = trimesh.load(path, process=True, force="mesh")
    if isinstance(m, trimesh.Scene):
        m = m.to_geometry()
    return m


def stats(m: trimesh.Trimesh) -> dict:
    """Métriques utiles pour savoir si le modèle est imprimable."""
    return {
        "faces": int(len(m.faces)),
        "vertices": int(len(m.vertices)),
        "watertight": bool(m.is_watertight),  # étanche = imprimable
        "is_volume": bool(m.is_volume),        # vrai solide fermé
        "volume_mm3": round(float(m.volume), 2) if m.is_volume else None,
        "dimensions_mm": [round(float(x), 2) for x in m.extents],
    }


# ---------------------------------------------------------------------------
# METHODE 1 — TRIMESH LIGHT
# Touche légère : corrige normales / winding / doublons et bouche les petits
# trous bien définis. Préserve TOUS les détails. Idéal si le modèle est
# presque bon (petits trous, normales inversées). Ne garantit pas le watertight.
# ---------------------------------------------------------------------------
def trimesh_light(path: str) -> trimesh.Trimesh:
    m = _load(path)
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    trimesh.repair.fix_winding(m)
    trimesh.repair.fix_inversion(m)
    for _ in range(5):
        if m.is_watertight:
            break
        m.fill_holes()
    trimesh.repair.fix_normals(m)
    return m


# ---------------------------------------------------------------------------
# METHODE 2 — PYMESHLAB
# Nettoyage agressif + réparation non-manifold + fermeture de trous.
# Plus puissant que trimesh pour les trous bien formés. Préserve les détails.
# ---------------------------------------------------------------------------
def pymeshlab_repair(path: str) -> trimesh.Trimesh:
    import pymeshlab
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(path)
    ms.meshing_remove_duplicate_vertices()
    ms.meshing_remove_duplicate_faces()
    ms.meshing_remove_unreferenced_vertices()
    ms.meshing_repair_non_manifold_edges()
    ms.meshing_repair_non_manifold_vertices()
    # plusieurs passes : de nouveaux trous peuvent apparaître après réparation
    for _ in range(4):
        try:
            ms.meshing_close_holes(maxholesize=30000)
        except Exception:
            try:
                ms.meshing_repair_non_manifold_edges()
                ms.meshing_close_holes(maxholesize=30000)
            except Exception:
                break
    import tempfile, os
    fd, out = tempfile.mkstemp(suffix=".stl")
    os.close(fd)
    try:
        ms.save_current_mesh(out)
        return _load(out)
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# METHODE 3 — VOXEL REMESH  ⭐ LA PLUS ROBUSTE
# Transforme le modèle en voxels, remplit l'intérieur, puis reconstruit la
# surface (marching cubes). Résultat TOUJOURS étanche, même sur un asset de
# jeu complètement cassé. Perd les détails fins selon la résolution.
# pitch_ratio bas = plus de détails + plus de faces.
# ---------------------------------------------------------------------------
def voxel_remesh(path: str, pitch_ratio: float = 0.015, max_faces: int = 80000) -> trimesh.Trimesh:
    m = _load(path)
    pitch = float(m.extents.max()) * float(pitch_ratio)
    rem = m.voxelized(pitch=pitch).fill().marching_cubes
    # décimation conditionnelle : on ne garde que si ça reste étanche
    if len(rem.faces) > max_faces:
        try:
            dec = rem.simplify_quadric_decimation(face_count=max_faces)
            if dec.is_watertight:
                rem = dec
        except Exception:
            pass
    trimesh.repair.fix_normals(rem)
    return rem


# ---------------------------------------------------------------------------
# METHODE 4 — CONVEX HULL
# Dernier recours : enveloppe convexe pleine autour du modèle. Toujours
# imprimable mais perd toute la forme concave. Utile pour un socle / test.
# ---------------------------------------------------------------------------
def convex_hull(path: str) -> trimesh.Trimesh:
    return _load(path).convex_hull


METHODS = {
    "trimesh_light": {
        "fn": trimesh_light,
        "label": "Trimesh — touche légère",
        "desc": "Corrige normales/doublons, bouche les petits trous. Garde tous les détails.",
        "params": [],
    },
    "pymeshlab": {
        "fn": pymeshlab_repair,
        "label": "PyMeshLab — nettoyage poussé",
        "desc": "Répare le non-manifold et ferme les trous bien définis. Garde les détails.",
        "params": [],
    },
    "voxel": {
        "fn": voxel_remesh,
        "label": "Voxel Remesh — robuste ⭐",
        "desc": "Reconstruit le maillage. Étanche garanti, même sur asset cassé. Perd un peu de détail.",
        "params": [
            {"name": "pitch_ratio", "label": "Résolution (bas = + de détails)",
             "type": "float", "default": 0.015, "min": 0.005, "max": 0.05, "step": 0.005},
        ],
    },
    "convex": {
        "fn": convex_hull,
        "label": "Convex Hull — dernier recours",
        "desc": "Enveloppe pleine. Toujours imprimable mais perd les concavités.",
        "params": [],
    },
}
