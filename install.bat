@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "LOG=%~dp0install_log.txt"
echo ==== MiroFish install started ==== > "%LOG%"

echo [1/4] Checking Node.js and Python...
echo [1/4] check tools >> "%LOG%"
node -v >> "%LOG%" 2>&1 || (echo ERROR: Node.js not found & echo NODE_MISSING >> "%LOG%" & pause & exit /b 1)
python --version >> "%LOG%" 2>&1 || (echo ERROR: Python not found & echo PYTHON_MISSING >> "%LOG%" & pause & exit /b 1)

echo [2/4] Checking uv (installing if missing)...
where uv >nul 2>nul
if errorlevel 1 (
    echo installing uv via pip >> "%LOG%"
    python -m pip install uv >> "%LOG%" 2>&1
)
for /f "delims=" %%i in ('python -c "import sysconfig;print(sysconfig.get_path('scripts'))"') do set "PATH=%%i;%PATH%"
uv --version >> "%LOG%" 2>&1 || (echo ERROR: uv install failed & echo UV_FAILED >> "%LOG%" & pause & exit /b 1)

echo [3/4] Installing Node dependencies, this takes several minutes, window may look stuck - it is working...
echo [3/4] npm setup >> "%LOG%"
call npm run setup >> "%LOG%" 2>&1
if errorlevel 1 (echo ERROR in npm setup, see install_log.txt & echo NPM_SETUP_FAILED >> "%LOG%" & pause & exit /b 1)

echo [4/4] Installing Python backend dependencies, also takes several minutes...
echo [4/4] backend setup >> "%LOG%"
call npm run setup:backend >> "%LOG%" 2>&1
if errorlevel 1 (echo ERROR in backend setup, see install_log.txt & echo BACKEND_SETUP_FAILED >> "%LOG%" & pause & exit /b 1)

echo ==== ALL DONE ====
echo INSTALL_SUCCESS >> "%LOG%"
echo You can close this window now.
pause
