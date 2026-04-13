# AGENTS.md

Read this repository in the following order:

1. [README.md](README.md) for the repository purpose, quick start, and documentation map.
2. [docs/deployment.md](docs/deployment.md) for runtime configuration and deployment-facing settings.
3. [docs/contributing.md](docs/contributing.md) for repository-specific workflow expectations.
4. [docs/testing.md](docs/testing.md) before changing code or tests.
5. [docs/migrations.md](docs/migrations.md) when a task mentions schema, data migrations, or transfer-processing migration logic.
6. [docs/documentation.md](docs/documentation.md) when changing repository documentation.

Then inspect the code paths relevant to the task:

- [`adobe_vipm/extension.py`](adobe_vipm/extension.py): extension hooks, API entry point, and event listener registration
- [`adobe_vipm/apps.py`](adobe_vipm/apps.py): Django app setup and startup-time configuration validation
- [`adobe_vipm/flows/fulfillment/`](adobe_vipm/flows/fulfillment): fulfillment workflows by order action
- [`adobe_vipm/flows/validation/`](adobe_vipm/flows/validation): validation workflows by order action
- [`adobe_vipm/flows/sync/`](adobe_vipm/flows/sync): agreement, asset, subscription, and pricing synchronization flows
- [`adobe_vipm/management/commands/`](adobe_vipm/management/commands): operational and scheduled commands
- [`adobe_vipm/adobe/`](adobe_vipm/adobe) and [`adobe_vipm/airtable/`](adobe_vipm/airtable): integration-specific clients and models
- [`tests/`](tests/): pytest coverage by domain area
- [`make/`](make/): canonical local commands
- [`helm/swo-extension-adobe/`](helm/swo-extension-adobe): deployment manifests for API and worker workloads

Operational guidance:

- Prefer documented `make` targets over ad hoc Docker commands.
- Treat Docker Compose as the default local execution model.
- Keep repository policy in `docs/` and keep `.github/copilot-instructions.md` thin.
- Do not expand `README.md` into a full manual. Update the topic-specific file under `docs/`.
- Do not infer undocumented deployment or migration behavior. If the code does not make it explicit, document the current constraint instead of inventing rules.
