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
    # CRUCIAL pour les assets de jeu : le winding number est SIGNÉ et
    # s'annule si la géométrie est "double-face" (chaque panneau dupliqué
    # avec winding inversé pour le rendu — très courant dans les rips).
    # unique_faces déduplique par indices triés -> supprime la copie
    # retournée et restaure le champ. On retire aussi les faces dégénérées.
    _p("Nettoyage (doublons, dégénérées)", 5)
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    # Orientation cohérente par composant (les faces en vrac annulent aussi
    # le champ) ; |champ| plus bas immunise contre les pièces retournées.
    if not m.is_winding_consistent:
        _p("Réorientation des faces", 7)
        trimesh.repair.fix_winding(m)
    V = np.ascontiguousarray(m.vertices, dtype=np.float64)
    F = np.ascontiguousarray(m.faces, dtype=np.int64)

    resolution = int(max(64, min(500, resolution)))
    pitch = float(m.extents.max()) / resolution
    pad = 3
    lo = m.bounds[0] - pad * pitch
    shape = np.ceil(m.extents / pitch).astype(int) + 2 * pad

    # Winding number par lots ; les points de la grille sont générés à la
    # volée par lot (pas de meshgrid géant en RAM) et les lots sont gros
    # (moins de reconstructions de l'octree igl) -> progression réelle.
    N = int(np.prod(shape))
    W = np.empty(N, dtype=np.float64)
    chunk = 8_000_000
    n_chunks = max(1, -(-N // chunk))
    sy, sz = int(shape[1]), int(shape[2])
    for c, start in enumerate(range(0, N, chunk)):
        _p("Analyse intérieur/extérieur", 10 + int(60 * c / n_chunks))
        end = min(N, start + chunk)
        flat = np.arange(start, end, dtype=np.int64)
        kk = flat % sz
        jj = (flat // sz) % sy
        ii = flat // (sz * sy)
        Qc = np.empty((end - start, 3), dtype=np.float64)
        Qc[:, 0] = lo[0] + ii * pitch
        Qc[:, 1] = lo[1] + jj * pitch
        Qc[:, 2] = lo[2] + kk * pitch
        W[start:end] = igl.fast_winding_number(V, F, Qc)
    field = np.abs(np.nan_to_num(W.reshape(shape), nan=0.0, posinf=1.0, neginf=1.0))

    # Filet de sécurité : union avec le remplissage voxel sur la même grille.
    # Si le winding number rate une zone (géométrie pathologique), le voxel
    # la fournit -> Ultra ne peut jamais être pire que la méthode Voxel.
    _p("Voxelisation de contrôle", 72)
    try:
        vox = m.voxelized(pitch=pitch).fill()
        mat = vox.matrix
        origin = np.asarray(vox.transform[:3, 3])
        off = np.round((lo - origin) / pitch).astype(int)
        ax_idx, ax_ok = [], []
        for a in range(3):
            ix = np.arange(shape[a]) + off[a]
            ax_ok.append((ix >= 0) & (ix < mat.shape[a]))
            ax_idx.append(np.clip(ix, 0, mat.shape[a] - 1))
        occ = mat[np.ix_(*ax_idx)].astype(np.float32)
        occ *= (ax_ok[0][:, None, None] & ax_ok[1][None, :, None]
                & ax_ok[2][None, None, :])
        field = np.maximum(field, occ)
    except Exception:
        pass  # le champ winding number seul reste utilisable

    # Lissage du CHAMP (pas du maillage) : le marching cubes interpole alors
    # en sub-voxel -> plus de marches. Les pièces fines sont sûres ici car le
    # winding number les remplit en volume (pas une feuille d'1 voxel).
    if smooth and float(smooth) > 0:
        _p("Lissage du champ", 76)
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
# METHODE 5 — COQUILLE (EXTÉRIEUR FIDÈLE)
# Capture UNIQUEMENT l'enveloppe extérieure, fidèle à ~1 voxel près :
#  1. échantillonne la surface en millions de points -> grille d'occupation
#     (rapide, insensible à l'orientation/trous/double-face)
#  2. fermeture morphologique (dilatation k voxels) pour BOUCHER les
#     ouvertures (tuyères de moteurs, prises d'air...) jusqu'à `close_mm`
#  3. l'extérieur = tout ce qui est accessible depuis le bord de la grille ;
#     le reste (coque + cavités) devient un solide plein
#  4. érosion k voxels -> on revient coller à la surface d'origine
#  5. suppression des débris flottants, lissage protégé (ne peut pas rouvrir
#     de trous), marching cubes sub-voxel
# Tout en scipy/C : nettement plus rapide que le winding number.
# ---------------------------------------------------------------------------
def shell_remesh(path: str, resolution: int = 500, close_mm: float = 2.0,
                 smooth: float = 0.0, max_faces: int = 4000000) -> trimesh.Trimesh:
    from scipy import ndimage
    from skimage import measure

    _p("Lecture du modèle", 3)
    m = _load(path)
    resolution = int(max(64, min(900, resolution)))
    pitch = float(m.extents.max()) / resolution
    k = int(np.ceil(max(0.0, float(close_mm)) / pitch))
    k = min(k, 15)                       # garde-fou perf
    pad = k + 3
    lo = m.bounds[0] - pad * pitch
    shape = tuple((np.ceil(m.extents / pitch).astype(int) + 2 * pad).tolist())

    # 1. surface -> occupation par échantillonnage (couvre ~6x chaque cellule)
    _p("Échantillonnage de la surface", 10)
    n = int(min(25_000_000, max(1_000_000, (m.area / (pitch * pitch)) * 6)))
    surf = np.zeros(shape, dtype=bool)
    done = 0
    while done < n:
        batch = min(5_000_000, n - done)
        pts, _ = trimesh.sample.sample_surface(m, batch)
        idx = np.floor((pts - lo) / pitch).astype(np.int64)
        np.clip(idx, 0, np.asarray(shape) - 1, out=idx)
        surf[idx[:, 0], idx[:, 1], idx[:, 2]] = True
        done += batch
        _p("Échantillonnage de la surface", 10 + int(25 * done / n))
    vi = np.floor((m.vertices - lo) / pitch).astype(np.int64)
    np.clip(vi, 0, np.asarray(shape) - 1, out=vi)
    surf[vi[:, 0], vi[:, 1], vi[:, 2]] = True   # coins/arêtes vives garantis

    # 2. fermeture des ouvertures (dilatation)
    if k > 0:
        _p(f"Bouchage des ouvertures (≤{close_mm:g} mm)", 40)
        work = ndimage.binary_dilation(surf, iterations=k)
    else:
        work = surf

    # 3. extérieur = composantes du vide qui touchent le bord de la grille
    _p("Détection de l'extérieur", 52)
    lbl, _ = ndimage.label(~work)
    border = np.unique(np.concatenate([
        lbl[0, :, :].ravel(), lbl[-1, :, :].ravel(),
        lbl[:, 0, :].ravel(), lbl[:, -1, :].ravel(),
        lbl[:, :, 0].ravel(), lbl[:, :, -1].ravel()]))
    border = border[border != 0]
    solid = ~np.isin(lbl, border)

    # 4. érosion -> la surface extérieure recolle au modèle d'origine
    if k > 0:
        _p("Retour à la surface", 62)
        solid = ndimage.binary_erosion(solid, iterations=k)
        solid |= surf                     # la vraie surface reste toujours là

    # 5. débris flottants (poussières de voxels) -> supprimés
    _p("Nettoyage des débris", 70)
    lbl2, n2 = ndimage.label(solid)
    if n2 > 1:
        counts = np.bincount(lbl2.ravel())
        counts[0] = 0
        keep = counts >= max(30, int(0.0005 * counts.max()))
        solid = keep[lbl2]

    # CHAMP DE DISTANCE EXACT : pour les cellules proches de la frontière,
    # on mesure la vraie distance à la surface d'origine (igl, C++). Le
    # marching cubes place alors chaque sommet EXACTEMENT sur la surface
    # d'origine -> fidélité maximale, arêtes et détails fins préservés
    # (contrairement à un lissage gaussien qui fond les détails).
    import igl
    _p("Champ de distance exact", 74)
    fp = 2.0 * pitch
    field = np.where(solid, fp, -fp).astype(np.float32)   # intérieur positif
    boundary = solid ^ ndimage.binary_erosion(solid)
    band = ndimage.binary_dilation(boundary, iterations=2)
    bi = np.argwhere(band)
    Qb = lo + bi.astype(np.float64) * pitch
    Vd = np.ascontiguousarray(m.vertices, dtype=np.float64)
    Fd = np.ascontiguousarray(m.faces, dtype=np.int64)
    normals = np.asarray(m.face_normals)
    vals = np.empty(len(Qb))
    sgn_mask = np.where(solid[band], 1.0, -1.0)   # même ordre C que argwhere
    step = 4_000_000
    for i in range(0, len(Qb), step):
        _p("Champ de distance exact", 74 + int(8 * i / max(1, len(Qb))))
        Qc = np.ascontiguousarray(Qb[i:i + step])
        sq, tri, C = igl.point_mesh_squared_distance(Qc, Vd, Fd)
        d = np.sqrt(np.maximum(sq, 0.0))
        # Tout près de la surface, le CÔTÉ est donné par la normale du
        # triangle le plus proche -> placement exact (le masque voxel, lui,
        # déborde d'un demi-voxel). Plus loin, le masque fait autorité
        # (bouchons, topologie).
        side = np.einsum("ij,ij->i", Qc - C, normals[tri])
        near = d <= 0.75 * pitch
        s_near = np.where(side >= 0, -1.0, 1.0)   # côté normale = extérieur
        vals[i:i + step] = np.where(near, s_near * d,
                                    sgn_mask[i:i + step] * np.minimum(d, fp))
    field[bi[:, 0], bi[:, 1], bi[:, 2]] = vals.astype(np.float32)

    # lissage OPTIONNEL (0 = brut fidèle, recommandé hard-surface)
    if smooth and float(smooth) > 0:
        _p("Lissage du champ", 83)
        field = ndimage.gaussian_filter(field, sigma=min(float(smooth), 1.2))

    # VERROU TOPOLOGIQUE : géométrie = champ de distance, topologie = masque.
    # Chaque cellule solide reste (un peu) positive, chaque cellule vide
    # (un peu) négative -> la surface vit dans le couloir d'une cellule entre
    # les deux. Ni le lissage ni le bruit d'orientation des normales ne
    # peuvent percer de trou ; coût max : un demi-voxel de déviation locale.
    eps = np.float32(0.05 * pitch)
    field = np.maximum(field, np.where(solid, eps, np.float32(-np.inf)).astype(np.float32))
    field = np.minimum(field, np.where(solid, np.float32(np.inf), -eps).astype(np.float32))

    _p("Reconstruction de la surface", 86)
    v, faces, _, _ = measure.marching_cubes(field, level=0.0)
    # process=False : le marching cubes indexe déjà ses sommets ; la fusion
    # de trimesh créerait des faces orphelines dégénérées (casse l'étanchéité)
    rem = trimesh.Trimesh(v * pitch + lo, faces, process=False)

    if len(rem.faces) > max_faces:
        _p("Allègement", 93)
        dec = _decimate(rem, max_faces)
        if dec.is_watertight:
            rem = dec
    _p("Finalisation", 97)
    trimesh.repair.fix_normals(rem)
    return rem


# ---------------------------------------------------------------------------
# METHODE 6 — NETTOYAGE FIDÈLE (pipeline MeshLab)
# Reproduit le workflow MeshLab manuel pour assets de jeu, SANS remesh :
# la géométrie d'origine est conservée à 100 %.
#   1. soude les points proches + retire doublons (faces et sommets)
#   2. répare le non-manifold (arêtes, puis sommets par séparation)
#   3. bouche les trous (cockpit, passages de roues...) jusqu'à une taille max
# Ne garantit PAS l'étanchéité sur un modèle très cassé (utiliser Coquille
# dans ce cas), mais quand ça passe, c'est la fidélité parfaite.
# ---------------------------------------------------------------------------
def meshlab_clean(path: str, hole_size: int = 150) -> trimesh.Trimesh:
    import pymeshlab
    _p("Lecture du modèle", 5)
    # Diagnostic d'abord : si le modèle est DÉJÀ étanche, on ne touche à
    # rien — la soudure de points sur un mesh sain fusionne les coutures
    # entre panneaux et CASSE l'étanchéité (constaté sur le Gladius).
    pre = _load(path)
    if pre.is_watertight:
        _p("Déjà étanche — rien à réparer", 90)
        trimesh.repair.fix_normals(pre)
        return pre
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(path)

    # Étape 1 — assainir : souder + dédupliquer
    _p("Soudure des points proches", 15)
    ms.meshing_merge_close_vertices()
    ms.meshing_remove_duplicate_faces()
    ms.meshing_remove_duplicate_vertices()

    # Étape 2 — réparer le non-manifold
    _p("Réparation non-manifold", 35)
    ms.meshing_repair_non_manifold_edges()
    try:
        ms.meshing_repair_non_manifold_vertices()
    except Exception:
        pass

    # Étape 3 — boucher les trous (plusieurs passes : la fermeture peut
    # faire apparaître de nouveaux bords à traiter)
    for i in range(3):
        _p("Bouchage des trous", 55 + i * 10)
        try:
            ms.meshing_close_holes(maxholesize=int(hole_size))
        except Exception:
            try:
                ms.meshing_repair_non_manifold_edges()
                ms.meshing_close_holes(maxholesize=int(hole_size))
            except Exception:
                break

    # Étape 4 — export (STL binaire) puis rechargement
    _p("Finalisation", 90)
    fd, out = tempfile.mkstemp(suffix=".stl")
    os.close(fd)
    try:
        ms.save_current_mesh(out)
        r = _load(out)
    finally:
        try:
            os.unlink(out)
        except OSError:
            pass
    # Étape 5 — réparation PAR COMPOSANT de ce qui reste ouvert. Sur les rips
    # très fragmentés (centaines de pièces), le bouchage global plafonne ;
    # pièce par pièce, MeshFix excelle. Escalade par morceau :
    #   fermé -> gardé tel quel (fidélité 100 %)
    #   poussière (<4 faces, non imprimable) -> supprimée
    #   ouvert -> MeshFix ; sinon enveloppe convexe ; sinon gardé ouvert
    if not r.is_watertight:
        _p("Réparation pièce par pièce", 92)
        try:
            import pymeshfix
            parts = []
            for c in r.split(only_watertight=False):
                if c.is_watertight:
                    parts.append(c)
                    continue
                if len(c.faces) < 4:
                    continue
                try:
                    mf = pymeshfix.MeshFix(c.vertices, c.faces)
                    mf.repair(joincomp=False, remove_smallest_components=False)
                    cc = trimesh.Trimesh(mf.points, mf.faces, process=True)
                    if len(cc.faces) > 0 and cc.is_watertight:
                        parts.append(cc)
                        continue
                except Exception:
                    pass
                try:
                    h = c.convex_hull
                    if h.is_watertight:
                        parts.append(h)
                        continue
                except Exception:
                    pass
                parts.append(c)
            if parts:
                r = trimesh.util.concatenate(parts)
        except Exception:
            pass  # pymeshfix indisponible : on garde le résultat du pipeline
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
    "meshlab": {
        "fn": meshlab_clean,
        "label": "Nettoyage fidèle (MeshLab) 🛠",
        "desc": "Soude, déduplique, répare le non-manifold, bouche les trous, puis répare pièce par pièce ce qui reste (MeshFix par composant). Géométrie d'origine conservée au maximum. Ne touche à rien si le modèle est déjà étanche.",
        "params": [
            {"name": "hole_size", "label": "Taille max des trous à boucher",
             "type": "int", "default": 150, "min": 10, "max": 500, "step": 10},
        ],
    },
    "shell": {
        "fn": shell_remesh,
        "label": "Coquille — Extérieur fidèle 🚀",
        "desc": "L'enveloppe extérieure uniquement, posée EXACTEMENT sur la surface d'origine (champ de distance). Bouche les ouvertures, supprime les débris. Pour imprimer en grand : résolution haute + lissage 0.",
        "params": [
            {"name": "resolution", "label": "Résolution (voxels/axe)",
             "type": "int", "default": 500, "min": 100, "max": 900, "step": 25},
            {"name": "close_mm", "label": "Bouchage des ouvertures (mm)",
             "type": "float", "default": 2.0, "min": 0, "max": 8, "step": 0.5},
            {"name": "smooth", "label": "Lissage (0 = brut fidèle)",
             "type": "float", "default": 0, "min": 0, "max": 1.2, "step": 0.1},
        ],
    },
}
