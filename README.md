# MESH//REPAIR 🛠️

Petite app web locale pour rendre un modèle 3D **imprimable**.
Tu déposes ton fichier, tu choisis une méthode de réparation, ça tourne tout seul,
et tu récupères un `.stl` prêt pour le slicer.

Pensé pour les modèles cassés : **assets rippés de jeu**, trous, normales inversées,
géométrie non-manifold, surfaces ouvertes.

![stack](https://img.shields.io/badge/stack-FastAPI%20%2B%20trimesh%20%2B%20pymeshlab-ff5e1a)

---

## 🚀 Lancement

### Windows
Double-clique sur **`run.bat`** (ou en terminal : `run.bat`).

### Linux / macOS
```bash
chmod +x run.sh
./run.sh
```

Puis ouvre **http://127.0.0.1:8000** dans ton navigateur.

> Le script crée un venv, installe les dépendances et démarre le serveur.
> La 1ʳᵉ fois ça prend 1-2 min (téléchargement de pymeshlab notamment).

### Lancement manuel (si tu préfères)
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd backend
python main.py
```

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
mesh-repair/
├── backend/
│   ├── main.py        # API FastAPI (upload / repair / download)
│   └── repair.py      # les 4 méthodes de réparation (testées)
├── frontend/
│   └── index.html     # UI (vanilla, pas de build)
├── requirements.txt
├── run.sh / run.bat
└── README.md
```

Tout tourne en local, aucun fichier n'est envoyé sur internet.
