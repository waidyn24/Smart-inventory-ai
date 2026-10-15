@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0FIX_TYPES_WINDOWS.ps1"
if errorlevel 1 (
  echo Patch failed.
  pause
  exit /b 1
)
echo.
echo Rebuilding Docker services...
docker compose up --build -d
if errorlevel 1 (
  echo Build still failed. Send screenshot of earliest TypeScript error.
  pause
  exit /b 1
)
docker compose ps
echo.
echo Open http://localhost:3000
pause
