# Release automatique Windows + macOS (GitHub Actions)

Le workflow `.github/workflows/release.yml` construit l'app sur des machines
Windows **et** macOS dans le cloud et attache les fichiers à la release.

Publier une version :
1. bump la version dans `backend/version.py` ET `installer/instantprint.iss`
2. `git commit` + `git push`
3. `git tag v1.3.0` puis `git push origin v1.3.0`
→ GitHub Actions fait le reste (suivi dans l'onglet **Actions** du repo).
La release contiendra `InstantPrint-Setup-1.3.0.exe` (Windows) et
`InstantPrint-macOS-1.3.0.zip` (macOS, app à glisser dans Applications).

Note macOS : app non signée → au premier lancement, clic droit → Ouvrir.

# Construire l'application Windows (.exe + installeur)

On garde 100 % du code Python. On l'emballe en une vraie app de bureau :
fenêtre native (WebView2) + serveur FastAPI interne, sans console ni navigateur.

```
desktop.py            -> lanceur : démarre le serveur + ouvre la fenêtre native
instantprint.spec      -> recette PyInstaller (gère les DLL de pymeshlab etc.)
installer/instantprint.iss -> recette Inno Setup (génère setup.exe)
build.bat             -> fait tout : exe puis installeur
```

## Prérequis (une seule fois)

1. **Python 3.9 – 3.13** (3.13 fonctionne avec les versions récentes de
   pymeshlab). Vérifie : `python --version`.
2. **Inno Setup 6** pour l'installeur : https://jrsoftware.org/isdl.php
   (Sans lui, tu auras quand même le `.exe` portable, juste pas le `setup.exe`.)

## Construire

Double-clic sur **`build.bat`** (ou en terminal). Ça :

1. crée le venv et installe tout,
2. lance PyInstaller → `dist\InstantPrint\InstantPrint.exe` (app portable, dossier complet),
3. lance Inno Setup → `installer\Output\InstantPrint-Setup.exe` (installeur).

## Tester avant l'installeur

```
dist\InstantPrint\InstantPrint.exe
```
La fenêtre doit s'ouvrir et les 4 méthodes apparaître. Si oui, l'installeur est bon.

## Distribuer

Donne **`InstantPrint-Setup.exe`** à tes utilisateurs. Il installe dans
Program Files, crée un raccourci menu Démarrer (et bureau en option), et
s'enlève proprement via « Ajouter/Supprimer des programmes ».

## Pièges connus

- **`python --version` = 3.13** → désinstalle / installe 3.12, ou crée le venv
  avec `py -3.12 -m venv .venv`. pymeshlab ne s'installe pas sinon.
- **`iscc` introuvable** → ajoute `C:\Program Files (x86)\Inno Setup 6` au PATH,
  ou ouvre `installer\instantprint.iss` dans Inno Setup et clique Compile.
- **L'exe se lance mais fenêtre blanche** → WebView2 manquant. Sur Win11 il est
  présent par défaut ; sur Win10 ancien, installe « Microsoft Edge WebView2 Runtime ».
- **Une méthode plante (pymeshlab)** → vérifie que le dossier `dist\InstantPrint\`
  contient bien les `.dll` et `_pymeshlab`. Si non, supprime `build/` et `dist/`
  et relance ; `collect_all("pymeshlab")` dans le spec doit les ramener.
- **Antivirus / SmartScreen** signale l'exe non signé → normal pour un exe non
  signé. Pour le supprimer il faut un certificat de signature de code (payant).

## Icône (optionnel)

Mets un fichier `installer\app.ico` : il sera utilisé automatiquement par
l'exe et l'installeur (le spec et le .iss le détectent).
```
