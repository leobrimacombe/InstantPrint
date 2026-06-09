# -*- mode: python ; coding: utf-8 -*-
"""
Spec PyInstaller pour InstantPrint.

Construit un .exe windowed (sans console) en mode "one-folder" sous
dist/InstantPrint/. Le mode one-folder est volontaire : pymeshlab embarque
beaucoup de DLL et de plugins, et le démarrage est nettement plus rapide
qu'en one-file (pas de ré-extraction à chaque lancement).

    pyinstaller instantprint.spec --noconfirm
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = []
binaries = []
hiddenimports = []

# Paquets natifs lourds : on ramasse tout (DLL, plugins, données).
for pkg in (
    "pymeshlab",
    "igl",
    "scipy",
    "skimage",
    "trimesh",
    "manifold3d",
    "fast_simplification",
    "webview",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# uvicorn/fastapi chargent des sous-modules dynamiquement -> imports cachés.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("fastapi")
hiddenimports += ["main", "repair", "updater", "version", "anyio", "multipart"]

# Nos propres fichiers : le frontend et le code backend.
datas += [
    ("frontend", "frontend"),
    ("backend", "backend"),
]


a = Analysis(
    ["desktop.py"],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InstantPrint",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # <- pas de fenêtre console
    disable_windowed_traceback=False,
    icon="installer/app.ico" if __import__("os").path.exists("installer/app.ico") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="InstantPrint",
)
