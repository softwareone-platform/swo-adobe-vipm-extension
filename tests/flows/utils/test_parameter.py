import json
from typing import Any

import pytest
from pytest_mock import MockerFixture

from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.utils.parameter import (
    get_flex_discounts_parameter,
    get_fulfillment_parameter,
    get_renewal_payload,
    get_switch_payload,
    set_flex_discounts_parameter,
    update_agreement_params_visibility,
)


@pytest.mark.parametrize(
    (
        "market_segment",
        "order_params",
        "fulfillment_params",
        "expected_visible",
    ),
    [
        (
            "COM",
            [
                {"externalId": Param.AGREEMENT_TYPE.value, "value": "New"},
                {"externalId": Param.COMPANY_NAME.value, "value": "Test Company"},
                {"externalId": Param.MEMBERSHIP_ID.value, "value": "M-123"},
                {
                    "externalId": Param.ADOBE_CUSTOMER_ADMIN_EMAIL.value,
                    "value": "adobe@example.com",
                },
                {"externalId": Param.CHANGE_RESELLER_CODE.value, "value": "R-123"},
                {"externalId": "hidden_param", "value": "hidden"},
            ],
            [
                {"externalId": Param.CUSTOMER_ID.value, "value": "C-123"},
                {"externalId": "another_hidden_param", "value": "hidden"},
            ],
            [
                Param.AGREEMENT_TYPE.value,
                Param.COMPANY_NAME.value,
                Param.CUSTOMER_ID.value,
            ],
        ),
        (
            "GOV_LGA",
            [
                {"externalId": Param.AGREEMENT_TYPE.value, "value": "Migrate"},
                {"externalId": Param.MEMBERSHIP_ID.value, "value": "M-123"},
                {"externalId": Param.AGENCY_TYPE.value, "value": "FEDERAL"},
                {
                    "externalId": Param.MARKET_SEGMENT_ELIGIBILITY_STATUS.value,
                    "value": "FEDERAL",
                    "constraints": {"hidden": False},
                },
            ],
            [],
            [
                Param.AGREEMENT_TYPE.value,
                Param.MEMBERSHIP_ID.value,
                Param.AGENCY_TYPE.value,
            ],
        ),
        (
            "COM",
            [
                {"externalId": Param.AGREEMENT_TYPE.value, "value": "Transfer"},
                {"externalId": Param.ADOBE_CUSTOMER_ADMIN_EMAIL.value, "value": "test@example.com"},
                {"externalId": Param.CHANGE_RESELLER_CODE.value, "value": "123456"},
            ],
            [],
            [
                Param.AGREEMENT_TYPE.value,
                Param.ADOBE_CUSTOMER_ADMIN_EMAIL.value,
                Param.CHANGE_RESELLER_CODE.value,
            ],
        ),
        (
            "EDU",
            [
                {"externalId": Param.AGREEMENT_TYPE.value, "value": "New"},
                {
                    "externalId": Param.MARKET_EDUCATION_SUB_SEGMENTS.value,
                    "value": "HIGHER_EDUCATION",
                },
            ],
            [],
            [
                Param.AGREEMENT_TYPE.value,
                Param.MARKET_EDUCATION_SUB_SEGMENTS.value,
            ],
        ),
    ],
)
def test_update_agreement_params_visibility(
    mocker: MockerFixture,
    order_factory: Any,
    market_segment: str,
    order_params: list[dict[str, Any]],
    fulfillment_params: list[dict[str, Any]],
    expected_visible: list[str],
) -> None:
    mocker.patch(
        "adobe_vipm.flows.utils.parameter.get_for_product",
        return_value=market_segment,
        autospec=True,
    )
    order = order_factory(
        order_parameters=order_params,
        fulfillment_parameters=fulfillment_params,
    )

    result = update_agreement_params_visibility(order)

    all_params = result["parameters"]["ordering"] + result["parameters"]["fulfillment"]
    for param in all_params:
        is_visible = param["externalId"] in expected_visible
        assert param["constraints"]["hidden"] is not is_visible


def test_get_switch_payload(order_factory, order_parameters_factory, switch_payload):
    order = order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(switch_payload=switch_payload),
    )

    result = get_switch_payload(order)  # act

    assert result == switch_payload


def test_get_switch_payload_json_string(order_factory, order_parameters_factory, switch_payload):
    order = order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(switch_payload=json.dumps(switch_payload)),
    )

    result = get_switch_payload(order)  # act

    assert result == switch_payload


def test_get_switch_payload_empty_string(order_factory, order_parameters_factory):
    order = order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(switch_payload=""),
    )

    result = get_switch_payload(order)  # act

    assert result is None


def test_get_switch_payload_not_set(order_factory):
    order = order_factory(order_type="Change")

    result = get_switch_payload(order)  # act

    assert result is None


def test_get_renewal_payload(order_factory, order_parameters_factory, renewal_payload):
    order = order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(renewal_payload=renewal_payload),
    )

    result = get_renewal_payload(order)  # act

    assert result == renewal_payload


