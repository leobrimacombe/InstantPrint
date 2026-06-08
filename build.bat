@echo off
REM ==========================================================================
REM  Construit l'application Windows complete : .exe puis installeur setup.exe
REM  Usage : double-clic, ou  build.bat  en terminal.
REM ==========================================================================
cd /d "%~dp0"

if not exist ".venv" (
  echo == Creation de l'environnement virtuel...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo == Installation des dependances (runtime + build)...
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
python -m pip install -q -r build-requirements.txt

echo.
echo == [1/2] Empaquetage avec PyInstaller...
pyinstaller mesh-repair.spec --noconfirm
if errorlevel 1 (
  echo !! Echec de PyInstaller.
  pause
  exit /b 1
)
echo    -> dist\MeshRepair\MeshRepair.exe

echo.
echo == [2/2] Construction de l'installeur (Inno Setup)...
where iscc >nul 2>nul
if errorlevel 1 (
  echo !! "iscc" introuvable. Installe Inno Setup 6 puis relance,
  echo    ou ajoute C:\Program Files ^(x86^)\Inno Setup 6 au PATH.
  echo    L'exe est quand meme pret dans dist\MeshRepair\.
  pause
  exit /b 0
)
iscc installer\mesh-repair.iss
if errorlevel 1 (
  echo !! Echec de Inno Setup.
  pause
  exit /b 1
)

echo.
echo == Termine.
echo    Application portable : dist\MeshRepair\MeshRepair.exe
echo    Installeur          : installer\Output\MeshRepair-Setup.exe
pause
