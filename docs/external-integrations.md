# External Integrations

This document lists the external systems the extension integrates with, their
purpose, and how they authenticate. The full environment-variable reference for
each integration lives in [deployment.md](deployment.md); this document is the
index and does not duplicate those tables.

## Integrations

| System | Purpose | Auth | Configuration | Code |
| --- | --- | --- | --- | --- |
| Adobe VIPM API | Order creation/preview, subscriptions, customers, resellers, transfers, deployments | OAuth 2.0 client credentials; credentials and authorizations loaded from mounted JSON files | `EXT_ADOBE_API_BASE_URL`, `EXT_ADOBE_AUTH_ENDPOINT_URL`, `EXT_ADOBE_CREDENTIALS_FILE`, `EXT_ADOBE_AUTHORIZATIONS_FILE` | [`adobe_vipm/adobe/client.py`](../adobe_vipm/adobe/client.py), [`adobe_vipm/adobe/config.py`](../adobe_vipm/adobe/config.py) |
| Airtable | Migration tracking, pricing tables, and SKU mapping | Personal Access Token | `EXT_AIRTABLE_API_TOKEN`, `EXT_AIRTABLE_BASES`, `EXT_AIRTABLE_PRICING_BASES`, `EXT_AIRTABLE_SKU_MAPPING_BASE` | [`adobe_vipm/airtable/models.py`](../adobe_vipm/airtable/models.py) |
| SoftwareOne Marketplace (MPT) API | Order polling, agreement/subscription updates, notifications | Bearer token (JWT) | `MPT_API_BASE_URL`, `MPT_API_TOKEN`, `MPT_PRODUCTS_IDS`, `MPT_NOTIFY_CATEGORIES` | provided by `mpt-extension-sdk` |
| Microsoft Teams | Operational alerts (warnings, errors, exceptions) | Incoming webhook | `EXT_MSTEAMS_WEBHOOK_URL` | [`adobe_vipm/notifications.py`](../adobe_vipm/notifications.py) |
| NAV | Customer/reseller validation against NAV | OAuth 2.0 client credentials | `EXT_NAV_API_BASE_URL`, `EXT_NAV_AUTH_ENDPOINT_URL`, `EXT_NAV_AUTH_AUDIENCE`, `EXT_NAV_AUTH_CLIENT_ID`, `EXT_NAV_AUTH_CLIENT_SECRET` | `adobe_vipm/flows/` |
| AWS SES | Email notifications when enabled | AWS credentials | `EXT_EMAIL_NOTIFICATIONS_ENABLED`, `EXT_EMAIL_NOTIFICATIONS_SENDER`, `EXT_AWS_SES_REGION`, `EXT_AWS_SES_CREDENTIALS` | `adobe_vipm/notifications.py` / flows |

## Notes

- Adobe credentials (`EXT_ADOBE_CREDENTIALS_FILE`) and authorizations
  (`EXT_ADOBE_AUTHORIZATIONS_FILE`) are JSON files that must stay consistent;
  their formats are documented in [deployment.md](deployment.md).
- Email notifications (AWS SES) are optional and only active when
  `EXT_EMAIL_NOTIFICATIONS_ENABLED` is set.