def test_get_renewal_payload_json_string(order_factory, order_parameters_factory, renewal_payload):
    order = order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(renewal_payload=json.dumps(renewal_payload)),
    )

    result = get_renewal_payload(order)  # act

    assert result == renewal_payload


def test_get_renewal_payload_empty_string(order_factory, order_parameters_factory):
    order = order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(renewal_payload=""),
    )

    result = get_renewal_payload(order)  # act

    assert result is None


def test_get_renewal_payload_not_set(order_factory):
    order = order_factory(order_type="Change")

    result = get_renewal_payload(order)  # act

    assert result is None


def test_set_flex_discounts_parameter_records_applied_codes_only():
    order = {
        "parameters": {
            Param.PHASE_FULFILLMENT.value: [
                {"externalId": Param.FLEXIBLE_DISCOUNTS.value, "value": None},
            ],
        },
    }
    adobe_order = {
        "lineItems": [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "sub-1",
                "flexDiscounts": [
                    {"code": "APPLIED", "result": "SUCCESS"},
                    {"code": "REJECTED", "result": "FAILURE"},
                ],
            },
            {
                "extLineItemNumber": 2,
                "offerId": "65304579CA01A12",
                "subscriptionId": "sub-2",
                "flexDiscounts": [{"code": "REJECTED_ONLY", "result": "FAILURE"}],
            },
            {
                "extLineItemNumber": 3,
                "offerId": "65304580CA01A12",
                "subscriptionId": "sub-3",
                "flexDiscounts": [{"code": "NO_RESULT"}],
            },
            {"extLineItemNumber": 4, "offerId": "65304581CA01A12", "subscriptionId": "sub-4"},
        ]
    }

    result = set_flex_discounts_parameter(order, adobe_order)  # act

    param = get_fulfillment_parameter(result, Param.FLEXIBLE_DISCOUNTS.value)
    assert param["value"] == [
        {
            "extLineItemNumber": 1,
            "offerId": "65304578CA01A12",
            "subscriptionId": "sub-1",
            "flexDiscountCode": ["APPLIED"],
        },
        {
            "extLineItemNumber": 3,
            "offerId": "65304580CA01A12",
            "subscriptionId": "sub-3",
            "flexDiscountCode": ["NO_RESULT"],
        },
    ]


def test_set_flex_discounts_parameter_without_applied_codes():
    order = {
        "parameters": {
            Param.PHASE_FULFILLMENT.value: [
                {"externalId": Param.FLEXIBLE_DISCOUNTS.value, "value": "stale"},
            ],
        },
    }
    adobe_order = {
        "lineItems": [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "flexDiscounts": [{"code": "REJECTED", "result": "FAILURE"}],
            },
        ]
    }

    result = set_flex_discounts_parameter(order, adobe_order)  # act

    assert get_fulfillment_parameter(result, Param.FLEXIBLE_DISCOUNTS.value)["value"] is None


def test_set_flex_discounts_parameter_restricted_to_requested_codes():
    order = {
        "parameters": {
            Param.PHASE_FULFILLMENT.value: [
                {"externalId": Param.FLEXIBLE_DISCOUNTS.value, "value": None},
            ],
        },
    }
    adobe_order = {
        "lineItems": [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "sub-1",
                "flexDiscounts": [
                    {"code": "AUTO_APPLIED", "result": "SUCCESS"},
                    {"code": "REQUESTED", "result": "SUCCESS"},
                ],
            },
            {
                "extLineItemNumber": 2,
                "offerId": "65304579CA01A12",
                "subscriptionId": "sub-2",
                "flexDiscounts": [{"code": "ONLY_AUTO_APPLIED", "result": "SUCCESS"}],
            },
        ]
    }

    result = set_flex_discounts_parameter(order, adobe_order, requested_codes={1: "REQUESTED"})

    assert get_fulfillment_parameter(result, Param.FLEXIBLE_DISCOUNTS.value)["value"] == [
        {
            "extLineItemNumber": 1,
            "offerId": "65304578CA01A12",
            "subscriptionId": "sub-1",
            "flexDiscountCode": ["REQUESTED"],
        },
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, []),
        ([], []),
        ("", []),
        ("   ", []),
        (
            [{"extLineItemNumber": 1, "flexDiscountCode": ["A"]}],
            [{"extLineItemNumber": 1, "flexDiscountCode": ["A"]}],
        ),
        (
            '[{"extLineItemNumber": 1, "flexDiscountCode": ["A"]}]',
            [{"extLineItemNumber": 1, "flexDiscountCode": ["A"]}],
        ),
    ],
)
def test_get_flex_discounts_parameter(value, expected):
    order = {
        "parameters": {
            Param.PHASE_FULFILLMENT.value: [
                {"externalId": Param.FLEXIBLE_DISCOUNTS.value, "value": value},
            ],
        },
    }

    result = get_flex_discounts_parameter(order)  # act

    assert result == expected


def test_get_flex_discounts_parameter_without_parameter():
    result = get_flex_discounts_parameter({"parameters": {Param.PHASE_FULFILLMENT.value: []}})

    assert result == []
