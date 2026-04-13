# Deployment

This document is the source of truth for runtime configuration referenced by local development and deployment flows.

## Deployment Model

The repository deploys more than one workload shape from [`helm/swo-extension-adobe/`](../helm/swo-extension-adobe):

- an API workload
- a worker workload
- cron-style worker jobs for commands such as `process_transfers`, `check_running_transfers`, `sync_agreements`, `process_3yc`, `check_gc_agreement_deployments`, and `sync_3yc_enrol`

## Configuration Source

Local Docker Compose reads `.env`.

Deployed workloads receive configuration through Helm config maps, secrets, and mounted JSON files. The deployed templates map the same runtime variables used locally.

## Core Marketplace Settings

| Environment Variable | Default | Example | Description |
| --- | --- | --- | --- |
| `MPT_API_BASE_URL` | `http://localhost:8000` | `https://api.s1.show` | SoftwareOne Marketplace API base URL |
| `MPT_API_TOKEN` | - | `eyJhbGciOiJSUzI1N...` | Marketplace API token |
| `MPT_PORTAL_BASE_URL` | `http://localhost:8000` | `https://portal.softwareone.com` | Marketplace portal base URL |
| `MPT_PRODUCTS_IDS` | `PRD-1111-1111` | `PRD-1111-1111,PRD-2222-2222` | Comma-separated Marketplace product ids |
| `MPT_NOTIFY_CATEGORIES` | `{"ORDERS": "NTC-0000-0006"}` | `{"ORDERS": "NTC-0000-0006"}` | Marketplace notification category mapping |
| `MPT_ORDERS_API_POLLING_INTERVAL_SECS` | `120` | `60` | Order polling interval |

## Adobe Integration Settings

| Environment Variable | Default | Example | Description |
| --- | --- | --- | --- |
| `EXT_ADOBE_API_BASE_URL` | - | `https://partner-example.adobe.io` | Adobe VIPM API base URL |
| `EXT_ADOBE_AUTH_ENDPOINT_URL` | - | `https://auth.partner-example.adobe.io` | Adobe authentication endpoint |
| `EXT_ADOBE_AUTHORIZATIONS_FILE` | - | `/extension/adobe_authorizations.json` | Path to Adobe authorizations JSON |
| `EXT_ADOBE_CREDENTIALS_FILE` | - | `/extension/adobe_credentials.json` | Path to Adobe credentials JSON |
| `EXT_WEBHOOKS_SECRETS` | - | `{"PRD-1111-1111":"secret"}` | Per-product webhook secret mapping |
| `EXT_PRODUCT_SEGMENT` | - | `{"PRD-1111-1111":"COM"}` | Per-product segment mapping |
| `EXT_ORDER_CREATION_WINDOW_HOURS` | `24` | `24` | Window used by order-creation logic |

## Airtable And Tool Storage Settings

| Environment Variable | Default | Example | Description |
| --- | --- | --- | --- |
| `MPT_TOOL_STORAGE_TYPE` | `local` | `airtable` | `mpt-tool` storage backend |
| `MPT_TOOL_STORAGE_AIRTABLE_API_KEY` | - | `patXXXXXXXX` | Airtable API key for `mpt-tool` storage |
| `MPT_TOOL_STORAGE_AIRTABLE_BASE_ID` | - | `appXXXXXXXX` | Airtable base id for `mpt-tool` storage |
| `MPT_TOOL_STORAGE_AIRTABLE_TABLE_NAME` | - | `MigrationTracking` | Airtable table for `mpt-tool` storage |
| `EXT_AIRTABLE_API_TOKEN` | - | `patXXXXXXXX` | Airtable API token used by repository-specific flows |
| `EXT_AIRTABLE_BASES` | - | `{"PRD-1111-1111":"app..."}` | Per-product Airtable base mapping for migration and transfer data |
| `EXT_AIRTABLE_PRICING_BASES` | - | `{"PRD-1111-1111":"app..."}` | Per-product Airtable base mapping for pricing data |
| `EXT_AIRTABLE_SKU_MAPPING_BASE` | - | `appXXXXXXXX` | Airtable base id for SKU mapping |
| `EXT_MIGRATION_RUNNING_MAX_RETRIES` | `10` | `10` | Retry limit for migration-running logic |

