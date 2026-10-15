@echo off
chcp 65001 >nul
cd /d "%~dp0"
where docker >nul 2>nul
if errorlevel 1 (
 echo Docker is not installed. Install Docker Desktop first.
 pause
 exit /b 1
)
if not exist .env copy .env.example .env >nul
echo Building Smart Inventory AI and starting services...
docker compose up --build -d
if errorlevel 1 (
 echo Startup failed. Check: docker compose logs
 pause
 exit /b 1
)
echo.
echo Web app: http://localhost:3000
echo API docs: http://localhost:8000/docs
echo Demo login: owner@demo.kz / Demo2026!
echo.
start "" "http://localhost:3000"
pause
