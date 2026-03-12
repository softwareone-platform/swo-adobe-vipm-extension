## Add repo-specific targets here. Do not modify the shared *.mk files.

run-local:  ## Run service by using fastapi
	$(DC) up app

run-dev:  ## Run service by using Ziticorn
	$(DC) -f compose.dev.yaml up app
