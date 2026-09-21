@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create the Python 3.11 .venv first. See README.md.
  exit /b 1
)
if not exist "models\face_landmarker.task" (
  echo Run .venv\Scripts\python.exe tools\download_model.py first.
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" tools\make_icon.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --noconsole --name DeskVeil --icon assets\deskveil.ico --add-data "assets;assets" --add-data "models;models" --collect-data mediapipe --collect-binaries mediapipe --hidden-import backports.tarfile main.py
if errorlevel 1 exit /b 1
echo Built dist\DeskVeil\DeskVeil.exe - distribute the whole DeskVeil folder.
