[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension) [![Coverage](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=coverage)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension)

[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

# SoftwareONE Adobe VIP Marketplace Extension
Extension integrates Adobe VIP Marketplace Extension with the SoftwareONE Marketplace

# Run tests
```
$ docker-compose build app_test
$ docker-compose run --service-ports app_test
```

# Local run using mocked SoftwareONE Marketplace API

## Create configuration files

1. Create Adobe secrets file
```
$ touch adobe_secrets.json
```

1. Fufill Adobe secrets file
```
[
    {
        "country": "<two-letters-country>",
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
        "country": "US",
        "client_id": "cc7fce0d-f2e8-45c2-a61e-452b31d096c7",
        "client_secret": "cltn3c1eo0001m5pxkdcmd8cl"
    }
]
```

The list of supported countries can be found in [adobe_vipm/adobe_config.json](adobe_vipm/adobe_config.json:795) "code" field.

1. Create environment file
```
$ cp .env.sample .env
```

1. Setup parameters for `.env` file
```
EXT_ADOBE_CREDENTIALS_FILE=/extension/adobe_secrets.json
EXT_QUERYING_TEMPLATE_ID=<querying-template-id>
EXT_COMPLETED_TEMPLATE_ID=<completed_template-id>
EXT_ADOBE_API_BASE_URL=<adobe-vipm-api>
EXT_ADOBE_AUTH_ENDPOINT_URL=<adobe-vipm-authentication-url>
MPT_PRODUCT_ID=<softwareone-marketplace-product-id>
MPT_API_BASE_URL=http://devmock:8000
```

Example of `.env` file
```
EXT_ADOBE_CREDENTIALS_FILE=/extension/adobe_secrets.json
EXT_QUERYING_TEMPLATE_ID=TPL-1234-5678
EXT_COMPLETED_TEMPLATE_ID=TPL-3333-4444
EXT_ADOBE_API_BASE_URL=<adobe-vipm-api>
EXT_ADOBE_AUTH_ENDPOINT_URL=<adobe-vipm-authentication-url>
MPT_PRODUCT_ID=PRD-1111-1111-1111
MPT_API_BASE_URL=http://devmock:8000
```


## Build and run extension

1. Build and run the extension
```
$ docker-compose build app
$ docker-compose run --service-ports app
```

## Generate mocked SoftwareONE Marketplace orders
1. Build and run mocked data generator
```
$ docker-compose build bash
$ docker-compose run --service-ports bash
```

1. Inside the `bash` container use `mockgendata` command
```
$ mockgendata sku <name>
$ mockgendata purchase <sku>
```

For more information use `--help` option
```
$ mockgendata --help
```

Find generated data in the `devmock/data` folder. Extension automatically retrieve generated order from the mocked data

# Configuration

## Application
| Environment Variable | Default | Example | Description |
| --- | --- | --- | --- |
| `EXT_ADOBE_CREDENTIALS_FILE` | - | /extension/adobe_secrets.json | Path to Adobe credentials file |
| `EXT_ADOBE_API_BASE_URL` | - | https://partner-example.adobe.io | Path to Adobe VIPM API |
| `EXT_ADOBE_AUTH_ENDPOINT_URL` | - | https://auth.partner-example.adobe.io | Path to Adobe VIPM authentication API |
| `EXT_QUERYING_TEMPLATE_ID` | - | TPL-1111-1111 | SoftwareONE Marketplace Template ID for Order Quering status |
| `EXT_COMPLETED_TEMPLATE_ID` | - | TPL-2222-2222 | SoftwareONE Marketplace Template ID for Order Completed status |
| `MPT_PRODUCT_ID` | PRD-1111-1111-1111 | PRD-1234-1234-1234 | SoftwareONE Marketplace Product ID |
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
