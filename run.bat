@echo off
cd /d "%~dp0"

if not exist ".venv" (
  echo == Creation de l'environnement virtuel...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo == Installation des dependances...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

echo == Demarrage du serveur sur http://127.0.0.1:8000
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
pause
