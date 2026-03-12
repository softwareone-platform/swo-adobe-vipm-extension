# Creating a New Extension with SDK v6

## 1. Initialize Extension (TBD)

```shell
swoext init my-extension
```

This generates the base structure.

```text
my-extension/
  .env.sample
  my-extension/
    api/
       __init__.py
       routes.py
    flows/
       __init__.py
       pipelines.py
       steps.py
    app.py
    settings.py
  meta.yaml

```

## 2. Define metadata in `ExtensionApp` and route decorators

In the first version, the generated `meta.yaml` supports only the version,
openapi, and events sections. Schedules, deferrables, plugs, and webhooks are
not included in the initial scope.

### 2.1 Choose between `task` and `non-task` events

- Use `task: true` when the platform must track the outcome of the processing.
- Use `task: false` when the platform does not need to track the outcome of the processing.


## 3. Create the extension app and register routes

Create one explicit `ExtensionApp`, define one or more `ExtensionRouter`
objects, and include them in the app.

```python
from mpt_extension_sdk import ExtensionApp, ExtensionRouter

ext_app = ExtensionApp(prefix="/api/v2")
orders_router = ExtensionRouter()
```

Then use `task_route` for `task` events and `route` for `non-task` events
from the router object. Each route must define its event name and can define an
optional condition.

```python
@orders_router.task_route(
    "/events/orders/purchase",
    name="orders-purchase",
    event="platform.commerce.order.created",
    condition="and(in(product.id,{{ settings.PRODUCT_IDS }}),eq(status,Processing))",
)
async def purchase_orders(event: TaskEvent, context: OrderContext) -> None:
    await PurchasePipeline().execute(context)
```

```python
@orders_router.route(
    "/events/orders/change",
    name="orders-change",
    event="platform.commerce.order.status_changed",
    condition="and(in(product.id,{{ settings.PRODUCT_IDS }}),eq(status,Processing))",
)
async def handle_change_order(event: Event, context: OrderContext) -> None:
    await ChangePipeline().execute(context)
```

```python
ext_app.include_router(orders_router)
```

The runtime materializes `meta.yaml` automatically on `swoext run` and
`swoext run --local`. If you want to write the file without starting the
service, use:

```shell
swoext meta generate
```

Generated example:

```yaml
version: 1.0.0
openapi: /bypass/openapi.json
events:
  - event: platform.commerce.order.created
    condition: "and(in(product.id,{{ settings.PRODUCT_IDS }}),eq(status,Processing))"
    path: /api/v2/events/orders/purchase
    task: true
  - event: platform.commerce.order.status_changed
    condition: "and(in(product.id,{{ settings.PRODUCT_IDS }}),eq(status,Processing))"
    path: /api/v2/events/orders/change
    task: false
```

Each event must be unique across the extension. The SDK rejects duplicate
event registrations even if the route path or condition differs.

The same app wiring layer can also extend the Marketplace service container
exposed through the execution context. This allows an extension to add new services
when the SDK still does not expose a capability you need. See the next section for more details.

```python
from mpt_extension_sdk import ExtensionApp
from mpt_extension_sdk.services.mpt_api_service import MPTAPIService

from my_extension.services.mpt.notifications import NotificationService


class ExtensionMPTAPIService(MPTAPIService):
    def __init__(self, client) -> None:
        super().__init__(client)
        self.notifications = NotificationService(client)


ext_app = ExtensionApp(
    prefix="/api/v2",
    version="1.0.0",
    openapi="/bypass/openapi.json",
    mpt_api_service_type=ExtensionMPTAPIService,
    order_context_type=AdobeOrderContext,
)
```

If an extension configures a derived context type in `ExtensionApp`, the SDK
adapts the base context automatically before invoking the handler.

The runtime context model is:

```text
event
 -> SDK base context
    -> ExecutionContext / OrderContext / AgreementContext
       -> optional extension-specific derived context
```

The adaptation contract is:

- if no derived context type is configured in `ExtensionApp`, the SDK passes
  the base context through
- if `order_context_type` or `agreement_context_type` is configured, the SDK
  uses that type for the matching base context
- the configured context type must inherit from the matching SDK base context
  and implement `ContextAdapter`
- the configured context type must define a `from_context()` classmethod
- if `from_context()` is missing, startup fails with an explicit configuration
  error

Use a derived context when:

- the pipeline needs extension-specific mutable state across steps
- you want domain helpers that make the business logic easier to read
- the generic SDK object-state channels are not enough for domain-specific runtime state

Do not use a derived context to:

