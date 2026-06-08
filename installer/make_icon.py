"""
Génère installer/app.ico — l'icône d'InstantPrint.

Un cube isométrique "imprimé en couches" dans l'orange de la marque, sur un
fond sombre arrondi (mêmes couleurs que le frontend). Dessiné en haute
résolution puis ré-échantillonné, et exporté en .ico multi-tailles.

    .venv\\Scripts\\python.exe installer\\make_icon.py
"""
from pathlib import Path
from PIL import Image, ImageDraw

# Palette (cohérente avec frontend/index.html)
BG1 = (22, 24, 29)      # #16181d  fond panneau
BG2 = (14, 15, 18)      # #0e0f12  fond app
ORANGE_TOP = (255, 138, 74)    # face du haut (plus claire)
ORANGE_L = (255, 94, 26)       # #ff5e1a  face gauche (couleur marque)
ORANGE_R = (203, 74, 16)       # face droite (plus sombre)
LAYER = (255, 176, 0)          # #ffb000  lignes de couches

S = 1024            # résolution de travail (supersampling)
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# --- fond : carré arrondi avec léger dégradé vertical ---
pad = int(S * 0.05)
radius = int(S * 0.22)
bg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
bgd = ImageDraw.Draw(bg)
for y in range(S):
    t = y / S
    r = int(BG1[0] + (BG2[0] - BG1[0]) * t)
    g = int(BG1[1] + (BG2[1] - BG1[1]) * t)
    b = int(BG1[2] + (BG2[2] - BG1[2]) * t)
    bgd.line([(0, y), (S, y)], fill=(r, g, b, 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([pad, pad, S - pad, S - pad], radius=radius, fill=255)
img.paste(bg, (0, 0), mask)
d = ImageDraw.Draw(img)

# --- cube isométrique ---
cx, cy = S * 0.5, S * 0.52
w = S * 0.30          # demi-largeur du losange du dessus
dh = S * 0.15         # demi-hauteur du losange (perspective)
H = S * 0.30          # hauteur du corps du cube

# losange du dessus
T = (cx, cy - H / 2 - dh)
R = (cx + w, cy - H / 2)
B = (cx, cy - H / 2 + dh)
L = (cx - w, cy - H / 2)
d.polygon([T, R, B, L], fill=ORANGE_TOP)

# face gauche
L2 = (L[0], L[1] + H)
B2 = (B[0], B[1] + H)
d.polygon([L, B, B2, L2], fill=ORANGE_L)

# face droite
R2 = (R[0], R[1] + H)
d.polygon([B, R, R2, B2], fill=ORANGE_R)

# --- lignes de couches (effet impression 3D) sur les deux faces avant ---
n = 5
lw = max(2, int(S * 0.006))
for i in range(1, n):
    f = i / n
    # face gauche : de l'arête L->L2 vers B->B2
    a = (L[0] + (B[0] - L[0]) * 0, L[1] + (B2[1] - L[1]) * f)
    # interpolation le long de la hauteur sur les deux bords du parallélogramme
    p1 = (L[0], L[1] + H * f)
    p2 = (B[0], B[1] + H * f)
    d.line([p1, p2], fill=LAYER, width=lw)
    p3 = (R[0], R[1] + H * f)
    d.line([p2, p3], fill=(LAYER[0], LAYER[1], LAYER[2], 120), width=lw)

# arêtes nettes du cube
edge = max(2, int(S * 0.004))
d.line([T, R, B, L, T], fill=(255, 220, 200, 90), width=edge)

# --- ré-échantillonnage + export multi-tailles ---
out = Path(__file__).parent / "app.ico"
sizes = [256, 128, 64, 48, 32, 16]
icons = [img.resize((s, s), Image.LANCZOS) for s in sizes]
icons[0].save(out, format="ICO", sizes=[(s, s) for s in sizes], append_images=icons[1:])
print("OK ->", out)
