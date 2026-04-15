# MPT Extension SDK v6

PoC SDK package for SWO extensions using the v6 architecture.

## Current PoC scope

- Runtime app assembly from `ExtensionApp` metadata + decorated business handlers
- Instance registration with identity persistence
- Event contracts (`task`/`non-task`) and error mapping
- Pipeline primitives and Marketplace service layer
- CLI commands: `swoext meta generate`, `swoext validate`, `swoext run`, and `swoext run --local`

## Usage

```bash
uv run swoext validate
uv run swoext run --local
uv run swoext run
```

`swoext run` and `swoext run --local` generate `meta.yaml` automatically before
starting the runtime. `swoext meta generate` remains available when you want to
materialize the artifact without starting the service.

## Deferred for next iteration

- CLI commands: `register`, `init`
- Test hardening and full quality gate coverage