- rebuild SDK settings or API clients
- mutate Marketplace models in place
- hide writes that should go through `ctx.mpt_api_service`

Concrete example:

```python
from dataclasses import dataclass, field
from typing import Self

from mpt_extension_sdk.pipeline import ContextAdapter, OrderContext


@dataclass
class AdobeOrderContext(OrderContext[ExtensionMPTAPIService], ContextAdapter):
    adobe_customer: AdobeCustomer | None = None
    adobe_orders: list[AdobeOrder] = field(default_factory=list)

    @classmethod
    def from_context(cls, ctx: OrderContext) -> Self:
        return cls(
            ext_settings=ctx.ext_settings,
            runtime_settings=ctx.runtime_settings,
            account_settings=ctx.account_settings,
            meta=ctx.meta,
            logger=ctx.logger,
            mpt_api_service=ctx.mpt_api_service,
            order=ctx.order,
            order_state=ctx.order_state,
            state=ctx.state,
        )
```

This keeps a clear separation between:

- `ctx.order`: immutable Marketplace snapshot
- `ctx.order_state`: generic SDK channel for order status transitions
- derived-context attributes: extension-specific working state
- `ctx.state`: generic mutable storage for temporary pipeline data

## 4. Temporarily subclass `MPTAPIService`

Business logic should use `ctx.mpt_api_service` services. The SDK builds the
base services and an extension can replace that container type from
`ExtensionApp`.

This mechanism is intended as a temporary escape hatch for endpoints or
behaviors that are not yet available in the SDK. The expected path is:

1. unblock the extension with an `ExtensionMPTAPIService` subclass
2. use it only in the places that need it
3. remove the workaround once the SDK exposes the capability natively

To add a temporary resource, subclass `MPTAPIService` and assign it in
`__init__`:

```python
class ExtensionMPTAPIService(MPTAPIService):
    def __init__(self, client) -> None:
        super().__init__(client)
        self.system = SystemService(client)
```

From business logic, both are consumed in the same way:

```python
await ctx.mpt_api_service.orders.mark_querying(order.id)

task = await ctx.mpt_api_service.system.tasks.get(ctx.meta.task_id)
```

To customize only one method of a base service, replace that service in your
subclass and keep the rest of the behavior inherited:

```python
from mpt_extension_sdk import ExtensionApp
from mpt_extension_sdk.models import Order
from mpt_extension_sdk.services.mpt_api_service import MPTAPIService
from mpt_extension_sdk.services.mpt_api_service.order import OrderService


class OrderServiceV2(OrderService):
    @override
    async def get_by_id(self, order_id: str) -> Order:
        order = await self._client.commerce.orders.get(
            order_id,
            select=[
                "agreement",
                "lines",
                "parameters",
                "yourExtraField",
            ],
        )
        return Order.from_payload(order)


class ExtensionMPTAPIService(MPTAPIService):
    def __init__(self, client) -> None:
        super().__init__(client)
        self.orders = OrderServiceV2(client)


ext_app = ExtensionApp(
    prefix="/api/v2",
    version="1.0.0",
    openapi="/bypass/openapi.json",
    mpt_api_service_type=ExtensionMPTAPIService,
)
```

The SDK still uses `mpt-api-python-client` internally, but extensions should
consume the shared `ctx.mpt_api_service` contract instead of building ad-hoc
clients inside handlers, pipelines, or steps.


## 5. Build a pipeline

Use stateless idempotent pipelines.

```python
class OrderPipeline(BasePipeline):
    @override
    @property
    def steps(self) -> list[BaseStep]:
        return [ValidateOrderStep(), SubmitVendorOrderStep(), CompleteOrderStep()]
```

`BasePipeline` also exposes overrideable hooks for step outcomes:

- `on_step_succeeded()`
- `on_step_skipped()`
- `on_step_deferred()`
- `on_step_stopped()`
- `on_step_failed()`

These hooks let an extension add cross-step behavior without copying the full
pipeline execution logic.

Typical use cases:

- centralize order/agreement failure handling for one extension
- trigger extension-specific notifications
- add extra logging or metrics for specific outcome types

Example:

```python
class MyOrderPipeline(BasePipeline):
    async def on_step_stopped(
        self,
        step: BaseStep,
        ctx: OrderContext,
        error: StopStepError,
    ) -> None:
        await super().on_step_stopped(step, ctx, error)

        if ctx.order_state.action is None or ctx.order_state.handled:
            return

        action = ctx.order_state.action
        if action.target_status == OrderStatusActionType.FAIL:
            await ctx.mpt_api_service.orders.fail(
                order_id=ctx.order_id,
                status_notes=action.status_notes,
                parameters=action.parameters,
            )
        else:
            await ctx.mpt_api_service.orders.query(
                order_id=ctx.order_id,
                status_notes=action.status_notes,
                parameters=action.parameters,
            )
        ctx.order_state.handled = True
```

