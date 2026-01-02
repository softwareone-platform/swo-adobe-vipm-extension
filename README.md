[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension) [![Coverage](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=coverage)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension)

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

# SoftwareONE Adobe VIP Marketplace Extension
Extension integrates Adobe VIP Marketplace Extension with the SoftwareONE Marketplace

## Getting started

### Prerequisites

- Docker and Docker Compose plugin (`docker compose` CLI)
- `make`
- Valid `.env` file
- Adobe credentials and authorizations JSON files in the project root
- [CodeRabbit CLI](https://www.coderabbit.ai/cli) (optional. Used for running review check locally)

### Make targets overview

Common development workflows are wrapped in the `makefile`:

- `make help` – list available commands
- `make bash` – start the app container and open a bash shell
- `make build` – build the application image for development
- `make check` – run code quality checks (ruff, flake8, lockfile check)
- `make check-all` – run checks, formatting, and tests
- `make format` – apply formatting and import fixes
- `make down` – stop and remove containers
- `make review` –  check the code in the cli by running CodeRabbit
- `make run` – run the service
- `make shell` – open a Django shell inside the running app container
- `make test` – run the test suite with pytest

## Running tests

Tests run inside Docker using the dev configuration.

Run the full test suite:

```bash
make test
```

Pass additional arguments to pytest using the `args` variable:

```bash
make test args="-k test_extension -vv"
make test args="tests/flows/test_orders_flow.py"
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

Update `.env` with your values. This file is used by all Docker Compose configurations and the `make run` target.

### 2. Running

Run the service against real Adobe and SoftwareONE Marketplace APIs. It uses `compose.yaml` and reads environment from `.env`.

Ensure:

- `adobe_secrets.json` and `adobe_authorizations.json` contain real credentials.
- `.env` is populated with real endpoints and tokens.

Start the app:

```bash
make run
```

The service will be available at `http://localhost:8080`.

Example `.env` snippet for real services:

```env
EXT_ADOBE_CREDENTIALS_FILE=/extension/adobe_secrets.json
EXT_ADOBE_API_BASE_URL=<adobe-vipm-api>
EXT_ADOBE_AUTH_ENDPOINT_URL=<adobe-vipm-authentication-url>
MPT_PRODUCT_ID=PRD-1111-1111,PRD-2222-2222
EXT_WEBHOOKS_SECRETS={"PRD-1111-1111": "<webhook-secret-for-product>", "PRD-2222-2222": "<webhook-secret-for-product>"}
MPT_PORTAL_BASE_URL=https://portal.s1.show
MPT_API_BASE_URL=https://api.s1.show/public
MPT_API_TOKEN=c0fdafd7-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

`MPT_PRODUCTS_IDS` is a comma-separated list of SWO Marketplace Product identifiers.
For each product ID in the `MPT_PRODUCTS_IDS` list, define the corresponding entry in the `WEBHOOKS_SECRETS` JSON using the product ID as the key.



## Developer utilities

Useful helper targets during development:

```bash
make bash      # open a bash shell in the app container
make check     # run ruff, flake8, and lockfile checks
make check-all # run checks and tests
make format    # auto-format code and imports
make review    # check the code in the cli by running CodeRabbit
make shell     # open a Django shell in the app container
```

## Configuration

The following environment variables are typically set in `.env`. Docker Compose reads them when using the Make targets described above.

### Application

| Environment Variable            | Default                 | Example                                 | Description                                                                               |
|---------------------------------|-------------------------|-----------------------------------------|-------------------------------------------------------------------------------------------|
| `EXT_ADOBE_CREDENTIALS_FILE`    | -                       | /extension/adobe_secrets.json           | Path to Adobe credentials file                                                            |
| `EXT_ADOBE_AUTHORIZATIONS_FILE` | -                       | /extension/adobe_authorizations.json    | Path to Adobe authorizations file                                                         |
| `EXT_ADOBE_API_BASE_URL`        | -                       | `https://partner-example.adobe.io`      | Path to Adobe VIPM API                                                                    |
| `EXT_ADOBE_AUTH_ENDPOINT_URL`   | -                       | `https://auth.partner-example.adobe.io` | Path to Adobe VIPM authentication API                                                     |
| `EXT_AIRTABLE_SKU_MAPPING_BASE` | -                       | appXXXXXXXXXXXXXXXX                     | Airtable base ID for the SKU mapping                                                      |
| `EXT_WEBHOOKS_SECRETS`          | -                       | {"PRD-1111-1111": "123qweasd3432234"}   | Webhook secret of the Draft validation Webhook in SoftwareONE Marketplace for the product |
| `MPT_PRODUCTS_IDS`              | PRD-1111-1111           | PRD-1234-1234,PRD-4321-4321             | Comma-separated list of SoftwareONE Marketplace Product ID                                |
| `MPT_API_BASE_URL`              | `http://localhost:8000` | `https://portal.softwareone.com`        | SoftwareONE Marketplace API URL                                                           |
| `MPT_API_TOKEN`                 | -                       | eyJhbGciOiJSUzI1N...                    | SoftwareONE Marketplace API Token                                                         |
| `MPT_NOTIFY_CATEGORIES`         | -                       | {"ORDERS": "NTC-0000-0006"}             | SoftwareONE Marketplace Notification Categories                                           |

### Azure AppInsights

| Environment Variable                    | Default                            | Example                                                                                                                                                                                               | Description                                                                                                   |
|-----------------------------------------|------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| `OTEL_SERVICE_NAME`                     | -                                  | Swo.Extensions.AdobeVIPM                                                                                                                                                                              | Service name that is visible in the AppInsights logs                                                          |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | -                                  | `InstrumentationKey=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx;IngestionEndpoint=https://westeurope-1.in.applicationinsights.azure.com/;LiveEndpoint=https://westeurope.livediagnostics.monitor.azure.com/` | Azure Application Insights connection string                                                                  |
| `LOGGING_ATTEMPT_GETTER`                | adobe_vipm.utils.get_attempt_count | adobe_vipm.utils.get_attempt_count                                                                                                                                                                    | Path to python function that retrieves order processing attempt to put it into the Azure Application Insights |

### Other

| Environment Variable                   | Default | Example | Description                                                          |
|----------------------------------------|---------|---------|----------------------------------------------------------------------|
| `MPT_ORDERS_API_POLLING_INTERVAL_SECS` | 120     | 60      | Orders polling interval from the Software Marketplace API in seconds |
