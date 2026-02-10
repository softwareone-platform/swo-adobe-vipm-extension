[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension) [![Coverage](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=coverage)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension)

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

# SoftwareONE Adobe VIP Marketplace Extension
Extension integrates Adobe VIP Marketplace Extension with the SoftwareONE Marketplace

## Getting started

### Prerequisites

- Docker and Docker Compose plugin (`docker compose` CLI)
- `make`
- [CodeRabbit CLI](https://www.coderabbit.ai/cli) (optional. Used for running review check locally)


### Make targets overview

Common development workflows are wrapped in the `Makefile`. Run `make help` to see the list of available commands.

### How the Makefile works

The project uses a modular Makefile structure that organizes commands into logical groups:

- **Main Makefile** (`Makefile`): Entry point that automatically includes all `.mk` files from the `make/` directory
- **Modular includes** (`make/*.mk`): Commands are organized by category:
  - `common.mk` - Core development commands (build, test, format, etc.)
  - `repo.mk` - Repository management and dependency commands
  - `migrations.mk` - Database migration commands (Only available in extension repositories)
  - `external_tools.mk` - Integration with external tools


You can extend the Makefile with your own custom commands creating a `local.mk` file inside make folder. This file is
automatically ignored by git, so your personal commands won't affect other developers or appear in version control.


### Setup

Follow these steps to set up the development environment:

#### 1. Clone the repository

```bash
git clone <repository-url>
```
```bash
cd swo-adobe-vipm-extension
```

#### 2. Create environment configuration

Copy the sample environment file and update it with your values:

```bash
cp .env.sample .env
```

Edit the `.env` file with your actual configuration values. See the [Configuration](#configuration) section for details on available variables.

In the project root, create and configure the following files.

#### Adobe secrets file

Create `adobe_credentials.json`:

```bash
touch adobe_credentials.json
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

#### 3. Build the Docker images

Build the development environment:

```bash
make build
```

This will create the Docker images with all required dependencies and the virtualenv.

#### 4. Verify the setup

Run the test suite to ensure everything is configured correctly:

```bash
make test
```

You're now ready to start developing! See [Running the service](#running-the-service) for next steps.


## Running the service

Before running, ensure your `.env` file is populated with real endpoints and tokens.

Start the app:

```bash
make run
```

The service will be available at `http://localhost:8080`.

Example `.env` snippet for real services:

```env
EXT_ADOBE_API_BASE_URL=<adobe-vipm-api>
EXT_ADOBE_AUTH_ENDPOINT_URL=<adobe-vipm-authentication-url>
EXT_ADOBE_CREDENTIALS_FILE=/extension/adobe_credentials.json
EXT_WEBHOOKS_SECRETS={"PRD-1111-1111": "<webhook-secret-for-product>", "PRD-2222-2222": "<webhook-secret-for-product>"}
MPT_API_BASE_URL=https://api.s1.show/public
MPT_API_TOKEN=c0fdafd7-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MPT_PORTAL_BASE_URL=https://portal.s1.show
MPT_PRODUCTS_IDS=PRD-1111-1111,PRD-2222-2222
MPT_TOOL_STORAGE_TYPE=airtable
MPT_TOOL_STORAGE_AIRTABLE_API_KEY=<fake-airtable-api-key>
MPT_TOOL_STORAGE_AIRTABLE_BASE_ID=<fake-storage-airtable-base-id>
MPT_TOOL_STORAGE_AIRTABLE_TABLE_NAME=<fake-storage-airtable-table-name>
```

`MPT_PRODUCTS_IDS` is a comma-separated list of SWO Marketplace Product identifiers.
For each product ID in the `MPT_PRODUCTS_IDS` list, define the corresponding entry in the `EXT_WEBHOOKS_SECRETS` JSON using the product ID as the key.



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

### Migration commands

The mpt-tool provides commands for managing database migrations:

```bash
make migrate-check                           # check migration status
make migrate-data                            # run data migrations
make migrate-schema                          # run schema migrations
make migrate-list                            # list available migrations
make migrate-new-data name=migration_id      # create a new data migration
make migrate-new-schema name=migration_id    # create a new schema migration
```


# Configuration

The following environment variables are typically set in `.env`. Docker Compose reads them when using the Make targets described above.

## Application

| Environment Variable                   | Default                 | Example                                 | Description                                                                               |
|----------------------------------------|-------------------------|-----------------------------------------|-------------------------------------------------------------------------------------------|
| `EXT_ADOBE_API_BASE_URL`               | -                       | `https://partner-example.adobe.io`      | Path to Adobe VIPM API                                                                    |
| `EXT_ADOBE_AUTHORIZATIONS_FILE`        | -                       | /extension/adobe_authorizations.json    | Path to Adobe authorizations file                                                         |
| `EXT_ADOBE_AUTH_ENDPOINT_URL`          | -                       | `https://auth.partner-example.adobe.io` | Path to Adobe VIPM authentication API                                                     |
| `EXT_ADOBE_CREDENTIALS_FILE`           | -                       | /extension/adobe_credentials.json       | Path to Adobe credentials file                                                            |
| `EXT_AIRTABLE_SKU_MAPPING_BASE`        | -                       | appXXXXXXXXXXXXXXXX                     | Airtable base ID for the SKU mapping                                                      |
| `EXT_NAV_AUTH_AUDIENCE`                | -                       | `api://default`                         | Audience/identifier string used by the NAV auth provider for JWT validation               |
| `EXT_WEBHOOKS_SECRETS`                 | -                       | {"PRD-1111-1111": "123qweasd3432234"}   | Webhook secret of the Draft validation Webhook in SoftwareONE Marketplace for the product |
| `MPT_API_BASE_URL`                     | `http://localhost:8000` | `https://api.s1.show`                   | SoftwareONE Marketplace API URL                                                           |
| `MPT_API_TOKEN`                        | -                       | eyJhbGciOiJSUzI1N...                    | SoftwareONE Marketplace API Token                                                         |
| `MPT_NOTIFY_CATEGORIES`                | -                       | {"ORDERS": "NTC-0000-0006"}             | SoftwareONE Marketplace Notification Categories                                           |
| `MPT_PORTAL_BASE_URL`                  | `http://localhost:8000` | `https://portal.softwareone.com`        | Base URL for the Marketplace Portal used to construct portal links and API endpoints      |
| `MPT_PRODUCTS_IDS`                     | PRD-1111-1111           | PRD-1234-1234,PRD-4321-4321             | Comma-separated list of SoftwareONE Marketplace Product ID                                |
| `MPT_TOOL_STORAGE_TYPE`                | `local`                 | `airtable`                              | Storage type for MPT tools (local or airtable)                                            |
| `MPT_TOOL_STORAGE_AIRTABLE_API_KEY`    | -                       | patXXXXXXXXXXXXXX                       | Airtable API key for MPT tool storage (required when storage type is airtable)            |
| `MPT_TOOL_STORAGE_AIRTABLE_BASE_ID`    | -                       | appXXXXXXXXXXXXXX                       | Airtable base ID for MPT tool storage (required when storage type is airtable)            |
| `MPT_TOOL_STORAGE_AIRTABLE_TABLE_NAME` | -                       | MigrationTracking                       | Airtable table name for MPT tool storage (required when storage type is airtable)         |

### Azure AppInsights

| Environment Variable                    | Default                            | Example                                                                                                                                                                                               | Description                                                                                                   |
|-----------------------------------------|------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | -                                  | `InstrumentationKey=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx;IngestionEndpoint=https://westeurope-1.in.applicationinsights.azure.com/;LiveEndpoint=https://westeurope.livediagnostics.monitor.azure.com/` | Azure Application Insights connection string                                                                  |
| `LOGGING_ATTEMPT_GETTER`                | adobe_vipm.utils.get_attempt_count | adobe_vipm.utils.get_attempt_count                                                                                                                                                                    | Path to python function that retrieves order processing attempt to put it into the Azure Application Insights |
| `OTEL_SERVICE_NAME`                     | -                                  | Swo.Extensions.AdobeVIPM                                                                                                                                                                              | Service name that is visible in the AppInsights logs                                                          |

### Other

| Environment Variable                   | Default | Example | Description                                                          |
|----------------------------------------|---------|---------|----------------------------------------------------------------------|
| `MPT_ORDERS_API_POLLING_INTERVAL_SECS` | 120     | 60      | Orders polling interval from the Software Marketplace API in seconds |
