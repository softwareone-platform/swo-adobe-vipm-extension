# Local Development

This document covers running `swo-adobe-vipm-extension` locally. Docker is the
default execution model. Runtime configuration and environment variables are
documented in [deployment.md](deployment.md); the contribution workflow and
validation commands are in [contributing.md](contributing.md).

## Prerequisites

- Docker and Docker Compose.
- An `.env` file at the repository root, created from `.env.sample`.
- Adobe credentials and authorizations JSON files referenced by
  `EXT_ADOBE_CREDENTIALS_FILE` and `EXT_ADOBE_AUTHORIZATIONS_FILE`. In local runs
  the repository is mounted at `/extension`, so these usually point at files in
  the repository root. See the file formats in [deployment.md](deployment.md).

## Setup and run

```bash
cp .env.sample .env        # then fill in the required values
make build                 # build the images
make run                   # start the service (compose, http://localhost:8080)
```

The Compose service runs `swoext run --no-color` and exposes port `8080`.

## Common commands

| Command | Purpose |
| --- | --- |
| `make build` | Build the Docker images |
| `make run` | Run the service via Docker Compose |
| `make bash` | Open a shell in the container |
| `make shell` | Open a Django shell (`swoext shell`) |
| `make test` | Run the test suite (`args=<filter>` to narrow) |
| `make check` | Run formatting, lint, type, and lock checks |
| `make check-all` | Run checks and tests |
| `make down` | Stop and remove the containers |

For migration commands (`migrate-schema`, `migrate-data`, `migrate-list`, …) see
[migrations.md](migrations.md).

## Configuration

The minimal local configuration covers the Marketplace API, the Adobe
integration (API URLs plus the credential/authorization files), Airtable, and
the webhook secrets. The full variable reference lives in
[deployment.md](deployment.md).
