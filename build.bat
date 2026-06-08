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
pyinstaller instantprint.spec --noconfirm
if errorlevel 1 (
  echo !! Echec de PyInstaller.
  pause
  exit /b 1
)
echo    -> dist\InstantPrint\InstantPrint.exe

echo.
echo == [2/2] Construction de l'installeur (Inno Setup)...
REM  Cherche ISCC.exe : d'abord dans le PATH, sinon aux emplacements connus
REM  (installation par-utilisateur via winget, ou Program Files).
set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  echo == Inno Setup absent : tentative d'installation automatique via winget...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo !! winget introuvable. Installe Inno Setup 6 manuellement : https://jrsoftware.org/isdl.php
    echo    L'exe portable reste pret dans dist\InstantPrint\.
    pause
    exit /b 0
  )
  winget install --id JRSoftware.InnoSetup --accept-source-agreements --accept-package-agreements --silent
  if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
  if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
)
if not defined ISCC (
  echo !! Inno Setup toujours introuvable. L'exe portable reste pret dans dist\InstantPrint\.
  pause
  exit /b 0
)
"%ISCC%" installer\instantprint.iss
if errorlevel 1 (
  echo !! Echec de Inno Setup.
  pause
  exit /b 1
)

echo.
echo == Termine.
echo    Application portable : dist\InstantPrint\InstantPrint.exe
echo    Installeur          : installer\Output\InstantPrint-Setup.exe
pause
