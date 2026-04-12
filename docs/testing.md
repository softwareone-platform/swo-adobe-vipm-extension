# Testing

Shared unit-test rules live in [unittests.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/unittests.md).

Shared build and target knowledge also applies:

- [knowledge/build-and-checks.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/knowledge/build-and-checks.md)
- [knowledge/make-targets.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/knowledge/make-targets.md)

This file documents repository-specific testing behavior.

## Test Scope

The repository currently has stable coverage in these areas:

- extension registration and startup checks in [`tests/test_apps.py`](../tests/test_apps.py) and [`tests/test_extension.py`](../tests/test_extension.py)
- Adobe client and configuration behavior in [`tests/adobe/`](../tests/adobe)
- Airtable model behavior in [`tests/airtable/`](../tests/airtable)
- fulfillment, validation, sync, migration, Marketplace, NAV, and helper flows in [`tests/flows/`](../tests/flows)
- management commands in [`tests/management/commands/`](../tests/management/commands)
- notification and utility helpers in [`tests/test_notifications.py`](../tests/test_notifications.py) and [`tests/test_utils.py`](../tests/test_utils.py)

## Commands

Use the repository make targets:

```bash
make test
make check
make check-all
```

Repository command mapping:

- `make test` runs `pytest`
- `make check` runs `ruff format --check`, `ruff check`, `flake8`, and `uv lock --check`
- `make check-all` runs both checks and tests

The CI workflow in [`.github/workflows/pr-build-merge.yml`](../.github/workflows/pr-build-merge.yml) uses the same `make build` and `make check-all` flow.

## Pytest Configuration

Repository-specific test settings come from [`pyproject.toml`](../pyproject.toml):

- tests are discovered under `tests`
- `pythonpath` includes the repository root
- coverage is collected for `adobe_vipm`
- `DJANGO_SETTINGS_MODULE` is `tests.django.settings`
- tests run with `--import-mode=importlib`

## Writing Tests

Repository-specific guidance:

- prefer existing fixtures from [`tests/conftest.py`](../tests/conftest.py) and domain-specific `conftest.py` files under `tests/`
- add or update tests next to the affected domain area instead of creating catch-all test files
- keep external service calls mocked; do not make live Adobe, Marketplace, Airtable, NAV, or notification calls in tests
- cover action-specific behavior in the matching fulfillment or validation test module when changing those flows
- cover command behavior in [`tests/management/commands/`](../tests/management/commands) when changing scheduled or operational commands

## When Tests Are Required

Add or update tests when a change modifies:

- extension startup or webhook handling
- validation behavior
- fulfillment behavior
- synchronization behavior
- management command behavior
- Airtable, NAV, or notification integration logic

If a change only affects documentation, tests are not required.
