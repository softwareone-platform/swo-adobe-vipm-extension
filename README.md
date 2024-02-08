[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension) [![Coverage](https://sonarcloud.io/api/project_badges/measure?project=softwareone-platform_swo-adobe-vipm-extension&metric=coverage)](https://sonarcloud.io/summary/new_code?id=softwareone-platform_swo-adobe-vipm-extension)
# SoftwareONE Adobe VIP Marketplace Extension
Extension integrates Adobe VIP Marketplace Extension with the SoftwareONE Marketplace

# Local run
```
docker-compose build app
docker-compose run --service-ports app
```

# Run tests
```
docker-compose build app_test
docker-compose run --service-ports app_test
```

# Run devmock and generate test data

1. Build and run bash command for container
```
docker-compose build bash
docker-compose run --service-ports bash
```

2. Install dependencies for devmock inside the container
```
poetry install
```

3. Generate order using `mockgendata` command
```
mockgendata purchase <cutted-sku>
```

For more information about the `mockgendata` command use the `--help option`
For generating order use the cutted form of the Adobe SKU, removing last 5 symbols from it

4. Run the app in another console session to process the generated fake order
```
docker-compose build app
docker-compose run --service-ports app
```
