# EventMind v2 — задачи разработки. Бэкенд на uv, dev-стек на docker compose.
COMPOSE := docker compose -f deploy/docker-compose.yml
BACKEND := backend

.DEFAULT_GOAL := help

.PHONY: help up down logs build test test-unit test-integration lint typecheck \
        imports migrate revision seed eval load-test web-dev fmt

help: ## Показать доступные команды
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up: ## Поднять dev-стек (pg+redis+api+web+prometheus+grafana+mailhog)
	$(COMPOSE) up --build -d
	@echo "api:        http://localhost:8000/health"
	@echo "web:        http://localhost:3000"
	@echo "grafana:    http://localhost:3001  (admin/admin)"
	@echo "prometheus: http://localhost:9090"
	@echo "mailhog:    http://localhost:8025"

down: ## Остановить dev-стек (данные сохраняются в volume'ах)
	$(COMPOSE) down

logs: ## Хвост логов всех сервисов
	$(COMPOSE) logs -f --tail=100

build: ## Пересобрать образы
	$(COMPOSE) build

test: test-unit ## Псевдоним для test-unit (integration требует Docker)

test-unit: ## Unit-тесты (без внешних сервисов)
	cd $(BACKEND) && uv run pytest tests/unit

test-integration: ## Integration-тесты (testcontainers: pg+redis, нужен Docker)
	cd $(BACKEND) && uv run pytest tests/integration -m integration

lint: ## ruff
	cd $(BACKEND) && uv run ruff check .

fmt: ## ruff --fix (автоформат/автофикс)
	cd $(BACKEND) && uv run ruff check --fix .

typecheck: ## mypy (strict)
	cd $(BACKEND) && uv run mypy src

imports: ## import-linter — границы гексагональных слоёв
	cd $(BACKEND) && uv run lint-imports

migrate: ## Применить миграции к БД (alembic upgrade head)
	cd $(BACKEND) && uv run alembic upgrade head

revision: ## Создать миграцию: make revision m="описание"
	cd $(BACKEND) && uv run alembic revision -m "$(m)"

seed: ## Наполнить БД демо-данными (появится в M1)
	@echo "seed: будет реализован в M1"

eval: ## Offline-eval рекомендера (появится в M8)
	@echo "eval: будет реализован в M8"

load-test: ## Нагрузочный смоук (появится в M8)
	@echo "load-test: будет реализован в M8"

web-dev: ## Next.js dev-сервер (локально, без Docker)
	cd web && npm run dev
