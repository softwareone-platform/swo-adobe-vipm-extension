import uuid

import pytest


@pytest.fixture()
def flex_discounts_factory():
    def _flex_discounts():
        return {
            "limit": 20,
            "offset": 0,
            "count": 1,
            "totalCount": 1,
            "flexDiscounts": [
                {
                    "id": "55555555-8768-4e8a-9a2f-fb6a6b08f561",
                    "name": "Black Friday Flexible Discount - FAILURE - Country",
                    "description": "Exclusive 22% off on Adobe Technical Communication Suite and"
                    " Adobe Express for Teams",
                    "code": "BLACK_FRIDAY_22_FAILURE_3",
                    "startDate": "2025-03-12T10:00:48Z",
                    "endDate": "2026-03-07T10:16Z",
                    "status": "ACTIVE",
                    "qualification": {"baseOfferIds": ["65304768CA01A12"]},
                    "outcomes": [
                        {"type": "PERCENTAGE_DISCOUNT", "discountValues": [{"value": 22.0}]}
                    ],
                },
                {
                    "id": "55555555-8768-4e8a-9a2f-fb6a6b08f563",
                    "name": "Easter Flexible Discount",
                    "description": "Exclusive 26 fixed off on Adobe Technical Communication Suite",
                    "code": "EASTER_26",
                    "startDate": "2025-06-12T10:00:48Z",
                    "endDate": "2026-03-07T10:16Z",
                    "status": "ACTIVE",
                    "qualification": {"baseOfferIds": ["65304769CA01A12"]},
                    "outcomes": [
                        {
                            "type": "FIXED_DISCOUNT",
                            "discountValues": [{"country": "US", "currency": "USD", "value": 26.0}],
                        }
                    ],
                },
                {
                    "id": "55555555-8768-4e8a-9a2f-fb6a6b08f557",
                    "name": "Adobe All Flexible Discount",
                    "description": "Exclusive 20 fixed off on select products",
                    "code": "ADOBE_ALL_PROMOTION",
                    "startDate": "2025-03-12T10:00:48Z",
                    "endDate": "2026-03-07T10:16Z",
                    "status": "ACTIVE",
                    "qualification": {"baseOfferIds": ["65304770CA01A12"]},
                    "outcomes": [
                        {
                            "type": "FIXED_DISCOUNT",
                            "discountValues": [{"country": "US", "currency": "USD", "value": 20.0}],
                        }
                    ],
                },
            ],
            "links": {
                "self": {
                    "uri": "/v3/flex-discounts?market-segment=COM&country=US&offer-ids=65304768CA0",
                    "method": "GET",
                    "headers": [],
                }
            },
        }

    return _flex_discounts


@pytest.fixture()
def mock_uuid4(mocker):
    return mocker.patch(
        "adobe_vipm.adobe.client.uuid4",
        return_value=uuid.UUID("a21beee6-c07e-43e1-b5b7-fbef9644dbbb"),
    )
