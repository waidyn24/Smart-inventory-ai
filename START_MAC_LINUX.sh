#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v docker >/dev/null 2>&1; then echo 'Install Docker Desktop/Engine first.'; exit 1; fi
if [ ! -f .env ]; then cp .env.example .env; fi
echo 'Starting Smart Inventory AI…'
docker compose up --build -d
printf '\nWeb: http://localhost:3000\nAPI: http://localhost:8000/docs\nLogin: owner@demo.kz / Demo2026!\n'
