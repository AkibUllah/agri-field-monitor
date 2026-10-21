.PHONY: install migrate seed run test lint fmt awd-check schema docker-up docker-down clean

PY ?= .venv/bin/python
PIP ?= .venv/bin/pip

install:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

migrate:
	$(PY) manage.py migrate

seed: migrate
	$(PY) manage.py seed_demo

run:
	$(PY) manage.py runserver 0.0.0.0:8000

awd-check:
	$(PY) manage.py awd_check

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

schema:
	$(PY) scripts/export_schema.py schema.graphql

docker-up:
	docker compose up --build -d
	docker compose exec web python manage.py migrate
	docker compose exec web python manage.py seed_demo

docker-down:
	docker compose down -v

clean:
	rm -rf .pytest_cache .ruff_cache db.sqlite3 media staticfiles
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
