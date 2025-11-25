import datetime as dt
from collections import defaultdict

import pytest
from requests import HTTPError

from adobe_vipm.adobe.errors import AdobeProductNotFoundError
from adobe_vipm.airtable.models import (
    AirTableBaseInfo,
    create_gc_agreement_deployments,
    create_gc_main_agreement,
    create_offers,
    get_adobe_product_by_marketplace_sku,
    get_agreement_deployment_view_link,
    get_gc_agreement_deployment_model,
    get_gc_agreement_deployments_by_main_agreement,
    get_gc_agreement_deployments_to_check,
    get_gc_main_agreement,
    get_gc_main_agreement_model,
    get_offer_ids_by_membership_id,
    get_offer_model,
    get_pricelist_model,
    get_prices_for_3yc_skus,
    get_prices_for_skus,
    get_sku_adobe_mapping_model,
    get_transfer_by_authorization_membership_or_customer,
    get_transfer_link,
    get_transfer_model,
    get_transfers_to_check,
    get_transfers_to_process,
)


def test_airtable_base_info_for_migrations(settings):
    api_key = "airtable-token"
    base_id = "base-id"
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": api_key,
        "AIRTABLE_BASES": {"PRD-1111": "base-id"},
    }

    result = AirTableBaseInfo.for_migrations("PRD-1111")

    assert result.api_key == api_key
    assert result.base_id == base_id


def test_get_transfer_model():
    base_info = AirTableBaseInfo(api_key="api-key", base_id="base-id")

    result = get_transfer_model(base_info)

    assert result.get_api().api_key == base_info.api_key
    assert result.get_base().id == base_info.base_id


def test_get_offer_model():
    base_info = AirTableBaseInfo(api_key="api-key", base_id="base-id")

    result = get_offer_model(base_info)

    assert result.get_api().api_key == base_info.api_key
    assert result.get_base().id == base_info.base_id


def test_get_offer_ids_by_membership_id(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_offer_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_offer_model",
        return_value=mocked_offer_model,
    )
    mocked_offer = mocker.MagicMock(offer_id="offer-id")
    mocked_offer_model.all.return_value = [mocked_offer]

    result = get_offer_ids_by_membership_id("product_id", "member_id")

    assert result == ["offer-id"]
    mocked_offer_model.all.assert_called_once_with(formula="{membership_id}='member_id'")


