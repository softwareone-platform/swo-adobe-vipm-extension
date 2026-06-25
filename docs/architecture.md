# Architecture

This document describes the structure, major components, boundaries, and layer
responsibilities of `swo-adobe-vipm-extension`. For configuration, local setup,
external systems, testing, and migrations, see the documents linked below.

## Purpose

`swo-adobe-vipm-extension` is a SoftwareOne Marketplace Platform (MPT) extension
for the Adobe VIP Marketplace program. It fulfils and validates Adobe orders
(purchase, change, transfer, reseller transfer, termination, configuration),
synchronises agreements, subscriptions, and pricing from Adobe, manages
three-year commitments (3YC), and runs reseller/transfer operational jobs.

It is built on the MPT Extension SDK and runs as the registered `swo.mpt.ext`
extension (`pyproject.toml` `[project.entry-points."swo.mpt.ext"]` ->
`adobe_vipm.apps:ExtensionConfig`).

## Entry points

- `adobe_vipm/apps.py` — Django `ExtensionConfig` (SDK `DjAppConfig`).
- `adobe_vipm/extension.py` — registers the SDK hooks:
  - order fulfilment event listener (`orders`) -> `fulfill_order(client, order)`
  - order validation endpoint (`POST /v1/orders/validate`) -> `validate_order(client, order)`
- `adobe_vipm/management/commands/` — Django management commands run by the
  worker (see Management commands).

## Layers

1. **Entry layer** (`extension.py`) — receives order events and validation requests.
2. **Fulfilment** (`flows/fulfillment/`) — `fulfill_order()` in `base.py` routes by
   order type to `purchase.py`, `change.py`, `transfer.py`, `reseller_transfer.py`,
   `termination.py`, and `configuration.py`; `shared.py` holds common utilities.
3. **Validation** (`flows/validation/`) — `validate_order()` in `base.py` routes to
   per-type validators (`purchase.py`, `change.py`, `transfer.py`, `termination.py`).
4. **Sync** (`flows/sync/`) — Adobe-to-MPT synchronisation for `agreement.py`,
   `subscription.py`, and `asset.py`, with `price_manager.py` for pricing.
5. **Integration clients** — the Adobe client (`adobe/`), Airtable (`airtable/`),
   and notification helpers (`notifications.py`) wrap external systems.

## Major components

| Package / module | Responsibility |
|---|---|
| `adobe_vipm/flows/` | Order fulfilment, validation, and sync orchestration |
| `adobe_vipm/adobe/client.py` + `adobe/mixins/` | Adobe VIPM API client (customer, order, subscription, transfer, deployment, reseller mixins) |
| `adobe_vipm/adobe/config.py` | `Config` singleton: authorizations, resellers, countries |
| `adobe_vipm/airtable/models.py` | `pyairtable` models for migration, pricing, and SKU-mapping data |
| `adobe_vipm/notifications.py` | Microsoft Teams alerts (Adaptive Cards via `requests`) and MPT notifications (Jinja2 templates) |
| `adobe_vipm/management/commands/` | Worker commands for transfers, 3YC, resellers, and sync |

## Management commands

Run by the worker (locally via `make run` + the Django management interface, and
in deployment as worker jobs / CronJobs):

- `create_resellers` — create resellers in Adobe VIP Marketplace from an Excel file
- `process_transfers`, `check_running_transfers` — process and monitor agreement transfers
- `process_3yc`, `sync_3yc_enrol`, `process_3yc_expiration_notifications` — three-year-commitment lifecycle and expiration notifications
- `sync_agreements` — synchronise agreements from Adobe to MPT
- `check_gc_agreement_deployments` — verify global-customer agreement deployments

## External integrations

Adobe VIPM API (`adobe/`), Airtable (`airtable/`), the MPT API (via the SDK),
Microsoft Teams, NAV, and AWS SES email. See
[external-integrations.md](external-integrations.md) for purpose, auth, and
configuration of each.

## Boundaries

- External systems are reached only through their client module (`adobe/`,
  `airtable/`, `notifications.py`); flows depend on those clients, not raw HTTP.
- Configuration is read through Django settings / `EXTENSION_CONFIG`, not from the
  environment directly inside business logic. Adobe credentials and
  authorizations are loaded from mounted JSON files (see
  [deployment.md](deployment.md)).

## Deployment shape

Deployed from `helm/swo-extension-adobe` as an **api** workload (webhooks and the
validation endpoint), a **worker** workload, and **CronJobs** for the management
commands. The container image is built from the multi-stage `Dockerfile` and
started via `swoext run`. See [deployment.md](deployment.md) for configuration.

## Related documentation

- [local-development.md](local-development.md) — local setup and run
- [contributing.md](contributing.md) — development workflow and commands
- [testing.md](testing.md) — test strategy and execution
- [deployment.md](deployment.md) — configuration and deployment model
- [external-integrations.md](external-integrations.md) — external systems
- [migrations.md](migrations.md) — migration workflow
