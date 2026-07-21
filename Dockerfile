# syntax=docker/dockerfile:1.7

FROM node:22.17.0-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


FROM python:3.12.11-slim-bookworm AS python-dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN python -m venv "$VIRTUAL_ENV"
COPY backend/requirements.runtime.lock /tmp/requirements.runtime.lock
RUN python -m pip install --requirement /tmp/requirements.runtime.lock \
    && python -m pip check


FROM python:3.12.11-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Junto"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PORT=8000

RUN groupadd --gid 10001 junto \
    && useradd --uid 10001 --gid junto --home-dir /nonexistent --shell /usr/sbin/nologin junto

WORKDIR /app
COPY --from=python-dependencies /opt/venv /opt/venv
COPY --chown=10001:10001 backend/junto/ /app/backend/junto/
COPY --chown=10001:10001 backend/scripts/start.py backend/scripts/release.py /app/backend/scripts/
COPY --chown=10001:10001 backend/alembic/ /app/backend/alembic/
COPY --chown=10001:10001 backend/alembic.ini /app/backend/alembic.ini
COPY --from=frontend-build --chown=10001:10001 /build/frontend/dist/ /app/frontend/dist/

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=4 \
  CMD ["python", "-c", \
       "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=2).read()"]

CMD ["python", "/app/backend/scripts/start.py"]
