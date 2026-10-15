# Single internet-facing service: Next.js 15 + FastAPI + SQLite or managed PostgreSQL.
# The public application runs on $PORT; FastAPI listens only on loopback (8000).
FROM node:22-bookworm-slim AS web-builder
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN mkdir -p public
ARG NEXT_PUBLIC_API_URL=/api
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

FROM python:3.12-slim-bookworm
# Copy the node runtime into the Python image to run Next.js & FastAPI together.
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libstdc++6 libgcc-s1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/ /app/backend/
COPY --from=web-builder /build/frontend/.next/standalone /app/web/
COPY --from=web-builder /build/frontend/.next/static /app/web/.next/static
COPY --from=web-builder /build/frontend/public /app/web/public
COPY cloud/start-online.sh /app/start-online.sh
COPY cloud/supervise.py /app/supervise.py
RUN chmod 755 /app/start-online.sh && mkdir -p /data
ENV NODE_ENV=production \
    HOSTNAME=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/inventory.db \
    COOKIE_SECURE=true \
    ALLOW_DEMO_RESET=false
EXPOSE 3000
CMD ["/app/start-online.sh"]