## 6. Implement steps with `pre/process/post`

```python
class ValidateOrderStep(BaseStep):
    @override
    async def pre(self, ctx: OrderContext) -> None:
        if not ctx.order.customer:
            raise StopStepError("No customer found for order")

    @override
    async def process(self, ctx: OrderContext) -> None: ...

    @override
    async def post(self, ctx: OrderContext) -> None:
        ctx.logger.info("ValidateOrderStep finished")
```

Step lifecycle behavior:

- `pre()` is optional and runs first
- `process()` contains the main business logic
- `post()` is optional and runs after `process()` on success and on failure
- if both `process()` and `post()` fail, the `post()` exception is raised and
  chained from the original `process()` error

Use `post()` for step-local cleanup or compensating actions.

When a step must trigger an extension-level object status transition such as:

- failing an order or agreement
- switching an order to query
- sending a notification
- resetting extension-specific fields

prefer the pipeline hooks plus `ctx.order_state` / `ctx.agreement_state` over duplicating the same side
effects in many steps.

To declare an order status transition from a step, set `ctx.order_state.action`
and then
raise `StopStepError`:

```python
from mpt_extension_sdk.pipeline import OrderStatusAction, OrderStatusActionType


ctx.order_state.action = OrderStatusAction(
    target_status=OrderStatusActionType.FAIL,
    message="Duplicate items found",
    status_notes={"details": "..."},  # example payload
    parameters=ctx.order.parameters.to_dict(),
)
raise StopStepError("Duplicate items found")
```

## 7. Immutable objects
The SDK uses immutable Marketplace models to avoid hidden side effects during
pipeline execution.

Treat `ctx.order` as a snapshot of the current Marketplace state, not as a
mutable working copy.

### 7.1 Working rule

When a step needs to change order-related state:

1. read from `ctx.order`
2. build a new payload without mutating the in-memory model
3. persist the change through `ctx.mpt_api_service`
4. refresh the order only when later logic in the same pipeline needs the
   updated Marketplace representation

Do not mutate:

- `ctx.order`
- `ctx.order.lines`
- `ctx.order.parameters`
- nested models such as agreement, subscription, asset, or price objects

### 7.2 Parameter updates

For parameter changes, use immutable helpers on `ParameterBag` instead of
mutation-style setters.

Recommended helpers:

- `with_ordering_value(...)`
- `with_fulfillment_value(...)`
- `with_ordering_error(...)`
- `with_fulfillment_error(...)`

Example:

```python
updated_parameters = ctx.order.parameters.with_fulfillment_value("deploymentId", deployment_id)

await ctx.mpt_api_service.orders.update(ctx.order_id, parameters=updated_parameters.to_dict())
```

### 7.3 Refreshing the order

The SDK exposes two refresh mechanisms:

- `await ctx.refresh_order()`
- `@refresh_order`

`ctx.refresh_order()` reloads the canonical order from Marketplace.

`@refresh_order` is a convenience decorator for read-after-write steps. Use it
only when later code in the same pipeline needs the refreshed order graph.

Typical examples:

- creating subscriptions inside the order
- creating assets inside the order
- updating order structure that a later step must read back from Marketplace

Do not use `@refresh_order` by default on every step. It adds an extra fetch and
should only be used when the refreshed state is actually needed.

Example:

```python
from mpt_extension_sdk.pipeline import BaseStep, refresh_order


class CreateOrderSubscriptionsStep(BaseStep):
    @override
    @refresh_order
    async def process(self, ctx: OrderContext) -> None:
        await ctx.mpt_api_service.subscriptions.create_order_subscription(
            ctx.order_id,
            name="Example subscription",
            lines=[{"id": ctx.order.lines[0].id}],
        )
```

### 7.3 Refreshing the agreement

The SDK exposes also two refresh mechanisms for agreements:

- `await ctx.refresh_agreement()`
- `@refresh_agreement`


### 7.5 What to avoid

Avoid patterns like:

```python
ctx.order.parameters.set_fulfillment_value(...)
ctx.order.external_ids.vendor = "..."
line.price.unit_pp = new_price
ctx.order.subscriptions.append(subscription)
```

Those patterns work against the SDK model and make retry behavior harder to
reason about.

## 8. Error mapping model

The SDK is responsible for mapping errors to the appropriate EventResponse. The following exceptions
are handled automatically:
RuntimeError:
- ConfigError
- ExtRuntimeError