## NAV Settings

| Environment Variable | Default | Example | Description |
| --- | --- | --- | --- |
| `EXT_NAV_API_BASE_URL` | - | `https://api.nav` | NAV API base URL |
| `EXT_NAV_AUTH_ENDPOINT_URL` | - | `https://authenticate.nav` | NAV auth endpoint |
| `EXT_NAV_AUTH_AUDIENCE` | - | `api://default` | NAV auth audience |
| `EXT_NAV_AUTH_CLIENT_ID` | - | `<client-id>` | NAV auth client id |
| `EXT_NAV_AUTH_CLIENT_SECRET` | - | `<client-secret>` | NAV auth client secret |

## Notifications And Observability

| Environment Variable | Default | Example | Description |
| --- | --- | --- | --- |
| `EXT_MSTEAMS_WEBHOOK_URL` | - | `https://...office.com/...` | Microsoft Teams webhook used by notification helpers |
| `EXT_EMAIL_NOTIFICATIONS_ENABLED` | - | `true` | Enables email notification flows where configured |
| `EXT_EMAIL_NOTIFICATIONS_SENDER` | - | `noreply@example.com` | Sender address for email notifications |
| `EXT_AWS_SES_REGION` | - | `eu-west-1` | AWS SES region |
| `EXT_AWS_SES_CREDENTIALS` | - | `<json-or-secret-ref>` | AWS SES credentials |
| `EXT_GC_EMAIL_NOTIFICATIONS_RECIPIENT` | - | `ops@example.com` | Recipient list for global-customer notification flows |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | - | `InstrumentationKey=...` | Azure Application Insights connection string |
| `OTEL_SERVICE_NAME` | - | `Swo.Extensions.AdobeVIPM` | Telemetry service name |

## File-Based Secrets

The runtime reads Adobe authorizations and credentials from the file paths provided by:

- `EXT_ADOBE_AUTHORIZATIONS_FILE`
- `EXT_ADOBE_CREDENTIALS_FILE`

In local Docker Compose runs, these usually point to files in the repository root because the repository is mounted at `/extension`.

In deployed environments, the same paths are expected to exist inside the container through mounted secrets or equivalent file injection.

## Adobe JSON File Formats

### `EXT_ADOBE_CREDENTIALS_FILE`

The credentials file must be a JSON array. Each item represents one Adobe authorization credential set.

Expected fields:

- `authorization_uk`
- `authorization_id`
- `name`
- `client_id`
- `client_secret`

Example:

```json
[
  {
    "authorization_uk": "pl-adobe-auth-us",
    "authorization_id": "AUT-5774-7413",
    "name": "Credentials for US",
    "client_id": "<client-id>",
    "client_secret": "<client-secret>"
  }
]
```

The `authorization_uk` value must match the corresponding authorization entry in `EXT_ADOBE_AUTHORIZATIONS_FILE`.

### `EXT_ADOBE_AUTHORIZATIONS_FILE`

The authorizations file must be a JSON object with an `authorizations` array.

Each authorization entry is expected to contain:

- `authorization_uk`
- `authorization_id`
- `distributor_id`
- `currency`
- `resellers`

Each reseller entry is expected to contain:

- `id`
- `seller_uk`
- optionally `seller_id`

Example:

```json
{
  "authorizations": [
    {
      "authorization_uk": "pl-adobe-auth-us",
      "authorization_id": "AUT-5774-7413",
      "distributor_id": "db5a6d9c-9eb5-492e-a000-ab4b8c29fc63",
      "currency": "USD",
      "resellers": [
        {
          "id": "P1000050972",
          "seller_id": "SEL-7282-9889",
          "seller_uk": "SWO_US"
        }
      ]
    }
  ]
}
```

The repository loads credentials by `authorization_uk` and augments reseller data from the authorization file, so the two files must stay consistent.
