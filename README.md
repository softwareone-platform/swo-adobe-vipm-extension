# SoftwareONE Adobe VIP Marketplace Extension

`swo-adobe-vipm-extension` is a SoftwareOne Marketplace extension for Adobe VIP Marketplace.

The repository contains:

- a Django-based extension runtime
- Marketplace order validation and fulfillment flows
- Adobe synchronization and transfer-processing logic
- operational commands for workers and scheduled jobs
- Helm deployment charts for API and worker workloads

## Documentation

Start here:

- [AGENTS.md](AGENTS.md): entry point for AI agents
- [docs/deployment.md](docs/deployment.md): runtime configuration and deployment model
- [docs/contributing.md](docs/contributing.md): repository-specific development workflow
- [docs/testing.md](docs/testing.md): testing strategy and commands
- [docs/migrations.md](docs/migrations.md): migration workflow and migration-specific constraints
- [docs/documentation.md](docs/documentation.md): repository documentation rules

## Quick Start

Prerequisites:

- Docker with the `docker compose` plugin
- `make`

Recommended setup:

```bash
cp .env.sample .env
make build
make test
make run
```

The application runs on `http://localhost:8080`.

See [docs/deployment.md](docs/deployment.md) for runtime parameters and the Docker-based local execution context.

## Repository Layout

- [`adobe_vipm/`](adobe_vipm): extension package and business flows
- [`tests/`](tests): pytest suite
- [`make/`](make): modular make targets
- [`migrations/`](migrations): `mpt-service-cli` migration scripts
- [`helm/swo-extension-adobe/`](helm/swo-extension-adobe): Helm charts for deployment

## Common Commands

```bash
make build
make run
make test
make check
make check-all
make shell
```
