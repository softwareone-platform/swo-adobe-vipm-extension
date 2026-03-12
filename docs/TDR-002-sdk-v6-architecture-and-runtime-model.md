# TDR: SDK v6 architecture and runtime model

## Status
Pending

## Date
2026-03-11

## Related ADR
- `ADR-001-introduce-sdk-v6.md`

## Context

This document defines the technical design and runtime model for SDK v6. Architectural rationale, alternatives, and trade-offs are documented in the related ADR.

---

## 1. Runtime framework

The SDK runtime is based on `FastAPI`.

Runtime execution modes are:

```text
Local development -> FastAPI + uvicorn
Production -> Ziticorn (mrok - OpenZiti)
```

The SDK must expose a `run()` abstraction that selects the appropriate runtime for the current environment.

Illustrative runtime entrypoint:

```python
from mrok.agent import ziticorn

identity_file_path = "/path/to/identity.json"

ziticorn.run("extension.app:app", identity_file_path, server_workers=4)
```

---

## 2. Extension metadata

Each extension must provide a metadata file named `meta.yaml`.

The metadata file defines:

* version
* OpenAPI specification location
* deferrables
* events
* plugs
* schedules
* webhooks

The SDK must load and validate `meta.yaml` during startup.

Example:

```yaml
version: 1.0.0
openapi: /bypass/openapi.json
deferrables:
  - path: /api/v2/tasks/orders/synchronize
    method: GET
    description: "Run a background order synchronization task"
events:
  - event: platform.commerce.order.status_changed
    path: /api/v2/events/orders/purchase
    condition: "and(in(product.id,{{ settings.PRODUCT_IDS }}),eq(type,Purchase))"
    task: true
  - event: platform.commerce.order.created
    path: /api/v2/events/orders/termination
    condition: "and(in(product.id,{{ settings.PRODUCT_IDS }}),eq(type,Termination))"
    task: false
plugs:
  - id: subs-actions
    name: Subscriptions Actions Demo
    description: Check sockets
    icon: adobe.png
    socket: portal.commerce.subscriptions.actions
    href: "/static/index.js"
schedules:
  - id: adobe.core.refresh_token
    path: /api/v2/schedules/agreements/sync
    description: "Allows to sync agreements periodically"
    cron: "* * * * */5"
webhooks:
  - type: validationPurchaseOrderDraft
    description: "Validate a purchase order draft"
    path: /api/v2/webhooks/orders/validate
    criteria:
      product.id: "{{ settings.product_id }}"
```

>The metadata schema describes the target SDK model.
>In the first version, only `version`, `openapi`, and `events` are required and supported.
---

## 3. Instance registration

On startup, the SDK must register the extension instance with the Marketplace API.

Registration endpoint:

```text
POST /public/v1/integration/extensions/<ext-id>/instances
```

The registration payload must include the extension `externalId`, the running version, and the generated `meta` object derived from `meta.yaml`.

Payload example:

```json
{
  "externalId": "swo-extension-adobe-api-6bbd8f8b6f-8jf5x",
  "version": "1.0.0",
  "meta": {"events": []}
}
```

The SDK must create or update the identity file as part of the registration process.

---

## 4. Event handling model

The Marketplace Extension Service triggers events through HTTP endpoints exposed by the runtime.

The SDK must register these routes automatically during startup.

Example route:

```text
POST /api/v2/events/orders/purchase
```

The event processing model is defined as follows:

* each path is mapped to a specific order type
* the event type in the payload determines the pipeline to execute
* each pipeline contains one or more steps

```text
event
 -> path (order_type)
    -> event_type
        -> pipeline
           -> step
           -> step
```

### 4.1 Illustrative event processing scenarios

* Fast pipelines. Example: Synchronous call to Vendor API
   1. The extension receives the event
   2. The extension runs the pipeline
   3. The extension returns a response within 60 seconds
* Long pipelines. Example: Asynchronous call to the vendor API — multiple attempts
  1. The extension receives the event (taskId=1)
  2. The extension runs the pipeline
  3. The extension returns a Defer response
  4. The extension receives the event (taskId=1)
  5. The extension runs the pipeline
  6. The extension returns an OK response or Defer response (go to 4)

* Error handling. Example: Third party is down
  1. The extension receives the event
  2. The extension runs the pipeline. Third party is down
  3. The extension returns a Defer response

* Deferred execution (MPT-Async: true)
  1. TODO
  2. ...

### 4.2 Delivery contracts by event type

The SDK supports two types of events depending on the `task` flag defined in the `meta.yaml` file:

| Metadata flag | Request                              | Response                             | Retry                                        |
|---------------|--------------------------------------|--------------------------------------|----------------------------------------------|
| task: true    | Event payload with task context      | EventResponse (OK, Defer, Cancel)    | Controlled by Marketplace task orchestration |
| task: false   | Event payload without task lifecycle | Response (204 No Content on success) | No task-level retry contract                 |

EventResponse:
* OK: Event processed successfully. The task is marked as completed.
* Defer: Event processing is postponed, and the task is scheduled for a later delivery.
* Cancel: Event was delivered successfully, but the extension declines to process it.
* Unexpected error: Mapped to Cancel by default.

Response:
* On success the runtime returns 204 No Content.
* On unhandled exceptions, the runtime returns an HTTP error response.

Operational delivery constraints:
* Response must be returned within 60 seconds. After that time the message delivery is considered failed.
* Task-based events can be stored for not more than 1 week until they are processed.
* Deferred delivery may be retried for up to 2 days.
* Default defer delay is 5 minutes.
* A message may be retried up to 10 times.

