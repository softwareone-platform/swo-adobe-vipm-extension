from collections import defaultdict
from datetime import date

from requests import HTTPError

from adobe_vipm.flows.airtable import (
    AirTableBaseInfo,
    create_offers,
    get_offer_ids_by_membership_id,
    get_offer_model,
    get_pricelist_model,
    get_prices_for_3yc_skus,
    get_prices_for_skus,
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

    base_info = AirTableBaseInfo.for_migrations("PRD-1111")

    assert base_info.api_key == api_key
    assert base_info.base_id == base_id


def test_get_transfer_model():
    base_info = AirTableBaseInfo(api_key="api-key", base_id="base-id")
    Transfer = get_transfer_model(base_info)
    assert Transfer.get_api().api_key == base_info.api_key
    assert Transfer.get_base().id == base_info.base_id


def test_get_offer_model():
    base_info = AirTableBaseInfo(api_key="api-key", base_id="base-id")
    Offer = get_offer_model(base_info)
    assert Offer.get_api().api_key == base_info.api_key
    assert Offer.get_base().id == base_info.base_id


def test_get_offer_ids_by_membership_id(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_offer_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.airtable.get_offer_model",
        return_value=mocked_offer_model,
    )

    mocked_offer = mocker.MagicMock(offer_id="offer-id")

    mocked_offer_model.all.return_value = [mocked_offer]

    offer_ids = get_offer_ids_by_membership_id("product_id", "member_id")

    assert offer_ids == ["offer-id"]
    mocked_offer_model.all.assert_called_once_with(
        formula="{membership_id}='member_id'"
    )


def test_create_offers(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_offer = mocker.MagicMock()
    mocked_transfer = mocker.MagicMock()
    mocked_offer_model = mocker.MagicMock(return_value=mocked_offer)
    mocker.patch(
        "adobe_vipm.flows.airtable.get_offer_model",
        return_value=mocked_offer_model,
    )

    offers = [
        {
            "transfer": [mocked_transfer],
            "offer_id": "offer-id",
            "quantity": 234,
            "renewal_date": date(2022, 11, 23),
        }
    ]

    create_offers("product_id", offers)

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
        "adobe_vipm.flows.airtable.get_transfer_model",
        return_value=mocked_transfer_model,
    )

    mocked_transfer = mocker.MagicMock()
    mocked_transfer_model.all.return_value = [mocked_transfer]

    transfer_to_process = get_transfers_to_process("product_id")

    assert transfer_to_process == [mocked_transfer]
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
        "adobe_vipm.flows.airtable.get_transfer_model",
        return_value=mocked_transfer_model,
    )

    mocked_transfer = mocker.MagicMock()
    mocked_transfer_model.all.return_value = [mocked_transfer]

    transfer_to_process = get_transfers_to_check("product_id")

    assert transfer_to_process == [mocked_transfer]
    mocked_transfer_model.all.assert_called_once_with(
        formula="{status}='running'",
    )


