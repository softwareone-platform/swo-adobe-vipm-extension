# ADR-001: Introduce SDK v6 for MPT Extensions

## Status
Pending

## Date
2026-03-10

## Context

Today MPT Extensions are built using the `mpt-extension-sdk`, which relies on a
runtime based on **Django/Ninja**.

A new runtime based on **mrok** is now available.
This runtime allows extensions to run using **FastAPI** and **OpenZiti (Ziticorn)**,
providing a simpler and more secure execution model. A new MPT Extension Service has been
added to support event registration and orchestration.

The goal is to allow extension teams to focus on **business logic and configuration**,
while the SDK handles infrastructure concerns.

SDK v6 is intended to become the **standard framework for all MPT Extensions**.


## Decision Summary
- Build a new SDK v6 without backward compatibility.
- Use FastAPI/Uvicorn for local development and Ziticorn for production runtime.
- Configure events in each Extension with `meta.yaml`.
- Use an official business model based on stateless idempotent pipelines.
- Use typed exceptions and a fixed SDK mapper for `OK / Reschedule / Cancel`.
- Keep observability outside business logic with middleware and SDK instrumentation adapters.
- Keep notification orchestration in the extension layer; the SDK only provides lifecycle hooks and service extension points.
- The first version scope includes only events.
- Preserve domain logic in extensions but rewrite framework/wiring layers.
- Settings are split into three layers (SDK, extension, account), each with its own lifecycle and future provider strategy.
- SDK injects `ExecutionContext` into handlers via the route factory.

The SDK is responsible for:
- event registration
- pipelines orchestration
- error handling
- observability
- logging
- configuration
- provides the MPT API Client Service
- provides common models and schemas

The SDK is NOT responsible for:
- business logic
- vendor integrations


## Accepted Decisions

### 1) New SDK v6 without backward compatibility

#### Options considered
1. Keep compatibility with the old SDK.
2. Create a new SDK v6 without the compatibility layer.

#### Pros and cons
- Keep compatibility
  - Pros: lower short-term migration effort.
  - Cons: old framework constraints stay in the new design.
- New v6 only
  - Pros: clean architecture and lower long-term maintenance.
  - Cons: migration effort in each extension.

#### Final decision
We chose **new SDK v6 without backward compatibility**.

#### Why
We want a clean foundation, and we do not want to carry legacy design limits.

### 2) Runtime model: FastAPI local + Ziticorn production
#### Options considered
1. Ziticorn for all environments.
2. FastAPI/Uvicorn local and Ziticorn in production.

#### Pros and cons
- Ziticorn
  - Pros: only one runtime to manage.
  - Cons: hard to debug and requires extra infrastructure (Ziti network) for local development.
- FastAPI local + Ziticorn production
  - Pros: easy local development without local dependencies,  production aligned with mrok/OpenZiti.
  - Cons: two run modes to support.

#### Final decision
We chose **FastAPI/Uvicorn local + Ziticorn production**.

#### Why
It balances developer experience with platform integration requirements. It allows mocking the
external dependencies for local development.

### 3) Event registration with extension-level generated `meta.yaml`
#### Options considered
1. Hardcode events in Python code.
2. Use a declarative `meta.yaml` file with schema validation.
3. Build an advanced DSL.

#### Pros and cons
- Hardcoded events
  - Pros: direct implementation.
  - Cons: harder to review and maintain across many extensions.
- Declarative YAML
  - Pros: clear, versionable, and easier to validate.
  - Cons: less expressive than a custom DSL.
- Advanced DSL
  - Pros: powerful and flexible.
  - Cons: harder debugging and higher maintenance cost.

#### Final decision
We chose **declarative metadata in Python**, materialized as a generated `meta.yaml`,
validated by schema and registered automatically at startup.

#### Why
It keeps event metadata close to the handlers while preserving a stable
`meta.yaml` artifact for registration and review.

### 4) Generic endpoint vs explicit route per order type
#### Options considered
1. Use a generic endpoint for everything and dispatch internally based on the order type and the event type. Example: `/api/v2/events/orders`
2. Use an explicit endpoint per route/flow. Example: `/api/v2/events/orders/purchase`, `/api/v2/events/orders/change`