---

## 5. Pipeline execution model

Pipelines are stateless.

The SDK must not persist pipeline execution state.

The runtime relies on the Marketplace orchestrator for:

* serialized processing of the same object
* retry handling
* task lifecycle management

---

## 6. Step design

Steps must implement the following lifecycle contract:

```python
from abc import ABC, abstractmethod


class BaseStep(ABC):
    async def run(self, ctx):
        await self.pre(ctx)
        await self.process(ctx)
        await self.post(ctx)

    async def pre(self, ctx):
        pass

    @abstractmethod
    async def process(self, ctx):
        raise NotImplementedError()

    async def post(self, ctx):
        pass
```

Responsibilities:

| Method    | Responsibility                  |
|-----------|---------------------------------|
| `pre`     | optional validation and setup   |
| `process` | required business logic         |
| `post`    | optional cleanup, notifications |

Steps may raise typed SDK exceptions.

---

## 7. Pipeline orchestration

The SDK controls pipeline execution.

```python
class SkipStepError(Exception):
    pass


class Pipeline:
    def __init__(self, steps):
        self.steps = steps

    async def execute(self, ctx):
        for step in self.steps:
            try:
                await step.run(ctx)
            except SkipStepError:
                continue
```

The SDK must execute steps sequentially.

If a step raises `SkipStepError`, execution must continue with the next step.

Exception handling and response mapping must be centralized in the runtime.

---

## 8. Error handling model

The SDK defines a typed error hierarchy.

RuntimeError:
- ConfigError

PipelineError:
- CancelError
- DeferError
- FailError

StepError:
- SkipStepError: the pipeline continues with the next step
- StopStepError: the pipeline stops and returns CancelError
- DeferStepError: the pipeline stops and returns DeferError

The SDK must handle `StepError` automatically while the pipeline is running and
return the appropriate `PipelineError` when required.

Execution flow:

Route -> Pipeline -> Step
EventResponse <- PipelineError <- StepError

The runtime converts exceptions to `EventResponse` using a global mapper.

Mapping to `EventResponse`:

PipelineError:
- CancelError -> Cancel
- DeferError -> Defer
- FailError -> Cancel (reason: "Failed to process the event")

RuntimeError and inherited exceptions -> Cancel (reason: "Runtime error")
Unexpected error -> Cancel (reason: "Unexpected error")


Exception mapping is fixed at the SDK level and cannot be overridden by extensions. Extensions may
inherit from the SDK exceptions to provide more granular error semantics.

---

## 9. Execution context

Pipelines receive a unified `ExecutionContext` object.

The execution context must expose runtime metadata such as:

```text
ctx.execution.event_id
ctx.execution.object_id
ctx.execution.installation_id
```

The context must also provide:

```text
ctx.config
ctx.logger
ctx.mpt_api_service
ctx.payload
ctx.state
```

The `ctx.state` is an object that can be used to store intermediate results. It can be shared across steps in the same pipeline execution.

---

## 10. MPTAPIService layer

The SDK uses `mpt-api-python-client` internally.

The SDK must expose a stable Marketplace service layer through the execution context:

```text
ctx.mpt_api_service
```

Authentication must use the Account API token.

Business logic must depend on SDK services instead of the raw API client.

Example:

```python
async def mark_order_querying(ctx, order_id):
    await ctx.mpt_api_service.orders.mark_querying(order_id)
```

---

## 11. Async runtime with sync support

The SDK runtime is asynchronous. The SDK must provide a helper to use synchronous processing.

Illustrative helper:

```python
import anyio


async def run_sync(func, *args, **kwargs):
    return await anyio.to_thread.run_sync(lambda: func(*args, **kwargs))
```

Usage example:

```python
async def handle_order(service, run_sync):
    await run_sync(service.process_order)
```

---

## 12. Observability

Observability is provided by the SDK runtime.

The runtime must support:

* structured logging
* request correlation
* OpenTelemetry integration
* pluggable instrumentation adapters

Example adapter targets:

```text
requests
httpx
boto3
```

Instrumentation adapters may be enabled through configuration.

---

## 13. CLI tooling

The SDK provides a CLI for extension development and runtime operations.

Commands:

```text
swo-ext init
swo-ext run
swo-ext register
swo-ext validate
```

The CLI supports:

* Extension initialization
* Extension registration
* Local runtime execution
* Metadata validation

---

## Open questions

* Should mpt_api_service allow an operations and vendor api service at the same time?
* Async runtime with sync support. Does it make sense to do it in the first version?
* Cli tooling: review init and validate commands. Init can be done with a template in GitHub or cookiecutter.
* Add an example of how logs and set context should be used
* Add an example of how to instrument Opentelemetry and create spans
* Should dead instances be removed from the Marketplace?
* Add a point to the docs about the notification model
* Define the structure of the final extension directory

```text
mpt-extension-sdk/
   api/
     /v2
       routes/
         events/
         schedulers/
         webhooks/
   cli/
     commands/
       init.py
       run.py
       validate.py
   docs/
   errors/
   metadata/
     meta.py
     validation.py
   observability/
     instrumentation.py
     metrics.py
     tracing.py
   pipelines/
     base.py
       steps/
         base.py
   runtime/
     app.py
     config.py
     logger.py
   services/
     mpt_api_service.py
   pyproject.toml
   README.md
```
