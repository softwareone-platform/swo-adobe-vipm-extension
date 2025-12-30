[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension) [![Coverage](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=coverage)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension)

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

# SoftwareONE Adobe VIP Marketplace Extension
Extension integrates Adobe VIP Marketplace Extension with the SoftwareONE Marketplace

## Getting started

### Prerequisites

- Docker and Docker Compose plugin (`docker compose` CLI)
- `make`
- Valid `.env` file (and optional `.env.dev` for local development)
- Adobe credentials and authorizations JSON files in the project root

### Make targets overview

Common development workflows are wrapped in the `makefile`:

- `make help` – list available commands
- `make build` – build the application image for development
- `make run` – run the service with mocked third‑party integrations (Wiremock)
- `make run-prod` – run the service using real environment variables
- `make tests` – run the test suite with pytest
- `make bash` – start the app container and open a bash shell
- `make shell` – open a Django shell inside the running app container
- `make down` – stop and remove containers (dev stack)
- `make check` – run code quality checks (ruff, flake8, lockfile check)
- `make format` – apply formatting and import fixes
- `make check-all` – run checks, formatting, and tests

## Running tests

Tests run inside Docker using the dev configuration.

Run the full test suite:

```bash
make tests
```

Pass additional arguments to pytest using the `args` variable:

```bash
make tests args="-k test_extension -vv"
make tests args="tests/flows/test_orders_flow.py"
```

## Running the service

### 1. Configuration files

In the project root, create and configure the following files.

#### Adobe secrets file

Create `adobe_secrets.json`:

```bash
touch adobe_secrets.json
```

Fill it with your Adobe credentials:

```json
[
    {
        "authorization_uk": "<authorization-uk>",
        "authorization_id": "<authorization-id>",
        "name": "<name>",
        "client_id": "<client-id>",
        "client_secret": "<client-secret>"
    },
    {"...": "..."}
]
```

Example:

```json
[
    {
        "authorization_uk": "auth-adobe-us-01",
        "authorization_id": "AUT-1111-1111",
        "name": "Credentials for US",
        "client_id": "cc7fce0d-f2e8-45c2-a61e-452b31d096c7",
        "client_secret": "cltn3c1eo0001m5pxkdcmd8cl"
    }
]
```

#### Adobe authorizations file

Create `adobe_authorizations.json`:

```bash
touch adobe_authorizations.json
```

Fill it with your Adobe authorizations:

```json
{
    "authorizations": [
        {
            "authorization_uk": "<authorization-uk>",
            "authorization_id": "<authorization-id>",
            "distributor_id": "<distributor-id>",
            "currency": "USD",
            "resellers": [
                {
                    "id": "<adobe-reseller-id>",
                    "seller_id": "<seller-id>",
                    "seller_uk": "<seller-uk>"
                }
            ]
        }
    ]
}
```

Example:

```json
{
    "authorizations": [
        {
            "authorization_uk": "auth-adobe-us-01",
            "authorization_id": "AUT-1111-1111",
            "distributor_id": "db5a6d9c-9eb5-492e-a000-ab4b8c29fc63",
            "currency": "USD",
            "resellers": [
                {
                    "id": "P1000041107",
                    "seller_id": "SEL-1111-1111",
                    "seller_uk": "SWO_US"
                }
            ]
        }
    ]
}
```

#### Environment files

Start from the sample file:

```bash
cp .env.sample .env
```

Update `.env` with your values. This file is used by all Docker Compose configurations and the `make run-prod` target.

You can optionally create `.env.dev` for local overrides used only in development targets (`make run`, `make tests`, `make bash`, `make shell`, `make check`, `make format`, `make check-all`). For example, you can point Adobe and MPT APIs to Wiremock in `.env.dev`.

### 2. Running with mocks (development)

Use this mode when developing locally with mocked third‑party services. It uses `compose.yaml` and `compose.dev.yaml` and starts both the app and Wiremock.

Build the image (optional, `make run` will build when needed):

```bash
make build
```

Start the dev stack (app + Wiremock):

```bash
make run
```

Stop and remove containers:

```bash
make down
```

In this mode:

- The app runs on `http://localhost:8080`.
- Wiremock is available on `http://localhost:8081`.
- Wiremock uses mappings and stubs from `peripherals/wiremock`.
- Environment is loaded from `.env` and `.env.dev`.

Typical `.env.dev` overrides for mocks:

```env
EXT_ADOBE_API_BASE_URL=http://wiremock:8080
EXT_ADOBE_AUTH_ENDPOINT_URL=http://wiremock:8080
MPT_API_BASE_URL=http://wiremock:8080
```

### 3. Running against real services (production‑like)

Use this mode to run the service against real Adobe and SoftwareONE Marketplace APIs. It uses only `compose.yaml` and reads environment from `.env`.

Ensure:

