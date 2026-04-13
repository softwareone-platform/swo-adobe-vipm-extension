# Contributing

This document captures repository-specific contribution guidance.

Shared engineering rules live in `mpt-extension-skills` and should not be duplicated here:

- documentation standard: [documentation.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/documentation.md)
- makefile structure: [makefiles.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/makefiles.md)
- commit message rules: [commit-messages.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/commit-messages.md)
- dependency management: [packages-and-dependencies.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/packages-and-dependencies.md)
- extension design guidance: [extensions-best-practices.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/extensions-best-practices.md)
- pull request rules: [pull-requests.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/pull-requests.md)
- Python coding conventions: [python-coding.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/standards/python-coding.md)

Shared operational knowledge also applies:

- build and validation flow: [knowledge/build-and-checks.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/knowledge/build-and-checks.md)
- common make target meanings: [knowledge/make-targets.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/knowledge/make-targets.md)

## Development Model

The default development model for this repository is Docker-based.

- Use `make build` to build the local image and install dependencies.
- Use `make run` to start the service through Docker Compose.
- Use `make bash` or `make shell` when you need an interactive container session.

## Code Organization Expectations

Repository-specific expectations:

- keep extension entry-point changes close to [`adobe_vipm/extension.py`](../adobe_vipm/extension.py) and [`adobe_vipm/apps.py`](../adobe_vipm/apps.py)
- keep business behavior under the relevant domain directory in [`adobe_vipm/flows/`](../adobe_vipm/flows)
- keep operational command logic in [`adobe_vipm/management/commands/`](../adobe_vipm/management/commands)
- keep tests under [`tests/`](../tests), mirroring production structure where practical
- update documentation in the matching file under [`docs/`](.) when runtime, testing, or setup behavior changes

## Validation Before Review

Use the repository command entry points before review:

```bash
make check
make test
```

Use `make check-all` when you want the combined workflow.

See [testing.md](testing.md) for repository-specific testing expectations.

## Documentation Changes

Documentation rules live in [documentation.md](documentation.md).

When changing docs, update the smallest relevant file instead of duplicating policy across multiple documents.
