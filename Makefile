PY := python3
PIP := $(PY) -m pip
VENVDIR := .venv

.PHONY: help
help:
	@echo "Targets: init, api, worker, docker-up, docker-down, docker-build"

.PHONY: init
init:
	$(PY) -m venv $(VENVDIR)
	. $(VENVDIR)/bin/activate; $(PIP) install --upgrade pip; pip install -r requirements.txt

.PHONY: setup-dev
setup-dev:
	$(PY) -m venv $(VENVDIR)
	. $(VENVDIR)/bin/activate; $(PIP) install --upgrade pip; pip install -r requirements.txt -r requirements-dev.txt

.PHONY: api
api:
	. $(VENVDIR)/bin/activate; uvicorn api.app.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: worker
worker:
	. $(VENVDIR)/bin/activate; python -m worker.collector

.PHONY: docker-up
docker-up:
	docker compose up -d --build

.PHONY: docker-down
docker-down:
	docker compose down

.PHONY: docker-build
docker-build:
	docker compose build

.PHONY: compose-up
compose-up:
	docker compose up -d db api worker

.PHONY: compose-down
compose-down:
	docker compose down -v

.PHONY: api-logs
api-logs:
	docker compose logs -f api

.PHONY: worker-logs
worker-logs:
	docker compose logs -f worker

.PHONY: test
test:
	./.venv/bin/ruff check . && PYTHONPATH=. ./.venv/bin/pytest -q -m "not integration"

.PHONY: itest
itest:
	TEST_ALLOW_NETWORK=1 PYTHONPATH=. ./.venv/bin/pytest -q -m integration

.PHONY: itest-host
itest-host:
	DB_URL=postgresql://postgres:postgres@localhost:5432/mta TEST_ALLOW_NETWORK=1 PYTHONPATH=. ./.venv/bin/pytest -q -m integration
