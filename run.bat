@echo off
REM ==========================================================================
REM  Lance InstantPrint en mode developpement : la vraie fenetre application
REM  (WebView2), depuis le code source, sans avoir a reconstruire l'exe.
REM  Pour produire l'exe distribuable, utilise build.bat.
REM ==========================================================================
cd /d "%~dp0"

if not exist ".venv" (
  echo == Creation de l'environnement virtuel...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo == Installation des dependances...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

echo == Lancement de l'application InstantPrint...
python desktop.py
