# External Integrations

This document lists the external systems the extension integrates with, their
purpose, and how they authenticate. The full environment-variable reference for
each integration lives in [deployment.md](deployment.md); this document is the
index and does not duplicate those tables.

## Integrations

| System | Purpose | Auth | Configuration | Code |
| --- | --- | --- | --- | --- |
| Adobe VIPM API | Order creation/preview, subscriptions, customers, resellers, transfers, deployments | OAuth 2.0 client credentials; credentials and authorizations loaded from mounted JSON files | `EXT_ADOBE_API_BASE_URL`, `EXT_ADOBE_AUTH_ENDPOINT_URL`, `EXT_ADOBE_CREDENTIALS_FILE`, `EXT_ADOBE_AUTHORIZATIONS_FILE` | [`adobe_vipm/adobe/client.py`](../adobe_vipm/adobe/client.py), [`adobe_vipm/adobe/config.py`](../adobe_vipm/adobe/config.py) |
| Airtable | Migration tracking, pricing tables, SKU mapping, and flex discount redemptions | Shared service-account token (workspace-scoped Airtable PAT, provisioned and rotated by DevOps) | `EXT_AIRTABLE_API_TOKEN`, `EXT_AIRTABLE_BASES`, `EXT_AIRTABLE_PRICING_BASES`, `EXT_AIRTABLE_SKU_MAPPING_BASE`, `EXT_AIRTABLE_DISCOUNTS_ID` | [`adobe_vipm/airtable/models.py`](../adobe_vipm/airtable/models.py) |
| SoftwareOne Marketplace (MPT) API | Order polling, agreement/subscription updates, notifications | Bearer token (JWT) | `MPT_API_BASE_URL`, `MPT_API_TOKEN`, `MPT_PRODUCTS_IDS`, `MPT_NOTIFY_CATEGORIES` | provided by `mpt-extension-sdk` |
| Microsoft Teams | Operational alerts (warnings, errors, exceptions) | Workflow webhook | `EXT_MSTEAMS_WEBHOOK_URL` | [`adobe_vipm/notifications.py`](../adobe_vipm/notifications.py) |
| NAV | Customer/reseller validation against NAV | OAuth 2.0 client credentials | `EXT_NAV_API_BASE_URL`, `EXT_NAV_AUTH_ENDPOINT_URL`, `EXT_NAV_AUTH_AUDIENCE`, `EXT_NAV_AUTH_CLIENT_ID`, `EXT_NAV_AUTH_CLIENT_SECRET` | `adobe_vipm/flows/` |
| AWS SES | Email notifications when enabled | AWS credentials | `EXT_EMAIL_NOTIFICATIONS_ENABLED`, `EXT_EMAIL_NOTIFICATIONS_SENDER`, `EXT_AWS_SES_REGION`, `EXT_AWS_SES_CREDENTIALS` | `adobe_vipm/notifications.py` / flows |

## Adobe error code mappings

The extension maps Adobe VIPM API error codes to VIPM validation errors:

| Adobe error code | Adobe meaning | VIPM error | VIPM message | Enforcement |
| --- | --- | --- | --- | --- |
| `2147` ([`AdobeErrorCode.FLEX_DISCOUNT_CODE_LIMIT_EXCEEDED`](../adobe_vipm/adobe/constants.py)) | Line item carries more than one flexible discount code | `VIPM0052` ([`ERR_FLEX_DISCOUNT_CODE_LIMIT`](../adobe_vipm/flows/constants.py)) | "Only one flexible discount code per line item is allowed" | Proactively enforced before submission in switch/renewal fulfillment; defensively mapped if Adobe rejects the order |

## Notes

- Adobe credentials (`EXT_ADOBE_CREDENTIALS_FILE`) and authorizations
  (`EXT_ADOBE_AUTHORIZATIONS_FILE`) are JSON files that must stay consistent;
  their formats are documented in [deployment.md](deployment.md).
- An Adobe call that fails before any HTTP response arrives (dropped connection,
  timeout) raises `AdobeTransportError`, which sits outside the `AdobeError`
  hierarchy on purpose so flows that fail an order on an Adobe business rejection
  do not fail it on a network fault. Fulfillment logs these as warnings and does
  not raise a Teams alert: the order stays in processing and is re-dispatched, and
  a run of failures that outlives the order due date fails the order through the
  normal due-date path.
- Email notifications (AWS SES) are optional and only active when
  `EXT_EMAIL_NOTIFICATIONS_ENABLED` is set.
