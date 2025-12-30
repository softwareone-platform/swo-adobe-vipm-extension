.PHONY: bash build check check-all down format run run-prod shell tests help

DC = docker compose -f compose.yaml
DC_DEV = $(DC) -f compose.dev.yaml
DC_TEST = $(DC) -f compose.test.yaml

help:
	@echo "Available commands:"
	@echo "  make bash             - Run service opening the terminal."
	@echo "  make build            - Build images"
	@echo "  make check            - Check code quality with ruff."
	@echo "  make check-all        - Run check, format and tests."
	@echo "  make down             - Stop and remove containers."
	@echo "  make format           - Format code."
	@echo "  make run              - Run service mocking third parties"
	@echo "  make run-prod         - Run service using env variables"
	@echo "  make shell            - Open shell"
	@echo "  make tests            - Run tests."
	@echo "  make help             - Display this help message."

bash:
	  $(DC_DEV) run --rm -it app bash

build:
	  $(DC_DEV) build app

check:
	  $(DC_TEST) run --rm app bash -c "ruff format --check . && ruff check --fix . && flake8 . && uv lock --check"

check-all:
	  make format
	  make check
	  make tests

down:
	  $(DC_DEV) down

format:
	  $(DC_TEST) run --rm app bash -c "ruff check --select I --fix . && ruff format ."

run:
	  $(DC_DEV) up

run-prod:
	  $(DC) up app

shell:
	  $(DC_DEV) run --rm -it app bash django-shell

tests:
	  $(DC_TEST) run --rm app pytest $(args) .
