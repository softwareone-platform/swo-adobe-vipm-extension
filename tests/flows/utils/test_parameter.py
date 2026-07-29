import json
from typing import Any

import pytest
from pytest_mock import MockerFixture

from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.utils.parameter import (
    get_switch_payload,
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
