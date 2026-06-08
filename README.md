# InstantPrint 🛠️

Application de bureau (Windows) pour rendre un modèle 3D **imprimable**.
Tu déposes ton fichier, tu choisis une méthode de réparation, ça tourne tout seul,
et tu récupères un `.stl` prêt pour le slicer.

Pensé pour les modèles cassés : **assets rippés de jeu**, trous, normales inversées,
géométrie non-manifold, surfaces ouvertes.

![stack](https://img.shields.io/badge/stack-FastAPI%20%2B%20trimesh%20%2B%20pymeshlab-ff5e1a)

---

## 🚀 Lancement

InstantPrint est une **application de bureau** : une fenêtre native, pas un site.

### Utilisateur final
Installe via **`InstantPrint-Setup.exe`** (voir [PACKAGING.md](PACKAGING.md)), puis
lance InstantPrint depuis le menu Démarrer.

### Développement (lancer depuis le code source)
Double-clique sur **`run.bat`** (ou en terminal : `run.bat`).
Ça crée le venv, installe les dépendances et ouvre directement la fenêtre de l'app.

> La 1ʳᵉ fois ça prend 1-2 min (téléchargement de pymeshlab notamment).

Pour construire l'exe distribuable, voir **`build.bat`** et [PACKAGING.md](PACKAGING.md).

---

## 🧪 Les 4 méthodes

| Méthode | Garde les détails ? | Étanche garanti ? | Quand l'utiliser |
|---|---|---|---|
| **Trimesh — touche légère** | ✅ tout | ❌ | Petits trous, normales inversées. Modèle presque bon. |
| **PyMeshLab — nettoyage poussé** | ✅ | ❌ (trous bien définis) | Non-manifold, trous plus grands mais propres. |
| **Voxel Remesh** ⭐ | ⚠️ selon résolution | ✅ **toujours** | Asset complètement cassé. La méthode qui marche quand rien d'autre ne marche. |
| **Convex Hull** | ❌ | ✅ | Dernier recours / socle / test. |

**Conseil** : commence par *Trimesh light* (préserve tout). Si le résultat n'est
pas étanche, passe à *PyMeshLab*, puis en dernier à *Voxel Remesh* (baisse la
résolution = plus de détails mais plus de faces).

---

## 🩺 Dépannage

- **`libGL.so.1` introuvable (Linux)** : `sudo apt install libgl1 libopengl0`
- **pymeshlab refuse de s'installer** : il faut Python 3.9–3.12 (pas 3.13 pour l'instant).
- **Le modèle ne se charge pas** : vérifie le format (STL/OBJ/PLY/GLB/GLTF/OFF/3MF).

---

## 🗂️ Structure

```
instantprint/
├── desktop.py         # lanceur de l'app : fenêtre native + serveur interne
├── backend/
│   ├── main.py        # API interne (upload / repair / download / update)
│   ├── repair.py      # les 4 méthodes de réparation (testées)
│   ├── updater.py     # mises à jour auto via GitHub Releases
│   └── version.py     # numéro de version (source unique)
├── frontend/
│   └── index.html     # interface (HTML/CSS/JS, pas de build)
├── instantprint.spec  # recette PyInstaller (.exe)
├── installer/         # recette Inno Setup (setup.exe) + icône
├── requirements.txt
├── run.bat            # lancer l'app en dev
└── build.bat          # construire l'exe + l'installeur
```

L'interface est du HTML servi **en local** par un serveur interne à l'app —
l'utilisateur ne voit qu'une fenêtre. Aucune donnée n'est envoyée sur internet
(seule la vérification de mise à jour interroge GitHub).
