"""
Méthodes de réparation de mesh 3D pour l'impression.
Chaque méthode prend un chemin de fichier en entrée et renvoie un trimesh.Trimesh.
Toutes produisent (ou visent) un maillage ÉTANCHE, aux bonnes dimensions.
"""
import os
import tempfile

import trimesh
import numpy as np


# Progression partagée, lue par /api/repair/progress (un seul job à la fois
# dans une app de bureau mono-utilisateur).
_PROGRESS = {"stage": "En attente", "percent": 0}


def progress() -> dict:
    return dict(_PROGRESS)


def _p(stage: str, percent: int) -> None:
    _PROGRESS["stage"] = stage
    _PROGRESS["percent"] = int(percent)


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


def _decimate(mesh: trimesh.Trimesh, target: int) -> trimesh.Trimesh:
    """Décimation quadrique préservant les faces planes et les arêtes vives
    (idéal hard-surface). Passe par pymeshlab (C++, rapide et propre)."""
    import pymeshlab
    fd, src = tempfile.mkstemp(suffix=".stl")
    os.close(fd)
    mesh.export(src)
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(src)
    fd2, out = tempfile.mkstemp(suffix=".stl")
    os.close(fd2)
    try:
        ms.meshing_decimation_quadric_edge_collapse(
            targetfacenum=int(target),
            preserveboundary=True,
            preservenormal=True,
            planarquadric=True,   # garde les surfaces planes -> hard-surface
            autoclean=True,
        )
        ms.save_current_mesh(out)
        return _load(out)
    except Exception:
        return mesh  # en cas de souci, on garde le mesh non décimé
    finally:
        for p in (src, out):
            try:
                os.unlink(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# METHODE 1 — MESHFIX (FIDÈLE)  ⭐ PRÉSERVE LE DÉTAIL
# Algorithme de Marco Attene : rend le maillage manifold et étanche en
# CONSERVANT la géométrie d'origine (bouche les trous, retire les
# auto-intersections, répare le non-manifold). Aucune perte de résolution,
# dimensions exactes. Idéal pour les modèles détaillés (vaisseaux SC).
# Si le modèle est vraiment trop cassé, se rabattre sur le Voxel.
# ---------------------------------------------------------------------------
def meshfix_repair(path: str, join_parts: int = 0) -> trimesh.Trimesh:
    import pymeshfix
    _p("Lecture du modèle", 10)
    m = _load(path)
    _p("Réparation (MeshFix)", 45)
    mf = pymeshfix.MeshFix(m.vertices, m.faces)
    # remove_smallest_components=False : on garde toutes les pièces du modèle.
    mf.repair(joincomp=bool(join_parts), remove_smallest_components=False)
    _p("Finalisation", 90)
    r = trimesh.Trimesh(mf.points, mf.faces, process=True)
    trimesh.repair.fix_normals(r)
    return r


# ---------------------------------------------------------------------------
# METHODE 2 — VOXEL REMESH (SOLIDE)  — LE FILET DE SÉCURITÉ
# Transforme le modèle en voxels, remplit l'intérieur, reconstruit la surface
# (marching cubes). Résultat TOUJOURS étanche, aux BONNES dimensions, même sur
# un asset complètement cassé. Décimation finale qui préserve les arêtes pour
# rester léger (utile pour les vaisseaux / hard-surface).
# pitch_ratio bas = plus de détails + plus lent.
# ---------------------------------------------------------------------------
def voxel_remesh(path: str, pitch_ratio: float = 0.006, smooth: int = 8,
                 max_faces: int = 2000000) -> trimesh.Trimesh:
    _p("Lecture du modèle", 5)
    m = _load(path)
    pitch = float(m.extents.max()) * float(pitch_ratio)
    _p("Voxelisation", 20)
    vox = m.voxelized(pitch=pitch)
    _p("Remplissage du volume", 45)
    grid = vox.fill()
    _p("Reconstruction de la surface", 65)
    rem = grid.marching_cubes.copy()
    # CRUCIAL : marching_cubes renvoie un mesh en coordonnées de grille ;
    # on applique la transform (échelle = pitch, origine) pour revenir en mm.
    rem.apply_transform(grid.transform)
    # Lissage Taubin : gomme l'effet "marches d'escalier" des voxels SANS
    # rétrécir le modèle (préserve le volume), et garde l'étanchéité.
    if smooth and int(smooth) > 0:
        _p("Lissage", 80)
        trimesh.smoothing.filter_taubin(rem, iterations=int(smooth))
    if len(rem.faces) > max_faces:
        _p("Allègement", 90)
        dec = _decimate(rem, max_faces)
        # on ne garde la décimation que si elle préserve l'étanchéité
        if dec.is_watertight:
            rem = dec
    _p("Finalisation", 97)
    trimesh.repair.fix_normals(rem)
    return rem


# ---------------------------------------------------------------------------
# METHODE 2 — POISSON (SCREENED)  — DÉTAIL ORGANIQUE
# Reconstruction de surface lisse et détaillée, toujours étanche. Idéale pour
# les formes organiques (personnages, sculptures). Arrondit les arêtes vives,
# donc moins adaptée au hard-surface pur. depth haut = plus fin + plus lent.
# ---------------------------------------------------------------------------
def poisson_repair(path: str, depth: int = 9) -> trimesh.Trimesh:
    import pymeshlab
    _p("Lecture du modèle", 10)
    fd, src = tempfile.mkstemp(suffix=".stl")
    os.close(fd)
    _load(path).export(src)   # normalise l'entrée via trimesh
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(src)
    ms.meshing_remove_duplicate_vertices()
    ms.meshing_remove_unreferenced_vertices()
    _p("Calcul des normales", 30)
    ms.compute_normal_per_vertex()   # Poisson a besoin de normales
    _p("Reconstruction (Poisson)", 55)
    ms.generate_surface_reconstruction_screened_poisson(depth=int(depth), preclean=True)
    _p("Finalisation", 90)
    fd2, out = tempfile.mkstemp(suffix=".stl")
    os.close(fd2)
    try:
        ms.save_current_mesh(out)
        r = _load(out)
    finally:
        for p in (src, out):
            try:
                os.unlink(p)
            except OSError:
                pass
    trimesh.repair.fix_normals(r)
    return r


# ---------------------------------------------------------------------------
# METHODE 4 — CONVEX HULL
# Dernier recours : enveloppe convexe pleine autour du modèle. Toujours
# imprimable mais perd toute la forme concave. Utile pour un socle / test.
# ---------------------------------------------------------------------------
def convex_hull(path: str) -> trimesh.Trimesh:
    return _load(path).convex_hull


METHODS = {
    "voxel": {
        "fn": voxel_remesh,
        "label": "Voxel — Solide ⭐",
        "desc": "Reconstruit un solide étanche, dimensions exactes. Pousse la finesse vers le minimum pour un rendu ≈ 1:1 (plus lent, fichier plus lourd). Le choix sûr.",
        "params": [
            {"name": "pitch_ratio", "label": "Finesse (bas = Max ≈1:1, + lent)",
             "type": "float", "default": 0.006, "min": 0.0015, "max": 0.02, "step": 0.0005},
            {"name": "smooth", "label": "Lissage anti-cubes (0 = brut)",
             "type": "int", "default": 8, "min": 0, "max": 40, "step": 2},
        ],
    },
    "meshfix": {
        "fn": meshfix_repair,
        "label": "Fidèle (MeshFix)",
        "desc": "Répare en gardant la géométrie d'origine (zéro perte de résolution). Excellent si le modèle s'y prête, mais peut échouer sur les assets très fragmentés.",
        "params": [],
    },
    "poisson": {
        "fn": poisson_repair,
        "label": "Poisson — Détail organique",
        "desc": "Surface lisse et détaillée, étanche. Idéal personnages/sculptures. Arrondit les arêtes vives.",
        "params": [
            {"name": "depth", "label": "Détail (haut = + fin, + lent)",
             "type": "int", "default": 9, "min": 6, "max": 11, "step": 1},
        ],
    },
    "convex": {
        "fn": convex_hull,
        "label": "Convex Hull — dernier recours",
        "desc": "Enveloppe pleine. Toujours imprimable mais perd les concavités.",
        "params": [],
    },
}
