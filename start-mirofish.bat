@echo off
set "DESKTOP_APP=%~dp0dist-installers\panel\win-unpacked\MiroFish Studio.exe"
if exist "%DESKTOP_APP%" (
  start "" "%DESKTOP_APP%" --mirofish-root="%~dp0"
) else (
  start "" "%~dp0backend\.venv\Scripts\pythonw.exe" "%~dp0studio_launcher.pyw"
)
