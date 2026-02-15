# ---------------------------------------------------------------------------
# Multi-stage Dockerfile for Fuel Route Optimizer
# ---------------------------------------------------------------------------

# Stage 1: Builder -- install Python dependencies
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements/prod.txt requirements/prod.txt
COPY requirements/base.txt requirements/base.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements/prod.txt

# Stage 2: Production -- lean runtime image
FROM python:3.12-slim

# Runtime dependencies for PostGIS/GDAL + SSL certs for outbound HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    gdal-bin \
    libgdal36 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --create-home appuser

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application code
COPY . .

# Collect static files
RUN DJANGO_SETTINGS_MODULE=config.settings.production \
    SECRET_KEY=build-placeholder \
    DATABASE_URL=postgis://placeholder:placeholder@placeholder/placeholder \
    python manage.py collectstatic --noinput 2>/dev/null || true

# Own the app directory
RUN chown -R appuser:appuser /app

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
