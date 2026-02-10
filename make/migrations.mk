RUN_MIGRATE = $(RUN) mpt-service-cli migrate

migrate-check: ## Check migration status
	$(RUN_MIGRATE) --check

migrate-data: ## Run data migrations
	$(RUN_MIGRATE) --data

migrate-schema: ## Run schema migrations
	$(RUN_MIGRATE) --schema

migrate-list: ## List migrations with the status
	$(RUN_MIGRATE) --list

migrate-new-data: ## Create new data migration (name=<migration_id>)
	$(call require,name)
	$(RUN_MIGRATE) --new-data $(name)

migrate-new-schema: ## Create new schema migration (name=<migration_id>)
	$(call require,name)
	$(RUN_MIGRATE) --new-schema $(name)
