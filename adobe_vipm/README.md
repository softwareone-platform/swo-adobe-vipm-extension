# MROK Runtime (FastAPI + OpenZiti)

This module runs the extension with the MROK event runtime using FastAPI.

All commands in this document must be run from the repository root.

## Prerequisites

- Docker and Docker Compose (`docker compose`)
- A valid `.env` file in the repository root

Minimum required environment variables:

```dotenv
SDK_EXTENSION_API_URL=https://api.example.com
SDK_EXTENSIOM_API_KEY=<platform-api-token>
```

Optional for Ziticorn:

```dotenv
SDK_IDENTITY_FILE_PATH=./
```

## Runtime options

### Uvicorn (local)

Runs the FastAPI app directly without Ziticorn.

```bash
make run-local
```

Base URL:

- `http://localhost:8080`


### Ziticorn (OpenZiti)

Runs the Extension via `ziticorn`.

```bash
make run-dev
```

Service URL format:

- `https://<ext_id>.ext.<env>`

Example:

- `https://ext-7847-1229.ext.s1.show`


## Bypass route

`/bypass/*` endpoints do not require authorization.

Use this route only for local validation and controlled test environments. Do not expose it publicly without network restrictions.

Health/docs check:

- `https://<ext_id>.ext.<env>/bypass/docs`
- Example: `https://ext-7847-1229.ext.s1.show/bypass/docs`

## Event outcome behavior

Expected processing outcomes:

- `OK`: supported purchase order processed successfully
- `Cancel`: unsupported order type or invalid event preconditions
- `Defer`: third-party/transient failure; retry is expected

## Request examples

Order event requests for local Uvicorn testing are in:

- `adobe_vipm/mrok/example.http`

## OpenAPI docs

- Swagger UI: `http://localhost:8080/api/v2/bypass/docs`
- OpenAPI JSON: `http://localhost:8080/api/v2/bypass/openapi.json`