PipelineError:
- CancelError
- DeferError
- FailError

StepError:
- SkipStepError: the pipeline continues with the next step
- StopStepError: the pipeline stops and returns CancelError
- DeferStepError: the pipeline stops and returns DeferError

As a developer, in most step implementations you only need to raise the step
errors:

Use `SkipStepError` when the step should be skipped
Use `StopStepError` when the pipeline should stop. It returns a Cancel EventResponse.
Use `DeferStepError` when third-party status is pending and the pipeline should
be retried later.
Use `FailError` only when you need non-retriable pipeline-level failure
semantics outside the step-error model.

`StopStepError` controls the pipeline flow only. If the extension needs extra
business behavior on stop, use `ctx.order_state.action` or
`ctx.agreement_state.action` plus a pipeline hook such as `on_step_stopped()`.

You can also inherit from one of them to create a granulate error handling if needed

```python
class OrderFailedStopStepError(StopStepError): ...
```

## 9. Configure observability

The SDK manages tracing for the runtime and for pipeline execution.

When observability is enabled, the SDK:

- configures the process-wide tracing provider
- instruments FastAPI automatically
- instruments `httpx` automatically
- instruments logging correlation automatically
- creates spans for pipeline and step execution

Business logic does not need to initialize OpenTelemetry inside handlers,
pipelines, or steps.

Use this local configuration block:

```env
SDK_OBSERVABILITY_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

Current exporter behavior is:

- OTLP export is enabled by default when observability is enabled
- Azure Monitor export is added automatically when
  `SDK_APPLICATIONINSIGHTS_CONNECTION_STRING` is set

There is no separate `SDK_OTEL_EXPORTERS` switch in the current SDK runtime.

The SDK automatically instruments:

- FastAPI
- httpx
- logging correlation

Logs keep the existing request context fields and also include `trace_id` and
`span_id`.

### 9.1 Run tracing locally with Jaeger

To run tracing locally, run a Jaeger service and point OTLP to it.

If the extension process runs inside Docker, use the Jaeger service name:

```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318
```

If the extension process runs directly on the host, use localhost:

```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

Start the local stack and open Jaeger UI at:

```text
http://localhost:16686
```

Then send a request and inspect the trace tree:

```text
event -> pipeline -> step
```

The pipeline and step spans are created by the SDK pipeline executor, so an
extension that uses `BasePipeline` and `BaseStep` gets this structure
automatically.

### 9.2 Add extra instrumentation from an extension

The SDK instruments the common runtime automatically, but an extension can add
extra OpenTelemetry instruments for its own integrations.

The SDK does not add this extra instrumentation automatically. It is opt-in
at the extension level.

For example, to instrument `boto3`, add the dependency in the extension
environment and bootstrap it from the extension startup wiring, typically in
the same `app.py` module where `ExtensionApp` is created:

```python
from mpt_extension_sdk import ExtensionApp
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor

ext_app = ExtensionApp(
    prefix="/api/v2",
    version="1.0.0",
    openapi="/bypass/openapi.json",
)

BotocoreInstrumentor().instrument()
```

If we want to centralize more extension-specific instrumentation in the future,
the natural place is the extension app wiring layer, not handlers, pipelines,
or steps.

This should not live inside handlers, pipelines, or steps. Business logic
should stay free of tracing code.

### 9.3 Effective environment variables

The current observability-related settings are:

| Variable                                    | Required | Purpose                                                   |
|---------------------------------------------|----------|-----------------------------------------------------------|
| `SDK_OBSERVABILITY_ENABLED`                 | No       | Enables or disables SDK observability bootstrap           |
| `SDK_APPLICATIONINSIGHTS_CONNECTION_STRING` | No       | Enables Azure Monitor export when set                     |
| `SDK_OTEL_SERVICE_NAME`                     | No       | Overrides the OpenTelemetry service name                  |
| `OTEL_EXPORTER_OTLP_ENDPOINT`               | No       | Configures the OTLP exporter endpoint                     |
| `OTEL_EXPORTER_OTLP_PROTOCOL`               | No       | Configures the OTLP protocol, for example `http/protobuf` |


## 10. Run extension

### 10.1 Run the extension locally

```shell
swoext run --local
```

### 10.2 Run the extension in the Marketplace

```shell
swoext run
```

### 10.3 CLI status

Current SDK CLI commands:

- `swoext meta generate`
- `swoext run --local`
- `swoext run`
- `swoext validate`

`swoext init` is still TBD and is not implemented in the current SDK CLI.