def test_get_transfer_by_authorization_membership_or_customer(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"product_id": "base_id"},
    }
    mocked_transfer_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.airtable.get_transfer_model",
        return_value=mocked_transfer_model,
    )

    mocked_transfer = mocker.MagicMock()
    mocked_transfer_model.all.return_value = [mocked_transfer]

    transfer = get_transfer_by_authorization_membership_or_customer(
        "product_id",
        "authorization_uk",
        "membership_id",
    )

    assert transfer == mocked_transfer

    mocked_transfer_model.all.assert_called_once_with(
        formula=(
            "AND({authorization_uk}='authorization_uk',"
            "OR({membership_id}='membership_id',{customer_id}='membership_id'),"
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

    assert (
        get_transfer_link(transfer)
        == "https://airtable.com/base-id/table-id/view-id/record-id"
    )


def test_get_transfer_link_exception(mocker):
    transfer = mocker.MagicMock()
    transfer.get_table.side_effect = HTTPError()

    assert get_transfer_link(transfer) is None


def test_airtable_base_info_for_pricing(settings):
    api_key = "airtable-token"
    base_id = "pricing-base-id"
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": api_key,
        "AIRTABLE_PRICING_BASES": {"PRD-1111": "pricing-base-id"},
    }

    base_info = AirTableBaseInfo.for_pricing("PRD-1111")

    assert base_info.api_key == api_key
    assert base_info.base_id == base_id


def test_get_pricelist_model():
    base_info = AirTableBaseInfo(api_key="api-key", base_id="base-id")
    PriceList = get_pricelist_model(base_info)
    assert PriceList.get_api().api_key == base_info.api_key
    assert PriceList.get_base().id == base_info.base_id


def test_get_prices_for_skus(mocker, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_PRICING_BASES": {"product_id": "base_id"},
    }
    mocked_pricelist_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.airtable.get_pricelist_model",
        return_value=mocked_pricelist_model,
    )
    price_item_1 = mocker.MagicMock()
    price_item_1.sku = "sku-1"
    price_item_1.unit_pp = 12.44
    price_item_2 = mocker.MagicMock()
    price_item_2.sku = "sku-2"
    price_item_2.unit_pp = 31.23
    mocked_pricelist_model.all.return_value = [price_item_1, price_item_2]

    prices = get_prices_for_skus("product_id", "currency", ["sku-1", "sku-2"])

    assert prices == {
        "sku-1": 12.44,
        "sku-2": 31.23,
    }

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
        "adobe_vipm.flows.airtable.get_pricelist_model",
        return_value=mocked_pricelist_model,
    )
    price_item_1 = mocker.MagicMock()
    price_item_1.sku = "sku-1"
    price_item_1.currency = "currency"
    price_item_1.valid_from = date.fromisoformat("2024-01-01")
    price_item_1.valid_until = date.fromisoformat("2025-01-01")
    price_item_1.unit_pp = 12.44
    price_item_2 = mocker.MagicMock()
    price_item_2.sku = "sku-2"
    price_item_2.currency = "currency"
    price_item_2.valid_from = date.fromisoformat("2024-01-01")
    price_item_2.valid_until = None
    price_item_2.unit_pp = 31.23
    price_item_3 = mocker.MagicMock()
    price_item_3.sku = "sku-1"
    price_item_3.unit_pp = 43.10
    price_item_3.currency = "currency"
    price_item_3.valid_from = date.fromisoformat("2024-01-01")
    price_item_3.valid_until = None
    mocked_pricelist_model.all.return_value = [price_item_1, price_item_2, price_item_3]

    prices = get_prices_for_3yc_skus(
        "product_id",
        "currency",
        date.fromisoformat("2024-03-03"),
        ["sku-1", "sku-2"],
    )

    assert prices == {
        "sku-1": 12.44,
        "sku-2": 31.23,
    }

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


def test_get_prices_for_3yc_skus_hit_cache(
    mocker, settings, mock_pricelist_cache_factory
):
    cache = defaultdict(list)
    cache["sku-1"].append(
        {
            "currency": "currency",
            "valid_from": date.fromisoformat("2024-01-01"),
            "valid_until": date.fromisoformat("2025-01-01"),
            "unit_pp": 12.44,
        }
    )
    mock_pricelist_cache_factory(cache=cache)
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_PRICING_BASES": {"product_id": "base_id"},
    }
    mocked_pricelist_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.airtable.get_pricelist_model",
        return_value=mocked_pricelist_model,
    )
    price_item_2 = mocker.MagicMock()
    price_item_2.sku = "sku-2"
    price_item_2.currency = "currency"
    price_item_2.valid_from = date.fromisoformat("2024-01-01")
    price_item_2.valid_until = None
    price_item_2.unit_pp = 31.23
    mocked_pricelist_model.all.return_value = [price_item_2]

    prices = get_prices_for_3yc_skus(
        "product_id",
        "currency",
        date.fromisoformat("2024-03-03"),
        ["sku-1", "sku-2"],
    )

    assert prices == {
        "sku-1": 12.44,
        "sku-2": 31.23,
    }

    mocked_pricelist_model.all.assert_called_once_with(
        formula=(
            "AND({currency}='currency',"
            "OR({valid_until}=BLANK(),AND({valid_from}<='2024-03-03',{valid_until}>'2024-03-03')),"
            "OR({sku}='sku-2'))"
        ),
        sort=["-valid_until"],
    )


def test_get_prices_for_3yc_skus_just_cache(
    mocker, settings, mock_pricelist_cache_factory
):
    cache = defaultdict(list)
    cache["sku-1"].append(
        {
            "currency": "currency",
            "valid_from": date.fromisoformat("2024-01-01"),
            "valid_until": date.fromisoformat("2025-01-01"),
            "unit_pp": 12.44,
        }
    )
    mock_pricelist_cache_factory(cache=cache)
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_PRICING_BASES": {"product_id": "base_id"},
    }
    mocked_pricelist_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.airtable.get_pricelist_model",
        return_value=mocked_pricelist_model,
    )

    prices = get_prices_for_3yc_skus(
        "product_id",
        "currency",
        date.fromisoformat("2024-03-03"),
        ["sku-1"],
    )

    assert prices == {
        "sku-1": 12.44,
    }

    mocked_pricelist_model.all.assert_not_called()