#### Pros and cons
- Generic endpoint
  - Pros: fewer routes to define, less wiring, easier to centralize shared preprocessing.
  - Cons: event semantics are hidden in the payload, routing logic grows with conditionals, weaker observability
- Explicit endpoint per order type
  - Pros: clearer external contract, better traceability, easier testing, simpler route-to-pipeline mapping, and better long-term evolvability.
  - Cons: more route definitions, slightly more boilerplate, and shared logic must be extracted into reusable helpers.

#### Final decision
We chose **explicit endpoint per order type**.

#### Why
It allows defining a clear contract for each order type. The endpoint is more explicit and easier to understand.


### 5) Official business flow model: stateless idempotent pipeline
#### Options considered
1. Typed pipeline/steps.
2. Handler-only model.
3. Workflow engine.

#### Pros and cons
- Typed pipeline/steps
  - Pros: reusable steps and easier migration from current repos.
  - Cons: extra abstraction.
- Handler-only
  - Pros: simpler start.
  - Cons: repeated cross-cutting logic in many handlers.
- Workflow engine
  - Pros: explicit long-running state machine.
  - Cons: too heavy for MVP.

#### Final decision
We chose **pipeline as the official model**, specifically **stateless idempotent pipeline**.
Each pipeline execution must be safe to retry without side effects.
Steps must be designed to be idempotent.

Pipeline business logic also treats Marketplace models as immutable snapshots.
Writers must persist changes through the Marketplace service layer and refresh the
order only when later logic depends on the canonical post-write state.

#### Why
Current extensions already use pipelines a lot, and this model is the lowest-risk migration path.


### 6) Third-party waiting policy: Defer immediate
#### Options considered
1. Return `Defer` immediately when external state is pending.
2. Store the state in an external database.
3. Add mandatory persisted checkpoints.

#### Pros and cons
- Defer immediate
  - Pros: simple and clear in task-based flows.
  - Cons: next attempt reruns the pipeline.
- Store state in an external database
  - Pros: the extension keeps explicit control over the long-running state
  - Cons: it adds infrastructure complexity and operational overhead.
- Mandatory checkpoints
  - Pros: it allows resuming from the last successful step
  - Cons: introduces storage and consistency complexity

#### Final decision
We chose **Defer immediate** with strict idempotent step behavior.

#### Why
It keeps the SDK simple and reliable.

### 7) Error model: exceptions + fixed SDK mapper
#### Options considered
1. Exceptions with central mapper.
2. Result pattern.
3. Hybrid.

#### Pros and cons
- Exceptions + mapper
  - Pros: natural in Python/FastAPI and clean domain code.
  - Cons: needs strict taxonomy and good guidelines.
- Result pattern
  - Pros: explicit return contracts.
  - Cons: more verbose in Python.
- Hybrid
  - Pros: flexible.
  - Cons: mixed patterns and harder standards.

#### Final decision
We chose **exceptions + fixed mapper in SDK**.

The mapper translates pipeline exceptions to `EventResponse` as follows:

| Exception           | EventResponse | Reason                            |
|---------------------|---------------|-----------------------------------|
| `CancelError`       | `Cancel`      | reason from the exception message |
| `DeferError`        | `Reschedule`  | delay from the exception          |
| `FailError`         | `Cancel`      | reason from the exception message |
| `ExtRuntimeError`   | `Cancel`      | `"Runtime error"`                 |
| Any other exception | `Cancel`      | `"Unexpected error"`              |

The mapper is fixed at the SDK level and cannot be overridden by extensions.
`FailError` and unexpected exceptions are always logged before mapping.

#### Why
It gives consistent behavior and avoids generic error handling in each extension.

### 8) Step model with hooks and typed errors
#### Final decision
Adopt a standard step lifecycle and error taxonomy:
- Lifecycle: `pre()`, `process()`, `post()`
- Step errors (handled by the pipeline runner):
  - `SkipStepError` → pipeline continues with the next step
  - `StopStepError` → pipeline stops and raises `CancelError`
  - `DeferStepError` → pipeline stops and raises `DeferError`

