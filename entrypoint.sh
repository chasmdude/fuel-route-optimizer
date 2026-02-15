#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
until python -c "
import os, psycopg
url = os.environ.get('DATABASE_URL', '').replace('postgis://', 'postgresql://')
psycopg.connect(url)
" 2>/dev/null; do
    echo "  PostgreSQL not ready, retrying in 2s..."
    sleep 2
done
echo "PostgreSQL is ready."

echo "Running migrations..."
python manage.py migrate --noinput

echo "Starting application..."
exec "$@"
