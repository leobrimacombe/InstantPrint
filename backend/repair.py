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
# METHODE 1 — ULTRA (WINDING NUMBERS)  ⭐ LA MEILLEURE
# Reconstruction par "fast winding numbers" (Barill et al. 2018 — la techno du
# remesher de Blender) : pour chaque point d'une grille, un test
# intérieur/extérieur robuste MÊME sur un mesh troué/cassé, puis marching
# cubes sur ce champ continu (lissé) -> placement sub-voxel, pas de marches
# d'escalier. Contrairement au voxel binaire, le remplissage ne "fuit" pas
# par les trous, et les pièces fines (ailes...) sont préservées en volume.
# Toujours étanche, dimensions exactes.
# ---------------------------------------------------------------------------
def winding_remesh(path: str, resolution: int = 300, smooth: float = 1.0,
                   max_faces: int = 2000000) -> trimesh.Trimesh:
    import igl
    from scipy import ndimage
    from skimage import measure

    _p("Lecture du modèle", 3)
    m = _load(path)
    # CRUCIAL pour les assets rippés : le winding number est SIGNÉ. Avec des
    # faces orientées n'importe comment, les contributions s'annulent et le
    # champ ne voit plus l'intérieur (résultat : fragments épars). On rend
    # l'orientation cohérente par composant, et |champ| plus bas immunise
    # contre les pièces entièrement retournées.
    _p("Réorientation des faces", 6)
    trimesh.repair.fix_winding(m)
    V = np.ascontiguousarray(m.vertices, dtype=np.float64)
    F = np.ascontiguousarray(m.faces, dtype=np.int64)

    resolution = int(max(64, min(500, resolution)))
    pitch = float(m.extents.max()) / resolution
    pad = 3
    lo = m.bounds[0] - pad * pitch
    shape = np.ceil(m.extents / pitch).astype(int) + 2 * pad

    _p("Préparation de la grille", 8)
    xs = [lo[i] + np.arange(shape[i]) * pitch for i in range(3)]
    gx, gy, gz = np.meshgrid(*xs, indexing="ij")
    Q = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)
    del gx, gy, gz

    # Winding number par lots -> progression réelle pendant le gros du calcul.
    W = np.empty(len(Q))
    chunk = 2_000_000
    n_chunks = max(1, -(-len(Q) // chunk))
    for k, i in enumerate(range(0, len(Q), chunk)):
        _p("Analyse intérieur/extérieur", 10 + int(60 * k / n_chunks))
        W[i:i + chunk] = igl.fast_winding_number(V, F, np.ascontiguousarray(Q[i:i + chunk]))
    del Q
    field = np.abs(W.reshape(shape))

    # Lissage du CHAMP (pas du maillage) : le marching cubes interpole alors
    # en sub-voxel -> plus de marches. Les pièces fines sont sûres ici car le
    # winding number les remplit en volume (pas une feuille d'1 voxel).
    if smooth and float(smooth) > 0:
        _p("Lissage du champ", 74)
        field = ndimage.gaussian_filter(field, sigma=min(float(smooth), 2.0))

    _p("Reconstruction de la surface", 80)
    v, faces, _, _ = measure.marching_cubes(field, level=0.5)
    rem = trimesh.Trimesh(v * pitch + lo, faces, process=True)

    if len(rem.faces) > max_faces:
        _p("Allègement", 92)
        dec = _decimate(rem, max_faces)
        if dec.is_watertight:
            rem = dec
    _p("Finalisation", 97)
    trimesh.repair.fix_normals(rem)
    return rem


# ---------------------------------------------------------------------------
# METHODE 2 — VOXEL REMESH (SOLIDE)
# Voxelisation binaire + remplissage, puis marching cubes sur le champ LISSÉ
# (gaussien) : le lissage du champ place les sommets en sub-voxel -> bien
# moins de marches qu'un lissage de maillage après coup (et beaucoup plus
# rapide). Étanche, dimensions exactes. Attention : sur un mesh très troué à
# haute résolution, le remplissage peut fuir -> préférer Ultra dans ce cas.
# ---------------------------------------------------------------------------
def voxel_remesh(path: str, pitch_ratio: float = 0.006, smooth: float = 0.8,
                 max_faces: int = 2000000) -> trimesh.Trimesh:
    from scipy import ndimage
    from skimage import measure

    _p("Lecture du modèle", 5)
    m = _load(path)
    pitch = float(m.extents.max()) * float(pitch_ratio)
    _p("Voxelisation", 20)
    vox = m.voxelized(pitch=pitch)
    _p("Remplissage du volume", 45)
    grid = vox.fill()
    _p("Reconstruction de la surface", 70)
    pad = 3
    mat = np.pad(grid.matrix.astype(np.float32), pad)
    # sigma plafonné à 1.0 : au-delà, les pièces fines (1 voxel) disparaissent
    sigma = min(float(smooth), 1.0)
    field = ndimage.gaussian_filter(mat, sigma=sigma) if sigma > 0 else mat
    v, faces, _, _ = measure.marching_cubes(field, level=0.5)
    v -= pad
    rem = trimesh.Trimesh(v, faces, process=True)
    # repasse en mm : la transform de la grille porte l'échelle et l'origine
    rem.apply_transform(grid.transform)
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
    "ultra": {
        "fn": winding_remesh,
        "label": "Ultra — Winding Numbers ⭐",
        "desc": "La meilleure : test intérieur/extérieur robuste même sur mesh troué (techno du remesher de Blender), surface sub-voxel sans marches, pièces fines préservées. Étanche garanti.",
        "params": [
            {"name": "resolution", "label": "Résolution (voxels/axe, haut = + fin, + lent)",
             "type": "int", "default": 300, "min": 100, "max": 500, "step": 25},
            {"name": "smooth", "label": "Lissage du champ (0 = brut)",
             "type": "float", "default": 1.0, "min": 0, "max": 2, "step": 0.2},
        ],
    },
    "voxel": {
        "fn": voxel_remesh,
        "label": "Voxel — Solide",
        "desc": "Rapide et sûr sur un modèle déjà fermé. Surface sub-voxel (champ lissé). Sur un mesh très troué à haute finesse, préfère Ultra.",
        "params": [
            {"name": "pitch_ratio", "label": "Finesse (bas = Max ≈1:1, + lent)",
             "type": "float", "default": 0.006, "min": 0.0015, "max": 0.02, "step": 0.0005},
            {"name": "smooth", "label": "Lissage anti-cubes (0 = brut)",
             "type": "float", "default": 0.8, "min": 0, "max": 1, "step": 0.1},
        ],
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