For steps that perform order-related writes, the SDK provides an explicit refresh
mechanism:
- `OrderContext.refresh_order()`
- `@refresh_order`

The decorator is not a default for every step. It is meant for read-after-write
cases where later code in the same pipeline needs the refreshed Marketplace
order graph.

#### Why
This makes pipeline behavior predictable and testable.

### 9) Observability outside business logic
#### Options considered
1. Middleware + SDK instrumentation.
2. Sidecar-only strategy.
3. Mixed strategy in MVP.

#### Pros and cons
- Middleware + SDK instrumentation
  - Pros: clean separation and easy local testing.
  - Cons: still needs exporter policy by environment.
- Sidecar-only
  - Pros: strong operational separation.
  - Cons: extra infrastructure burden for all teams.
- Mixed
  - Pros: flexible.
  - Cons: additional complexity.

#### Final decision
We chose **middleware + SDK instrumentation adapters**.

The SDK injects the following fields into every log record automatically:

| Field            | Source                                           |
|------------------|--------------------------------------------------|
| `task_id`        | `MPT-Task-Id` request header                     |
| `{objectType}`   | `event.object.object_type` and `event.object.id` |


#### Why
It removes telemetry logic from business code and supports specific adapters like `boto3`.

### 10) Notification model
#### Options considered
1. SDK owns notification orchestration.
2. Extension owns orchestration and directly uses notifier implementations.
3. Hybrid (SDK default hooks + optional extension-specific notification implementations).

#### Pros and cons
- SDK-orchestrated
  - Pros: consistent behavior across extensions, centralized rules, simpler extension code.
  - Cons: less flexibility for extension-specific flows.
- Extension-orchestrated
  - Pros: maximum flexibility for domain-specific notification timing and routing.
  - Cons: duplicated logic, inconsistent behavior, higher maintenance and testing cost.
- Hybrid
  - Pros: balance of consistency and flexibility.
  - Cons: higher complexity, unclear ownership boundaries, harder governance.

#### Final decision
We chose the **extension-orchestrated** notification model for the current iteration.

#### Why
Notification timing and payloads are business-flow concerns and already differ between
extensions. The SDK should stay neutral and expose lifecycle hooks plus an extensible
Marketplace service container, but it should not prescribe when or how an extension sends
notifications.

### 11) First version scope
#### Final decision
The first version includes only event handling, covering both task-based and non-task event delivery.

The following are explicitly deferred to a future version:
- Webhook endpoints
- Schedules and deferrable jobs
- Plugs
- `swoext init` scaffold command
- Additional CLI surface beyond `swoext run`

#### Why
This scope is enough to implement a real flow and test the solution is working without spending too much time adding the business logic.

### 12) Keep vs. rebuild in extension repositories
#### Final decision
- Keep: domain services, vendor clients, business rules.
- Rebuild: runtime entrypoints, framework wiring, error mapping layer, observability wiring.

#### Why
This gives high value with controlled implementation risk.


### 13) Configuration model (settings)

#### Context

There are three distinct categories emerged with different lifecycles, ownership, and future management needs:

| Layer              | Examples                                          | Scope          | Future management                  |
|--------------------|---------------------------------------------------|----------------|------------------------------------|
| SDK settings       | `SDK_EXTENSION_URL`, `MPT_API_BASE_URL`, etc.     | Infrastructure | Always env vars                    |
| Extension settings | Adobe API credentials, Airtable tokens, etc.      | Extension-wide | could be env vars or UI + database |
| Account settings   | Per-customer credentials, account-level overrides | Per-account    | could be env vars or UI + database |

Settings are today loaded from environment variables, but they are expected to be managed via a management UI and stored in an
external store in the future.

#### Options considered

1. Keep everything in environment variables permanently.
2. Three-layer model with autodiscovery: the SDK derives the root package from SDK_HANDLERS_MODULES,
   imports <root>.settings, and instantiates the class named ExtensionSettings that subclasses
   BaseExtensionSettings. No registration required.
3. Three-layer model with swappable provider contracts: the SDK defines Protocol types (ExtensionSettingsProvider,
   AccountSettingsProvider). Extensions register any callable that satisfies the contract. The SDK calls providers
   per-request and injects results into ExecutionContext.

