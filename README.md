[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension) [![Coverage](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=coverage)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension)

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

# SoftwareONE Adobe VIP Marketplace Extension
Extension integrates Adobe VIP Marketplace Extension with the SoftwareONE Marketplace

# Run tests
```
$ docker-compose build app_test
$ docker-compose run --service-ports app_test
```

# Local run using SoftwareONE Marketplace API

## Create configuration files

1. Create Adobe secrets file
```
$ touch adobe_secrets.json
```

1. Fill Adobe secrets file
```
[
    {
        "authorization_uk": "<authorization-uk>",
        "authorization_id": "<authorization-id>",
        "name": "<name>",
        "client_id": "<client-id>",
        "client_secret": "<client-secret>"
    },
    {...}
]
```

Example of the secrets file
```
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


1. Create Adobe authorizations file
```
$ touch adobe_authorizations.json
```

1. Fill Adobe authorizations file
```
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

Example of the authorizations file
```
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


1. Create environment file
```
$ cp .env.sample .env
```

1. Setup parameters for `.env` file
```
EXT_ADOBE_CREDENTIALS_FILE=/extension/adobe_secrets.json
EXT_ADOBE_API_BASE_URL=<adobe-vipm-api>
EXT_ADOBE_AUTH_ENDPOINT_URL=<adobe-vipm-authentication-url>
MPT_PRODUCTS_IDS=<list-of-softwareone-marketplace-product-id>
MPT_API_BASE_URL=http://devmock:8000
MPT_API_TOKEN=<mpt-api-token>
```

`MPT_PRODUCTS_IDS` should be a comma-separated list of the SWO Marketplace Product identifiers
For each of the defined product id in the `MPT_PRODUCTS_IDS` list define `WEBHOOKS_SECRETS` json variables using product ID as key.

```
EXT_WEBHOOKS_SECRETS={"PRD-1111-1111": "<webhook-secret-for-product>"}
```

Example of `.env` file
```
EXT_ADOBE_CREDENTIALS_FILE=/extension/adobe_secrets.json
EXT_ADOBE_API_BASE_URL=<adobe-vipm-api>
EXT_ADOBE_AUTH_ENDPOINT_URL=<adobe-vipm-authentication-url>
MPT_PRODUCT_ID=PRD-1111-1111,PRD-2222-2222
MPT_API_BASE_URL=http://devmock:8000
MPT_API_TOKEN=c0fdafd7-6d5a-4fa4-9839-4c2c163794ff
EXT_WEBHOOKS_SECRETS={"PRD-1111-1111": "<webhook-secret-for-product>", "PRD-2222-2222": "<webhook-secret-for-product>"}
```


## Build and run extension

1. Build and run the extension
```
$ docker-compose build app
$ docker-compose run --service-ports app
```

# Configuration

## Application
| Environment Variable | Default | Example | Description |
| --- | --- | --- | --- |
| `EXT_ADOBE_CREDENTIALS_FILE` | - | /extension/adobe_secrets.json | Path to Adobe credentials file |
| `EXT_ADOBE_AUTHORIZATIONS_FILE` | - | /extension/adobe_authorizations.json | Path to Adobe authorizations file |
| `EXT_ADOBE_API_BASE_URL` | - | https://partner-example.adobe.io | Path to Adobe VIPM API |
| `EXT_ADOBE_AUTH_ENDPOINT_URL` | - | https://auth.partner-example.adobe.io | Path to Adobe VIPM authentication API |
| `EXT_WEBHOOKS_SECRETS` | - |  {"PRD-1111-1111": "123qweasd3432234"} | Webhook secret of the Draft validation Webhook in SoftwareONE Marketplace for the product |
| `MPT_PRODUCTS_IDS` | PRD-1111-1111 | PRD-1234-1234,PRD-4321-4321 | Comma-separated list of SoftwareONE Marketplace Product ID |
| `MPT_API_BASE_URL` | http://localhost:8000 | https://portal.softwareone.com/mpt | SoftwareONE Marketplace API URL |
| `MPT_API_TOKEN` | - | eyJhbGciOiJSUzI1N... | SoftwareONE Marketplace API Token |

## Azure AppInsights
| Environment Variable | Default | Example | Description |
| --- | --- | --- | --- |
| `SERVICE_NAME` | Swo.Extensions.AdobeVIPM | Swo.Extensions.AdobeVIPM | Service name that is visible in the AppInsights logs |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | - | InstrumentationKey=cf280af3-b686-40fd-8183-ec87468c12ba;IngestionEndpoint=https://westeurope-1.in.applicationinsights.azure.com/;LiveEndpoint=https://westeurope.livediagnostics.monitor.azure.com/ | Azure Application Insights connection string |
| `LOGGING_ATTEMPT_GETTER` | adobe_vipm.utils.get_attempt_count | adobe_vipm.utils.get_attempt_count | Path to python function that retrieves order processing attempt to put it into the Azure Application Insights |

## Other
| Environment Variable | Default | Example | Description |
| --- | --- | --- | --- |
| `MPT_ORDERS_API_POLLING_INTERVAL_SECS` | 120| 60 | Orders polling interval from the Software Marketplace API in seconds |
