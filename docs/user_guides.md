# Creating a New Extension with SDK v6

## 1. Initialize Extension

```shell
swo-ext init my-extension
```

This generates the base structure.

```text
my-extension/
  app.py
  meta.yaml
  pipelines/
     __init__.py
     steps/
       __init__.py
```

## 2. Define metadata (`meta.yaml`)

In the first version, meta.yaml supports only the version, openapi, and events.
Schedules, deferrables, plugs, and webhooks are not included in the initial scope.

Example:

```yaml
version: 1.0.0
openapi: /bypass/openapi.json
events:
  - event: platform.commerce.order.status_changed
    path: /api/v2/events/orders/purchase
    condition: "and(in(product.id,{{ settings.PRODUCT_IDS }}),eq(type,Purchase))"
    task: true
  - event: platform.commerce.order.created
    path: /api/v2/events/orders/termination
    condition: "and(in(product.id,{{ settings.PRODUCT_IDS }}),eq(type,Termination))"
    task: false
```

### 2.1 Choose between `task` and `non-task` events
- Use `task: true` when the platform must track the outcome of the processing.
- Use `task: false` when the platform does not need to track the outcome of the processing.
- `task: true` handlers return EventResponse.
- `task: false` handlers return 204 No Content on success.


## 3. Register routes

```python
@router.post("/api/v2/events/orders/purchase", response_model=EventResponse)
async def purchase_orders(event: TaskEvent) -> EventResponse:
    ctx = ExecutionContext.from_event(event)
    pipeline = PurchaseOrderPipeline()
    await pipeline.execute(ctx)
    return EventResponse.ok()
```

```python
@router.post("/api/v2/events/orders/termination", status_code=204)
async def termination_orders(event: Event) -> None:
    ctx = ExecutionContext.from_event(event)
    pipeline = TerminationOrderPipeline()
    await pipeline.execute(ctx)
```



## 4. Build a pipeline

Use stateless idempotent pipelines.

```python
class OrderPipeline(BasePipeline):
    @override
    def steps(self) -> list[Step]:
        return [ValidateOrderStep(), SubmitVendorOrderStep(), CompleteOrderStep()]
```

## 5. Implement steps with `pre/process/post`

```python
class ValidateOrderStep(BaseStep):
    async def pre(self, ctx):
        pass

    async def process(self, ctx):
        if not ctx.payload:
            raise CancelError("Invalid order payload")

    async def post(self, ctx):
        pass
```

## 6. Use `MPTAPIService` (not raw client)

Business logic should use `ctx.mpt_api_service` services.

```python
order = await ctx.mpt_api_service.orders.get(order_id)
await ctx.mpt_api_service.orders.mark_querying(order.id)
```

The SDK uses `mpt-api-python-client` internally.

## 7. Error mapping model

The SDK is responsible for mapping errors to the appropriate EventResponse. The following exceptions
are handled automatically:
RuntimeError: (it's automatically )
- ConfigError

PipelineError:
- CancelError
- DeferError
- FailError

StepError:
- SkipStepError: the pipeline continues with the next step
- StopStepError: the pipeline stops and returns CancelError
- DeferStepError: the pipeline stops and returns DeferError

As a developer you only should be worried about raise the StepErrors in the steps: SkipStepError, FailedStepError.

Use SkipStepError when the step should be skipped
Use FailedStepError when the pipeline should stop. It returns a Cancel EventResponse.
Use `DeferError` when third-party status is pending.

You can also inherit from one of the to create a granulate error handling is needed

```python
class OrderFailedStopStepError(StopStepError): ...
```

> Non-task events do not use OK / Defer / Cancel. So, the pipeline will return 204 No Content.

## 8. Configure observability

Enable OpenTelemetry adapters by configuration.

```env
OTEL_INSTRUMENTATIONS=fastapi,requests,boto3
```

Use correlation ids from the execution context for logs and tracing.


## 9. Run locally

```shell
swo-ext run
```

## Open topics

 * how to register the adapter
 * How to add a span or traces in Opentelemetry
 * How to add context to the logs
 * How to test