#### Pros and cons

- Everything in env vars
  - Pros: no abstraction needed today, simpler bootstrapping.
  - Cons: hard to migrate when a UI/database is introduced; no seam for injection in tests.
- Autodiscovery
  - Pros: zero boilerplate — the extension only defines the class, no registration needed.
  - Cons: the SDK is coupled to a specific file name, class name, and load() classmethod convention; any deviation raises ConfigError;
    AccountSettings cannot be expressed through autodiscovery because it requires event data at request time, not a static load() call.
- Provider contracts
  - Pros: explicit boundaries, decoupled from the loading mechanism, testable with any callable (including lambdas for tests), natural
    support for per-request AccountSettings via acc_provider(event), no convention imposed on the extension's file structure.
  - Cons: extensions must register their providers explicitly at startup.

#### Final decision

We chose **three-layer model with autodiscovery** for the first iteration.

>TBD — This is a first-iteration decision. The autodiscovery approach is in place and working.
> In a future iteration, we will design how to manage account and extension settings via a UI,
> define where to store them, and revisit whether the provider/protocol approach is needed
> to support those storage backends without SDK changes. The provider pattern remains the
> likely target for that iteration.

#### Why
This is a simple approach to implement. Account settings management and the question of non-env-var
storage backends are deferred — there is no value in designing the full provider mechanism before
those requirements are concrete. The current convention
is explicit enough to document and enforce at startup via ConfigError,
and it keeps extension boilerplate minimal for the teams adopting the new SDK


### 14) `Context` injected by SDK route factory
#### Options considered
1. Handler constructs `Context` manually.
2. SDK route factory builds and injects `Context`.

#### Pros and cons
- Manual construction
  - Pros: explicit, handler controls the context.
  - Cons: boilerplate repeated in every handler; tight coupling to `MPTAPIService` construction.
- SDK injection
  - Pros: zero boilerplate in handlers, consistent context across all events.
  - Cons: handler has less visibility into context construction.

#### Final decision
We chose **SDK route factory injects `Context`**.

#### Why
It removes infrastructure boilerplate from every handler and ensures consistent context
construction across all extensions.


### 15) Observability and tracing model (OpenTelemetry)
#### Options considered
1. Context manager-based / decorator-based instrumentation at the runtime level.
2. Internal hooking / middleware wrapping execution units.

#### Pros and cons
- Context manager-based / decorator-based
  - Pros: explicit instrumentation points and easy ad-hoc customization in specific code paths.
  - Cons: observability concerns leak into business code and require discipline from every extension team.
- Internal hooking / middleware wrapping execution units
  - Pros: clean separation from business logic, consistent instrumentation across handlers, pipelines, and steps.
  - Cons: less direct visibility into instrumentation boundaries when reading the business code.


#### Final decision
We chose **internal hooking / middleware wrapping execution units**.

Tracing is initialized by the SDK and applied around the runtime and pipeline
execution lifecycle. Extensions do not need to add context managers or
decorators to handlers, pipelines, or steps to participate in the standard
observability model.

#### Why
This keeps tracing concerns out of business logic while still giving the SDK a
single place to instrument request handling, pipeline execution, and common
integrations consistently.


### 16) Fail-fast validation (`meta.yaml` generated from routes)
#### Options considered
1. Log a warning and continue if generated metadata and `meta.yaml` are inconsistent.
2. Raise `ConfigError` and abort startup.

#### Final decision
We chose **fail-fast validation via CLI and startup metadata generation**.

The SDK derives metadata directly from `ExtensionApp` and route decorators at
startup. The checked-in `meta.yaml` must be regenerated from the same source of
truth and `swoext validate` must fail if the file does not match.

#### Why
Silent inconsistencies cause runtime failures that are hard to diagnose. A
generated artifact plus fail-fast validation makes misconfiguration visible
immediately.


## Pending Decisions

### A) Migration strategy across repositories
We intentionally deferred the adoption strategy (gradual vs. big-bang).
The architecture must be final first; then rollout can be selected.

### B) Scope for the next version
We defer the decision on the scope of the next version. It can include:
- Validation/webhook endpoints
- Schedules and deferrable jobs
- Plugs
