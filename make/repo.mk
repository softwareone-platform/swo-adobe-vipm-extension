## Add repo-specific targets here. Do not modify the shared *.mk files.

run-local:  ## Run service by using fastapi
	$(DC) -f compose.local.yaml up
