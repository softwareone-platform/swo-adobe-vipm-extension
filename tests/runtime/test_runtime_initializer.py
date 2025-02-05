import json

import pytest
from swo.mpt.extensions.runtime.initializer import get_extension_variables


def test_get_extension_variables(monkeypatch):
    webhook_secret = '{ "webhook_secret": "WEBHOOK_SECRET" }'
    airtable_base = '{ "airtable_base": "AIRTABLE_BASE" }'
    airtable_pricing_base = '{ "airtable_pricing_base": "AIRTABLE_PRICING_BASE" }'
    product_segment = '{ "product_segment": "PRODUCT_SEGMENT" }'
    email_sender = "email_sender"

    monkeypatch.setenv("EXT_WEBHOOKS_SECRETS", webhook_secret)
    monkeypatch.setenv("EXT_AIRTABLE_BASES", airtable_base)
    monkeypatch.setenv("EXT_AIRTABLE_PRICING_BASES", airtable_pricing_base)
    monkeypatch.setenv("EXT_PRODUCT_SEGMENT", product_segment)
    monkeypatch.setenv("EXT_EMAIL_NOTIFICATIONS_SENDER", email_sender)

    extension_variables = get_extension_variables()

    assert extension_variables is not None
    assert extension_variables["WEBHOOKS_SECRETS"] == json.loads(webhook_secret)
    assert extension_variables["AIRTABLE_BASES"] == json.loads(airtable_base)
    assert extension_variables["AIRTABLE_PRICING_BASES"] == json.loads(
        airtable_pricing_base
    )
    assert extension_variables["PRODUCT_SEGMENT"] == json.loads(product_segment)
    assert extension_variables["EMAIL_NOTIFICATIONS_SENDER"] == email_sender


def test_get_extension_variables_json_error(monkeypatch):
    webhook_secret = '{ "webhook_secret": "WEBHOOK_SECRET" }'
    airtable_base = '{ "airtable_base": "AIRTABLE_BASE" }'
    airtable_pricing_base = '{ "airtable_pricing_base": "AIRTABLE_PRICING_BASE" }'

    monkeypatch.setenv("EXT_WEBHOOKS_SECRETS", webhook_secret)
    monkeypatch.setenv("EXT_AIRTABLE_BASES", airtable_base)
    monkeypatch.setenv("EXT_AIRTABLE_PRICING_BASES", airtable_pricing_base)
    monkeypatch.setenv(
        "EXT_PRODUCT_SEGMENT", '{ "field_1": , , "field2": "very bad json"}'
    )

    with pytest.raises(Exception) as e:
        get_extension_variables()

    assert "Variable EXT_PRODUCT_SEGMENT not well formatted" in str(e.value)
