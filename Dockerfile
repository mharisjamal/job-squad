# JobSquad: one image serving the API and the built SPA on $PORT.

# Stage 1: build the React app.
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime (no node, no dev dependencies).
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app/backend

# Dependencies first so code edits do not invalidate the install layer.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
RUN uv sync --frozen --no-dev

# The app resolves the SPA at <repo root>/frontend/dist, so keep that layout.
COPY --from=frontend /build/dist /app/frontend/dist

# Runtime data (the SQLite fallback and the generated secret) live here.
RUN mkdir -p /app/data

EXPOSE 8100
# Render injects PORT; JOBSQUAD_PORT then 8100 are the fallbacks.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-${JOBSQUAD_PORT:-8100}}"]
