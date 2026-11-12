.DEFAULT_GOAL := help
PY ?= python

help: ## Lista los comandos disponibles
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Instala el paquete en modo editable con dependencias de desarrollo
	$(PY) -m pip install -e ".[dev]"
	$(PY) -m playwright install chromium
	pre-commit install || true

lint: ## Ruff (lint + formato) y mypy
	ruff check .
	ruff format --check .
	mypy src

format: ## Formatea el código
	ruff check --fix .
	ruff format .

test: ## Pruebas unitarias y de API con cobertura
	pytest --cov

e2e: ## Bot real (Playwright) contra el portal demo
	pytest -m e2e

integration: ## Requiere `make infra`
	pytest -m integration

infra: ## Levanta solo PostgreSQL y RabbitMQ
	docker compose up -d postgres rabbitmq

up: ## Plataforma completa con Docker
	docker compose up --build -d

down: ## Detiene la plataforma
	docker compose down

encolar: ## Encola el lote de ejemplo (fechas relativas a hoy)
	docker compose run --rm carga colmena-carga encolar --archivo data/sample_tasks.csv

migrate: ## Aplica migraciones
	alembic upgrade head

.PHONY: help install lint format test e2e integration infra up down encolar migrate
