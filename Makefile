.PHONY: build up down restart logs test migrate shell import-data lint clean

# ---------------------------------------------------------------------------
# Docker Compose
# ---------------------------------------------------------------------------
build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart django

logs:
	docker compose logs -f

# ---------------------------------------------------------------------------
# Django management (runs inside container)
# ---------------------------------------------------------------------------
migrate:
	docker compose exec django python manage.py migrate

shell:
	docker compose exec django python manage.py shell

import-data:
	docker compose exec django python manage.py import_fuel_data

createsuperuser:
	docker compose exec django python manage.py createsuperuser

collectstatic:
	docker compose exec django python manage.py collectstatic --noinput

# ---------------------------------------------------------------------------
# Testing (installs dev dependencies, then runs pytest inside container)
# ---------------------------------------------------------------------------
test:
	docker compose exec django sh -c "pip install --quiet pytest pytest-django factory-boy responses 2>/dev/null && python -m pytest -v"

# ---------------------------------------------------------------------------
# Local development (outside Docker, using .venv)
# ---------------------------------------------------------------------------
local-install:
	pip install -r requirements/dev.txt

local-run:
	python manage.py runserver

local-test:
	pytest -v

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
clean:
	docker compose down -v --remove-orphans
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
