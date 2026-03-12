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
- Use typed exceptions and a fixed SDK mapper for `OK / Defer / Cancel`.
- Keep observability outside business logic with middleware and SDK instrumentation adapters.
- SDK owns notification orchestration; extensions register notifier plugins.
- The first version scope includes only events.
- Preserve domain logic in extensions but rewrite framework/wiring layers.

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

### 3) Event registration with extension-level `meta.yaml`
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
We chose **declarative `meta.yaml`**, validated by schema and registered automatically at startup.

#### Why
It gives a simple, consistent interface for all extension teams.

### 4) Generic endpoint vs explicit route per order type
#### Options considered
1. Use a generic endpoint for everything and dispatch internally based on the order type and the event type. Example: `/api/v2/events/orders`
2. Use an explicit endpoint per order type. Example: `/api/v2/events/orders/purchase`, `/api/v2/events/orders/termination`

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

#### Why
It gives consistent behavior and avoids generic error handling in each extension.

### 8) Step model with hooks and typed errors
#### Final decision
Adopt a standard step lifecycle and error taxonomy:
- Lifecycle: `pre()`, `process()`, `post()`
- Errors: `SkipStepError`, `CancelError`, `ConfigError`, `FailError`, `DeferError`

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

#### Why
It removes telemetry logic from business code and supports specific adapters like `boto3`.

### 10) Notification model
#### Options considered
1. SDK owns notification orchestration; extensions register notifier plugins.
2. Extension owns orchestration and directly uses notifier implementations.
3. Hybrid (SDK default notifier + optional extension override hooks).

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
We chose the **SDK-orchestrated** notification model.

#### Why
This keeps notification consistent across all extensions while still allowing extension teams to customize
channels and message formatting by registering notifier implementations.
SDK owns the orchestration, so the notifications are outside the business logic.

### 11) First version scope
#### Final decision
The first version includes only event handling, covering both task-based and non-task event delivery.

#### Why
This scope is enough to implement a real flow and test the solution is working without spending too much time adding the business logic.

### 12) Keep vs. rebuild in extension repositories
#### Final decision
- Keep: domain services, vendor clients, business rules.
- Rebuild: runtime entrypoints, framework wiring, error mapping layer, observability wiring.

#### Why
This gives high value with controlled implementation risk.

## Pending Decisions

### A) Migration strategy across repositories
We intentionally deferred the adoption strategy (gradual vs. big-bang).
The architecture must be final first; then rollout can be selected.

### B) Scope for next version.
We defer the decision on the scope of the next version. It can include:
- Validation/webhook endpoints
- Schedules and deferrable jobs
- Plugs
