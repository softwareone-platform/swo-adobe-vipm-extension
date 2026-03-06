# MROK Runtime (FastAPI + OpenZiti)

This module runs the extension with the new event runtime using FastAPI.

## Prerequisites

- Docker + Docker Compose (`docker compose`)
- A valid `.env` file in repository root
- `MPT_API_BASE_URL`, `MPT_API_TOKEN`, and `MPT_EXTENSION_ID` configured

Optional but recommended for bootstrap + OpenZiti identity:

- `MPT_EXTENSION_IDENTITY_FILE` (default: `./identity.json`)

## Run with Docker Compose (Uvicorn)

This runs the FastAPI app directly (no ziticorn):

```bash
docker compose -f compose.yaml -f compose.fastapi.yaml up app
```

Service URL:

- `http://localhost:8081`


## Run with `mextmock.main` style (`ziticorn`)

The runner is implemented in:

- `adobe_vipm/main.py`

It does:

1. load runtime settings
2. bootstrap the extension instance
3. run the app using `ziticorn`

Run:

```bash
docker compose run --rm app uv run python -m adobe_vipm.main
```

Expected behavior:

- `OK` if order is a supported new purchase and processing succeeds
- `Cancel` if order is not a supported purchase event
- `Defer` on third party errors

## cURL examples

### 1) Missing task header (returns `Cancel`)

```bash
curl -s -X POST http://localhost:8081/public/v2/orders \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "EVT-0001",
    "object": {
      "id": "ORD-0001",
      "name": "Order 1",
      "objectType": "orders"
    },
    "details": {
      "eventType": "platform.commerce.order",
      "enqueueTime": "2026-03-06T12:00:00Z",
      "deliveryTime": "2026-03-06T12:01:00Z"
    },
    "task": {
      "id": "TSK-0001"
    }
  }'
```

### 2) Valid event, cancel response unsupported order type

```bash
curl -s -X POST http://localhost:8081/public/v2/orders \
  -H 'Content-Type: application/json' \
  -H 'MPT-Task-Id: TSK-0001' \
  -d '{
    "id": "EVT-0001",
    "object": {
      "id": "ORD-3834-9388-3444",
      "name": "Change order",
      "objectType": "orders"
    },
    "details": {
      "eventType": "platform.commerce.order",
      "enqueueTime": "2026-03-06T12:00:00Z",
      "deliveryTime": "2026-03-06T12:01:00Z"
    },
    "task": {
      "id": "TSK-0001"
    }
  }'
```

### 3) Valid event, OK response
```bash
curl -s -X POST http://localhost:8081/public/v2/orders \
  -H 'Content-Type: application/json' \
  -H 'MPT-Task-Id: TSK-0002' \
  -d '{
    "id": "EVT-0002",
    "object": {
      "id": "ORD-3881-0750-6275",
      "name": "Purchase order",
      "objectType": "orders"
    },
    "details": {
      "eventType": "platform.commerce.order",
      "enqueueTime": "2026-03-06T12:00:00Z",
      "deliveryTime": "2026-03-06T12:01:00Z"
    },
    "task": {
      "id": "TSK-0002"
    }
  }'
```

## OpenAPI docs

- Swagger UI: `http://localhost:8081/public/v2/docs`
- OpenAPI JSON: `http://localhost:8081/public/v2/openapi.json`
