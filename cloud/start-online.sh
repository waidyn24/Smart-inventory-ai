#!/bin/sh
set -eu
export DATABASE_URL="${DATABASE_URL:-sqlite:////data/inventory.db}"
export COOKIE_SECURE="${COOKIE_SECURE:-true}"
export ALLOW_DEMO_RESET="${ALLOW_DEMO_RESET:-false}"
if [ -z "${SESSION_SECRET:-}" ]; then
  echo "WARNING: SESSION_SECRET missing. Set a permanent secret in host variables!" >&2
  SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  export SESSION_SECRET
fi
mkdir -p /data
cd /app/backend
alembic upgrade head
python -m app.seed
exec python /app/supervise.py
