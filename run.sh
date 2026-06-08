#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo ">> Création de l'environnement virtuel..."
  python3 -m venv .venv
fi
source .venv/bin/activate

echo ">> Installation des dépendances..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo ">> Démarrage du serveur sur http://127.0.0.1:8000"
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