def test_create_offers(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_offer = mocker.MagicMock()
    mocked_transfer = mocker.MagicMock()
    mocked_offer_model = mocker.MagicMock(return_value=mocked_offer)
    mocker.patch(
        "adobe_vipm.airtable.models.get_offer_model",
        return_value=mocked_offer_model,
    )
    offers = [
        {
            "transfer": [mocked_transfer],
            "offer_id": "offer-id",
            "quantity": 234,
            "renewal_date": dt.date(2022, 11, 23),
        }
    ]

    create_offers("product_id", offers)  # act

    mocked_offer_model.batch_save.assert_called_once_with([mocked_offer])
    mocked_offer_model.assert_called_once_with(
        transfer=[mocked_transfer],
        offer_id=offers[0]["offer_id"],
        quantity=offers[0]["quantity"],
        renewal_date=offers[0]["renewal_date"],
    )


def test_get_transfers_to_process(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_transfer_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_transfer_model",
        return_value=mocked_transfer_model,
    )
    mocked_transfer = mocker.MagicMock()
    mocked_transfer_model.all.return_value = [mocked_transfer]

    result = get_transfers_to_process("product_id")

    assert result == [mocked_transfer]
    mocked_transfer_model.all.assert_called_once_with(
        formula="OR({status}='init',{status}='rescheduled')",
    )


def test_get_transfers_to_check(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_transfer_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_transfer_model", return_value=mocked_transfer_model
    )
    mocked_transfer = mocker.MagicMock()
    mocked_transfer_model.all.return_value = [mocked_transfer]

    result = get_transfers_to_check("product_id")

    assert result == [mocked_transfer]
    mocked_transfer_model.all.assert_called_once_with(formula="{status}='running'")


def test_get_transfer_by_authorization_membership_or_customer(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_transfer_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_transfer_model", return_value=mocked_transfer_model
    )
    mocked_transfer = mocker.MagicMock()
    mocked_transfer_model.all.return_value = [mocked_transfer]

    result = get_transfer_by_authorization_membership_or_customer(
        "product_id", "authorization_uk", "membership_id"
    )

    assert result == mocked_transfer
    mocked_transfer_model.all.assert_called_once_with(
        formula=(
            "AND({authorization_uk}='authorization_uk',"
            "OR(LOWER({membership_id})=LOWER('membership_id'),{customer_id}='membership_id'),"
            "{status}!='duplicated')"
        ),
    )


def test_get_transfer_link(mocker):
    transfer = mocker.MagicMock()
    transfer.id = "record-id"
    transfer.Meta.base_id = "base-id"
    view_mock = mocker.MagicMock()
    view_mock.id = "view-id"
    schema_mock = mocker.MagicMock()
    schema_mock.view.return_value = view_mock
    table_mock = mocker.MagicMock()
    table_mock.id = "table-id"
    table_mock.schema.return_value = schema_mock
    transfer.get_table.return_value = table_mock

    result = get_transfer_link(transfer)

    assert result == "https://airtable.com/base-id/table-id/view-id/record-id"


def test_get_transfer_link_exception(mocker):
    transfer = mocker.MagicMock()
    transfer.get_table.side_effect = HTTPError()

    result = get_transfer_link(transfer)

    assert result is None


def test_airtable_base_info_for_pricing(settings):
    api_key = "airtable-token"
    base_id = "pricing-base-id"
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": api_key,
        "AIRTABLE_PRICING_BASES": {"PRD-1111": "pricing-base-id"},
    }

    result = AirTableBaseInfo.for_pricing("PRD-1111")

    assert result.api_key == api_key
    assert result.base_id == base_id


def test_get_pricelist_model():
    base_info = AirTableBaseInfo(api_key="api-key", base_id="base-id")

    result = get_pricelist_model(base_info)

    assert result.get_api().api_key == base_info.api_key
    assert result.get_base().id == base_info.base_id


def test_get_prices_for_skus(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_PRICING_BASES": {"product_id": "base_id"},
    }
    mocked_pricelist_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_pricelist_model",
        return_value=mocked_pricelist_model,
    )
    price_item_1 = mocker.MagicMock()
    price_item_1.sku = "sku-1"
    price_item_1.unit_pp = 12.44
    price_item_2 = mocker.MagicMock()
    price_item_2.sku = "sku-2"
    price_item_2.unit_pp = 31.23
    mocked_pricelist_model.all.return_value = [price_item_1, price_item_2]

    result = get_prices_for_skus("product_id", "currency", ["sku-1", "sku-2"])

    assert result == {"sku-1": 12.44, "sku-2": 31.23}
    mocked_pricelist_model.all.assert_called_once_with(
        formula=(
            "AND({currency}='currency',{valid_until}=BLANK(),OR({sku}='sku-1',{sku}='sku-2'))"
        ),
    )


