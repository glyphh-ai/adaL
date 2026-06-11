# Ada — dev workflow
# Run `make` or `make help` to see targets.

.DEFAULT_GOAL := help
PY ?= python3
VENV := .venv
BIN := $(VENV)/bin
PORT ?= 8002

.PHONY: help install dev serve repl test fmt clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Create .venv and editable-install Ada with dev extras
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -U pip
	$(BIN)/pip install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "\n  Done. Add your ANTHROPIC_API_KEY to .env, then: make dev\n"

dev: ## Run the server with hot-reload (reads ./.env)
	$(BIN)/uvicorn ada.server:app --host 0.0.0.0 --port $(PORT) --reload

serve: ## Run the server (no reload), via the ada CLI
	$(BIN)/ada serve -p $(PORT)

repl: ## Admin REPL against the server (auto-starts one if needed)
	$(BIN)/ada

test: ## Run the test suite
	$(BIN)/pytest -q

fmt: ## Format + lint (black, isort, ruff)
	$(BIN)/black . && $(BIN)/isort . && $(BIN)/ruff check --fix .

clean: ## Remove venv and caches
	rm -rf $(VENV) .pytest_cache .ruff_cache **/__pycache__
