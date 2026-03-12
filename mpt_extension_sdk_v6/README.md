# MPT Extension SDK v6

PoC SDK package for SWO extensions using the v6 architecture.

## Current PoC scope

- Runtime app assembly from metadata + decorated business handlers
- Instance registration with identity persistence
- Event contracts (`task`/`non-task`) and error mapping
- Pipeline primitives and Marketplace service layer
- CLI command: `swo-ext run [--local]`

## Usage

```bash
uv run swoext run --local
uv run swoext run
```

## Deferred for next iteration

- CLI commands: `register`, `validate`, `init`
- Test hardening and full quality gate coverage