def test_get_prices_for_3yc_skus(mocker, settings, mocked_pricelist_cache):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_PRICING_BASES": {"product_id": "base_id"},
    }
    mocked_pricelist_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_pricelist_model",
        return_value=mocked_pricelist_model,
    )
    price_item_1 = mocker.MagicMock()
    price_item_1.sku = "sku-1"
    price_item_1.currency = "currency"
    price_item_1.valid_from = dt.date.fromisoformat("2024-01-01")
    price_item_1.valid_until = dt.date.fromisoformat("2025-01-01")
    price_item_1.unit_pp = 12.44
    price_item_2 = mocker.MagicMock()
    price_item_2.sku = "sku-2"
    price_item_2.currency = "currency"
    price_item_2.valid_from = dt.date.fromisoformat("2024-01-01")
    price_item_2.valid_until = None
    price_item_2.unit_pp = 31.23
    price_item_3 = mocker.MagicMock()
    price_item_3.sku = "sku-1"
    price_item_3.unit_pp = 43.10
    price_item_3.currency = "currency"
    price_item_3.valid_from = dt.date.fromisoformat("2024-01-01")
    price_item_3.valid_until = None
    mocked_pricelist_model.all.return_value = [price_item_1, price_item_2, price_item_3]

    result = get_prices_for_3yc_skus(
        "product_id",
        "currency",
        dt.date.fromisoformat("2024-03-03"),
        ["sku-1", "sku-2"],
    )

    assert result == {"sku-1": 12.44, "sku-2": 31.23}
    mocked_pricelist_model.all.assert_called_once_with(
        formula=(
            "AND({currency}='currency',"
            "OR({valid_until}=BLANK(),AND({valid_from}<='2024-03-03',{valid_until}>'2024-03-03')),"
            "OR({sku}='sku-1',{sku}='sku-2'))"
        ),
        sort=["-valid_until"],
    )
    assert mocked_pricelist_cache == {
        "sku-1": [
            {
                "currency": price_item_1.currency,
                "valid_from": price_item_1.valid_from,
                "valid_until": price_item_1.valid_until,
                "unit_pp": price_item_1.unit_pp,
            }
        ],
        "sku-2": [],
    }


def test_get_prices_for_3yc_skus_hit_cache(mocker, settings, mock_pricelist_cache_factory):
    cache = defaultdict(list)
    cache["sku-1"].append({
        "currency": "currency",
        "valid_from": dt.date.fromisoformat("2024-01-01"),
        "valid_until": dt.date.fromisoformat("2025-01-01"),
        "unit_pp": 12.44,
    })
    mock_pricelist_cache_factory(cache=cache)
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_PRICING_BASES": {"product_id": "base_id"},
    }
    mocked_pricelist_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_pricelist_model",
        return_value=mocked_pricelist_model,
    )
    price_item_2 = mocker.MagicMock()
    price_item_2.sku = "sku-2"
    price_item_2.currency = "currency"
    price_item_2.valid_from = dt.date.fromisoformat("2024-01-01")
    price_item_2.valid_until = None
    price_item_2.unit_pp = 31.23
    mocked_pricelist_model.all.return_value = [price_item_2]

    result = get_prices_for_3yc_skus(
        "product_id",
        "currency",
        dt.date.fromisoformat("2024-03-03"),
        ["sku-1", "sku-2"],
    )

    assert result == {"sku-1": 12.44, "sku-2": 31.23}
    mocked_pricelist_model.all.assert_called_once_with(
        formula=(
            "AND({currency}='currency',"
            "OR({valid_until}=BLANK(),AND({valid_from}<='2024-03-03',{valid_until}>'2024-03-03')),"
            "OR({sku}='sku-2'))"
        ),
        sort=["-valid_until"],
    )


def test_get_prices_for_3yc_skus_just_cache(mocker, settings, mock_pricelist_cache_factory):
    cache = defaultdict(list)
    cache["sku-1"].append({
        "currency": "currency",
        "valid_from": dt.date.fromisoformat("2024-01-01"),
        "valid_until": dt.date.fromisoformat("2025-01-01"),
        "unit_pp": 12.44,
    })
    mock_pricelist_cache_factory(cache=cache)
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_PRICING_BASES": {"product_id": "base_id"},
    }
    mocked_pricelist_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_pricelist_model",
        return_value=mocked_pricelist_model,
    )

    result = get_prices_for_3yc_skus(
        "product_id",
        "currency",
        dt.date.fromisoformat("2024-03-03"),
        ["sku-1"],
    )

    assert result == {"sku-1": 12.44}
    mocked_pricelist_model.all.assert_not_called()


def test_get_gc_main_agreement_model():
    base_info = AirTableBaseInfo(api_key="api-key", base_id="base-id")

    result = get_gc_main_agreement_model(base_info)

    assert result.get_api().api_key == base_info.api_key
    assert result.get_base().id == base_info.base_id


