# Migrations

Shared migration knowledge lives in:

- [knowledge/migrations.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/knowledge/migrations.md)
- [knowledge/make-targets.md](https://github.com/softwareone-platform/mpt-extension-skills/blob/main/knowledge/make-targets.md)

This file documents repository-specific migration behavior only.

## Migration Files

Repository migration scripts live in [`migrations/`](../migrations).

This repository uses the standard migration workflow and standard make-based command wiring used across related repositories. Use the shared migration knowledge above as the primary reference.

## Repository-Specific Constraint

Do not confuse two different concepts in this repository:

- [`migrations/`](../migrations) contains `mpt-service-cli` migration scripts
- [`adobe_vipm/flows/migration.py`](../adobe_vipm/flows/migration.py) contains business logic for transfer-processing and related operational flows

Changing transfer-processing logic does not automatically mean a new `mpt-service-cli` migration is required.

## When To Update This Document

Update this file when the repository changes:

- migration file locations
- migration command entry points
- required execution order
- rollout or safety constraints specific to this repository
