DC = docker compose -f compose.yaml
RUN = $(DC) run --rm app
RUN_IT = $(DC) run --rm -it app

bash:  ## Open a bash shell
	$(RUN_IT) bash

build:  ## Build images
	$(DC) build

check:  ## Check code quality with ruff
	$(RUN) bash -c "ruff format --check . && ruff check . && flake8 . && uv lock --check"

check-all:  check test ## Run checks and tests

down:  ## Stop and remove containers
	$(DC) down

format:  ## Format code
	$(RUN) bash -c "ruff check --select I --fix . && ruff format ."

run:  ## Run service
	$(DC) up

shell:  ## Open Django shell
	$(RUN_IT) bash -c "swoext shell"

test:  ## Run test
	$(RUN) pytest $(if $(args),$(args),.)

uv-add: ## Add a production dependency (pkg=<package_name>)
	$(call require,pkg)
	$(RUN) bash -c "uv add $(pkg)"
	$(MAKE) build

uv-add-dev: ## Add a dev dependency (pkg=<package_name>)
	$(call require,pkg)
	$(RUN) bash -c "uv add --dev $(pkg)"
	$(MAKE) build

uv-upgrade: ## Upgrade all packages or a specific package (use pkg="package_name" to target one)
	$(RUN) bash -c "uv lock $(if $(pkg),--upgrade-package $(pkg),--upgrade) && uv sync"
	$(MAKE) build