def test_get_gc_agreement_deployment_model():
    base_info = AirTableBaseInfo(api_key="api-key", base_id="base-id")

    result = get_gc_agreement_deployment_model(base_info)

    assert result.get_api().api_key == base_info.api_key
    assert result.get_base().id == base_info.base_id


def test_create_gc_agreement_deployments(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_gc_agreement_deployment = mocker.MagicMock()
    mocked_gc_agreement_deployment_model = mocker.MagicMock(
        return_value=mocked_gc_agreement_deployment
    )
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployment_model,
    )
    agreement_deployment = [
        {
            "deployment_id": "deployment_id",
            "status": "pending",
            "customer_id": "customer_id",
            "product_id": "product_id",
            "main_agreement_id": "main_agreement_id",
            "account_id": "account_id",
            "seller_id": "seller_id",
            "membership_id": "membership_id",
            "transfer_id": "transfer_id",
            "deployment_currency": "USD",
            "deployment_country": "US",
            "licensee_id": "licensee_id",
            "agreement_id": "agreement_id",
            "authorization_id": "authorization_id",
            "price_list_id": "price_list_id",
            "listing_id": "listing_id",
            "error_description": "error_description",
        }
    ]

    create_gc_agreement_deployments("product_id", agreement_deployment)  # act

    mocked_gc_agreement_deployment_model.batch_save.assert_called_once_with([
        mocked_gc_agreement_deployment
    ])
    mocked_gc_agreement_deployment_model.assert_called_once_with(
        deployment_id=agreement_deployment[0]["deployment_id"],
        status=agreement_deployment[0]["status"],
        customer_id=agreement_deployment[0]["customer_id"],
        product_id=agreement_deployment[0]["product_id"],
        main_agreement_id=agreement_deployment[0]["main_agreement_id"],
        account_id=agreement_deployment[0]["account_id"],
        seller_id=agreement_deployment[0]["seller_id"],
        membership_id=agreement_deployment[0]["membership_id"],
        transfer_id=agreement_deployment[0]["transfer_id"],
        deployment_currency=agreement_deployment[0]["deployment_currency"],
        deployment_country=agreement_deployment[0]["deployment_country"],
        licensee_id=agreement_deployment[0]["licensee_id"],
        agreement_id=agreement_deployment[0]["agreement_id"],
        authorization_id=agreement_deployment[0]["authorization_id"],
        price_list_id=agreement_deployment[0]["price_list_id"],
        listing_id=agreement_deployment[0]["listing_id"],
        error_description=agreement_deployment[0]["error_description"],
    )


def test_create_gc_main_agreement(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_get_gc_main_agreement_model = mocker.MagicMock(return_value=mocked_gc_main_agreement)
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_main_agreement_model",
        return_value=mocked_get_gc_main_agreement_model,
    )
    main_agreement = {
        "membership_id": "membership_id",
        "authorization_uk": "authorization_uk",
        "main_agreement_id": "main_agreement_id",
        "transfer_id": "transfer_id",
        "customer_id": "customer_id",
        "status": "pending",
        "error_description": "error_description",
    }

    create_gc_main_agreement("product_id", main_agreement)  # act

    mocked_gc_main_agreement.save.assert_called_once()
    mocked_get_gc_main_agreement_model.assert_called_once_with(
        membership_id=main_agreement["membership_id"],
        authorization_uk=main_agreement["authorization_uk"],
        main_agreement_id=main_agreement["main_agreement_id"],
        transfer_id=main_agreement["transfer_id"],
        customer_id=main_agreement["customer_id"],
        status=main_agreement["status"],
        error_description=main_agreement["error_description"],
    )