- `adobe_secrets.json` and `adobe_authorizations.json` contain real credentials.
- `.env` is populated with real endpoints and tokens.

Start the app:

```bash
make run-prod
```

The service will be available at `http://localhost:8080`.

Example `.env` snippet for real services:

```env
EXT_ADOBE_CREDENTIALS_FILE=/extension/adobe_secrets.json
EXT_ADOBE_API_BASE_URL=<adobe-vipm-api>
EXT_ADOBE_AUTH_ENDPOINT_URL=<adobe-vipm-authentication-url>
MPT_PRODUCT_ID=PRD-1111-1111,PRD-2222-2222
MPT_API_TOKEN=c0fdafd7-6d5a-4fa4-9839-4c2c163794ff
EXT_WEBHOOKS_SECRETS={"PRD-1111-1111": "<webhook-secret-for-product>", "PRD-2222-2222": "<webhook-secret-for-product>"}
MPT_API_BASE_URL=http://devmock:8000
MPT_API_TOKEN=<mpt-api-token>
```

`MPT_PRODUCTS_IDS` should be a comma-separated list of the SWO Marketplace Product identifiers
For each of the defined product id in the `MPT_PRODUCTS_IDS` list define `WEBHOOKS_SECRETS` json variables using product ID as key.



## Developer utilities

Useful helper targets during development:

```bash
make bash      # open a bash shell in the dev app container
make shell     # open a Django shell in the dev app container
make check     # run ruff, flake8, and lockfile checks
make format    # auto-format code and imports
make check-all # run checks, format, and tests
```

## Configuration

The following environment variables are typically set in `.env` (and `.env.dev` for development). Docker Compose reads them when using the Make targets described above.

### Application
| Environment Variable            | Default               | Example                               | Description                                                                               |
|---------------------------------|-----------------------|---------------------------------------|-------------------------------------------------------------------------------------------|
| `EXT_ADOBE_CREDENTIALS_FILE`    | -                     | /extension/adobe_secrets.json         | Path to Adobe credentials file                                                            |
| `EXT_ADOBE_AUTHORIZATIONS_FILE` | -                     | /extension/adobe_authorizations.json  | Path to Adobe authorizations file                                                         |
| `EXT_ADOBE_API_BASE_URL`        | -                     | https://partner-example.adobe.io      | Path to Adobe VIPM API                                                                    |
| `EXT_ADOBE_AUTH_ENDPOINT_URL`   | -                     | https://auth.partner-example.adobe.io | Path to Adobe VIPM authentication API                                                     |
| `EXT_AIRTABLE_SKU_MAPPING_BASE` | -                     | appXXXXXXXXXXXXXXXX                   | Airtable base ID for the SKU mapping                                                      |
| `EXT_WEBHOOKS_SECRETS`          | -                     | {"PRD-1111-1111": "123qweasd3432234"} | Webhook secret of the Draft validation Webhook in SoftwareONE Marketplace for the product |
| `MPT_PRODUCTS_IDS`              | PRD-1111-1111         | PRD-1234-1234,PRD-4321-4321           | Comma-separated list of SoftwareONE Marketplace Product ID                                |
| `MPT_API_BASE_URL`              | http://localhost:8000 | https://portal.softwareone.com        | SoftwareONE Marketplace API URL                                                           |
| `MPT_API_TOKEN`                 | -                     | eyJhbGciOiJSUzI1N...                  | SoftwareONE Marketplace API Token                                                         |
| `MPT_NOTIFY_CATEGORIES`         | -                     | {"ORDERS": "NTC-0000-0006"}           | SoftwareONE Marketplace Notification Categories                                           |

### Azure AppInsights
| Environment Variable                    | Default                            | Example                                                                                                                                                                                             | Description                                                                                                   |
|-----------------------------------------|------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| `OTEL_SERVICE_NAME`                     | -                                  | Swo.Extensions.AdobeVIPM                                                                                                                                                                            | Service name that is visible in the AppInsights logs                                                          |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | -                                  | InstrumentationKey=cf280af3-b686-40fd-8183-ec87468c12ba;IngestionEndpoint=https://westeurope-1.in.applicationinsights.azure.com/;LiveEndpoint=https://westeurope.livediagnostics.monitor.azure.com/ | Azure Application Insights connection string                                                                  |
| `LOGGING_ATTEMPT_GETTER`                | adobe_vipm.utils.get_attempt_count | adobe_vipm.utils.get_attempt_count                                                                                                                                                                  | Path to python function that retrieves order processing attempt to put it into the Azure Application Insights |

### Other
| Environment Variable                   | Default | Example | Description                                                          |
|----------------------------------------|---------|---------|----------------------------------------------------------------------|
| `MPT_ORDERS_API_POLLING_INTERVAL_SECS` | 120     | 60      | Orders polling interval from the Software Marketplace API in seconds |
