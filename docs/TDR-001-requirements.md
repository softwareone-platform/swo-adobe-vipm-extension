# TDR: SDK requirements

## Scope
This document describes the requirements for the SDK v6 architecture and runtime model.

## Requirements

### Functional

1. SDK should be able to expose an HTTP interface used by the Marketplace Extension Service to trigger events
2. SDK should have an MPT API client that Developers can use to interact with the Marketplace Platform API
3. SDK should cover all the boilerplate code to focus the Developers on business logic only
4. SDK should support sync/async execution models
5. SDK should be designed in a way that any extension can have multiple instances running at the same time
6. SDK should support running extensions on the K8S cluster, the local machine of the developer, or the Vendor/Client infrastructure
7. SDK should minimize the number of external services that are required to run the Extension
8. SDK should support blue/green deployment of the Extension code
9. SDK by default should follow Extensions Logging Best Practices
10. SDK should be able to override logging configuration to add additional libraries for instrumentation/disable AppInsights
11. Developer should be able to override the default Extension configuration to provide additional parameters
12. SDK should provide a way to run one-time/periodic commands using the CLI interface
13. SDK should provide a way to run one-time/periodic commands on the event from the Marketplace Extension Service
14. SDK should provide a CLI command to run the extension, validate the extension code, add a new command, and initialize the extension
15. SDK should use env variables for configuration

### Integration
1. SDK when starts should register the instance on the Marketplace API by sending POST /instances, providing parameters in the body from the article
2. SDK should start the uvicorn workers using the OpenZiti solution. It allows the Marketplace API to call event handlers securely
3. The API client should be able to authorize against the Extension Installation. Technically, it means to exchange the extension token for the token for a particular account that belongs to the Extension installation. More details in here.
4. SDK should provide a way for extensions to describe events/plugs/schedules/openapi specification
5. OpenAPI specification can be provided either by an endpoint with JSON file or as an object to the instance

### Security
1. For event HTTP calls, it is not required to check JWT or any other tokens. It is already done by the Platform and Openziti

### Performance
1. SDK should provide the ability to scale the number of workers/threads for the extension

### Observability
The SDK is responsible for providing a consistent and transparent observability model across all extensions.
Tracing must be enabled by default without requiring any instrumentation in the business logic layer.

According to extension best practices, extensions must contain only domain-specific logic, while all technical and platform-related concerns must be isolated outside of the extension codebase .
Therefore, observability (including tracing) must be fully managed by the SDK and must not leak into extension implementation.

The system processes events through a structured execution flow (event → pipeline → steps), and tracing should reflect this hierarchy.
Additionally, the SDK must support multiple exporters and allow flexible configuration without coupling the business logic to OpenTelemetry APIs.
Requirements

1. SDK must initialize and manage OpenTelemetry.
2. SDK must support registering multiple exporters.
3. Business logic must not depend on OpenTelemetry APIs.
4. No tracing-related code should be required in extensions.
5. Spans must be created automatically following the execution structure:
    ```
    Event → root span
    Pipeline → child span
    Step / unit of work → child spans
    ```
6. Each event processing must generate an independent root trace (aligned with operation isolation).