def test_get_gc_main_agreement(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_gc_main_agreement_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_main_agreement_model",
        return_value=mocked_gc_main_agreement_model,
    )
    mocked_gc_main_agreement = mocker.MagicMock()
    mocked_gc_main_agreement_model.all.return_value = [mocked_gc_main_agreement]

    result = get_gc_main_agreement("product_id", "authorization_uk", "main_agreement_id")

    assert result == mocked_gc_main_agreement
    mocked_gc_main_agreement_model.all.assert_called_once_with(
        formula="AND({authorization_uk}='authorization_uk',OR({membership_id}='main_agreement_id',"
        "{customer_id}='main_agreement_id'))",
    )


def test_get_gc_main_agreement_empty_response(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_gc_main_agreement_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_main_agreement_model",
        return_value=mocked_gc_main_agreement_model,
    )
    mocked_gc_main_agreement_model.all.return_value = []

    result = get_gc_main_agreement("product_id", "authorization_uk", "main_agreement_id")

    assert result is None
    mocked_gc_main_agreement_model.all.assert_called_once_with(
        formula="AND({authorization_uk}='authorization_uk',OR({membership_id}='main_agreement_id',"
        "{customer_id}='main_agreement_id'))",
    )


def test_get_gc_agreement_deployments_by_main_agreement(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_gc_agreement_deployments_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    gc_agreement_deployments = mocker.MagicMock()
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    result = get_gc_agreement_deployments_by_main_agreement("product_id", "main_agreement_id")

    assert result == [gc_agreement_deployments]
    mocked_gc_agreement_deployments_model.all.assert_called_once_with(
        formula="AND({main_agreement_id}='main_agreement_id')",
    )


def test_get_gc_agreement_deployments_to_check(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_gc_agreement_deployments_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    gc_agreement_deployments = mocker.MagicMock()
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    result = get_gc_agreement_deployments_to_check("product_id")

    assert result == [gc_agreement_deployments]
    mocked_gc_agreement_deployments_model.all.assert_called_once_with(
        formula="OR({status}='pending',{status}='error')",
    )


def test_get_agreement_deployment_view_link(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_gc_agreement_deployments_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    mocked_gc_agreement_deployments_model.id = "record-id"
    mocked_gc_agreement_deployments_model.Meta.base_id = "base-id"
    view_mock = mocker.MagicMock()
    view_mock.id = "view-id"
    schema_mock = mocker.MagicMock()
    schema_mock.view.return_value = view_mock
    table_mock = mocker.MagicMock()
    table_mock.id = "table-id"
    table_mock.schema.return_value = schema_mock
    mocked_gc_agreement_deployments_model.get_table.return_value = table_mock

    result = get_agreement_deployment_view_link("product_id")

    assert result == "https://airtable.com/base-id/table-id/view-id/record-id"


def test_get_agreement_deployment_view_link_exception(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_gc_agreement_deployments_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    mocked_gc_agreement_deployments_model.get_table.side_effect = HTTPError()

    result = get_agreement_deployment_view_link("product_id")

    assert result is None


def test_get_sku_adobe_mapping_model():
    base_info = AirTableBaseInfo(api_key="api-key", base_id="base-id")

    result = get_sku_adobe_mapping_model(base_info)

    assert result.get_api().api_key == base_info.api_key
    assert result.get_base().id == base_info.base_id


# FIX: it has multiple act blocks
def test_get_adobe_product_by_marketplace_sku(mocker, mock_get_sku_adobe_mapping_model):  # noqa: AAA02
    base_info = AirTableBaseInfo(api_key="api-key", base_id="base-id")
    mocker.patch(
        "adobe_vipm.airtable.models.AirTableBaseInfo.for_sku_mapping",
        return_value=base_info,
    )
    mocker.patch(
        "adobe_vipm.airtable.models.get_sku_adobe_mapping_model",
        return_value=mock_get_sku_adobe_mapping_model,
    )

    with pytest.raises(AdobeProductNotFoundError):
        get_adobe_product_by_marketplace_sku("vendor_external_id")

    result = get_adobe_product_by_marketplace_sku("65304578CA")

    assert result.vendor_external_id == "65304578CA"
    assert result.sku == "65304578CA01A12"
    assert not result.is_consumable()
    assert result.is_license()
    assert result.is_valid_3yc_type()
