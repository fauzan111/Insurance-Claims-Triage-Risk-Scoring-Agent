.PHONY: install test lint run up down demo

install:
	pip install -r requirements-dev.txt

lint:
	ruff check app workers tests scripts

test:
	pytest tests/unit -q

# Run offline: SQLite, trained fraud model, template reasoning (no LLM key).
run:
	DATABASE_URL=sqlite+pysqlite:///./dev.sqlite \
	uvicorn app.main:app --reload

up:
	docker compose up --build

down:
	docker compose down -v

# Seed a policy + low/high-risk claims, approve one, print the audit trail.
demo:
	python scripts/seed_demo.py --base-url http://localhost:8000
