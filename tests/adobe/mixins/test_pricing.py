from urllib.parse import urljoin

import pytest
from responses import matchers

from adobe_vipm.adobe.constants import PriceListCurrency, PriceListRegion, PriceListType
from adobe_vipm.adobe.dataclasses import PriceListFilters, PriceListPayload
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import MarketSegment


@pytest.fixture
def price_list_payload():
    return PriceListPayload(
        region=PriceListRegion.NA,
        market_segment=MarketSegment.COMMERCIAL,
        currency=PriceListCurrency.USD,
        price_list_month="202601",
    )


@pytest.fixture
def price_list_offer_factory():
    def _factory(offer_id, partner_price, estimated_street_price):
        return {
            "offerId": offer_id,
            "productFamily": "ADBSTD",
            "partnerPrice": partner_price,
            "estimatedStreetPrice": estimated_street_price,
        }

    return _factory


@pytest.fixture
def price_list_page_factory():
    def _factory(offers, total_count, offset, limit=100):
        return {
            "priceListMonth": "202601",
            "marketSegment": "COM",
            "region": "NA",
            "currency": "USD",
            "priceListType": "STANDARD",
            "totalCount": total_count,
            "count": len(offers),
            "limit": limit,
            "offset": offset,
            "offers": offers,
        }

    return _factory


def test_get_price_list_single_page(
    adobe_client_factory,
    requests_mocker,
    settings,
    price_list_payload,
    price_list_offer_factory,
    price_list_page_factory,
):
    client, authorization, api_token = adobe_client_factory()
    offer = price_list_offer_factory("65304578CA01A12", "123.45", "150.00")
    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/pricelist"),
        status=200,
        json=price_list_page_factory([offer], total_count=1, offset=0),
        match=[
            matchers.json_params_matcher(price_list_payload.to_dict()),
            matchers.query_param_matcher({"offset": "0", "limit": "100"}),
            matchers.header_matcher({
                "X-Api-Key": authorization.client_id,
                "Authorization": f"Bearer {api_token.token}",
            }),
        ],
    )

    result = client.get_price_list(
        authorization=authorization,
        payload=price_list_payload,
    )

    assert result["offers"] == [offer]
    assert len(requests_mocker.calls) == 1


def test_get_price_list_with_optional_params(
    adobe_client_factory,
    requests_mocker,
    settings,
    price_list_offer_factory,
    price_list_page_factory,
):
    client, authorization, _ = adobe_client_factory()
    payload = PriceListPayload(
        region=PriceListRegion.WE,
        market_segment=MarketSegment.EDUCATION,
        currency=PriceListCurrency.EUR,
        price_list_month="202602",
        price_list_type=PriceListType.THREE_YC,
        filters=PriceListFilters(offer_id="65304578CA01A12"),
        include_offer_attributes=["partnerPrice"],
    )
    offer = price_list_offer_factory("65304578CA01A12", "123.45", "150.00")
    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/pricelist"),
        status=200,
        json=price_list_page_factory([offer], total_count=1, offset=0),
        match=[matchers.json_params_matcher(payload.to_dict())],
    )

    result = client.get_price_list(authorization=authorization, payload=payload)

    assert result["offers"] == [offer]


def test_get_price_list_multiple_pages(
    adobe_client_factory,
    requests_mocker,
    settings,
    price_list_payload,
    price_list_offer_factory,
    price_list_page_factory,
):
    client, authorization, _ = adobe_client_factory()
    offer_1 = price_list_offer_factory("65304578CA01A12", "123.45", "150.00")
    offer_2 = price_list_offer_factory("65304578CA02A12", "234.56", "280.00")
    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/pricelist"),
        status=200,
        json=price_list_page_factory([offer_1], total_count=2, offset=0, limit=1),
        match=[
            matchers.json_params_matcher(price_list_payload.to_dict()),
            matchers.query_param_matcher({"offset": "0", "limit": "1"}),
        ],
    )
    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/pricelist"),
        status=200,
        json=price_list_page_factory([offer_2], total_count=2, offset=1, limit=1),
        match=[
            matchers.json_params_matcher(price_list_payload.to_dict()),
            matchers.query_param_matcher({"offset": "1", "limit": "1"}),
        ],
    )

    result = client.get_price_list(
        authorization=authorization,
        payload=price_list_payload,
        page_size=1,
    )

    assert result["offers"] == [offer_1, offer_2]
    assert len(requests_mocker.calls) == 2


def test_get_price_list_empty(
    adobe_client_factory,
    requests_mocker,
    settings,
    price_list_payload,
    price_list_page_factory,
):
    client, authorization, _ = adobe_client_factory()
    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/pricelist"),
        status=200,
        json=price_list_page_factory([], total_count=0, offset=0),
        match=[
            matchers.json_params_matcher(price_list_payload.to_dict()),
            matchers.query_param_matcher({"offset": "0", "limit": "100"}),
        ],
    )

    result = client.get_price_list(
        authorization=authorization,
        payload=price_list_payload,
    )

    assert result["offers"] == []
    assert len(requests_mocker.calls) == 1


def test_get_price_list_not_found(
    adobe_client_factory,
    requests_mocker,
    settings,
    price_list_payload,
    adobe_api_error_factory,
):
    client, authorization, _ = adobe_client_factory()
    requests_mocker.post(
        urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/pricelist"),
        status=404,
        json=adobe_api_error_factory("1162", "Price List not found"),
        match=[matchers.json_params_matcher(price_list_payload.to_dict())],
    )

    with pytest.raises(AdobeAPIError) as exc_info:
        client.get_price_list(
            authorization=authorization,
            payload=price_list_payload,
        )

    assert exc_info.value.code == "1162"
