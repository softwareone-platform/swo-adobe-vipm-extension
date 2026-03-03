import pytest

from adobe_vipm.flows.constants import AGREEMENT_VISIBLE_PARAMETERS, Param
from adobe_vipm.flows.utils.parameter import (
    update_agreement_parameters_visibility_for_agreement,
)


@pytest.fixture
def order_with_parameters():
    def _order(agreement_type="New"):
        return {
            "parameters": {
                "ordering": [
                    {
                        "externalId": Param.AGREEMENT_TYPE.value,
                        "value": agreement_type,
                        "constraints": {"hidden": False, "required": True},
                    },
                    {
                        "externalId": Param.COMPANY_NAME.value,
                        "value": "Test Company",
                        "constraints": {"hidden": False, "required": True},
                    },
                    {
                        "externalId": Param.ADDRESS.value,
                        "value": {},
                        "constraints": {"hidden": False, "required": True},
                    },
                    {
                        "externalId": Param.CONTACT.value,
                        "value": {},
                        "constraints": {"hidden": False, "required": True},
                    },
                    {
                        "externalId": Param.MEMBERSHIP_ID.value,
                        "value": "",
                        "constraints": {"hidden": True, "required": False},
                    },
                    {
                        "externalId": Param.THREE_YC.value,
                        "value": None,
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.THREE_YC_LICENSES.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.THREE_YC_CONSUMABLES.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.ADOBE_CUSTOMER_ADMIN_EMAIL.value,
                        "value": "",
                        "constraints": {"hidden": True, "required": False},
                    },
                    {
                        "externalId": Param.CHANGE_RESELLER_CODE.value,
                        "value": "",
                        "constraints": {"hidden": True, "required": False},
                    },
                ],
                "fulfillment": [
                    {
                        "externalId": Param.CUSTOMER_ID.value,
                        "value": "a-client-id",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.DUE_DATE.value,
                        "value": None,
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.THREE_YC_ENROLL_STATUS.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.THREE_YC_START_DATE.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.THREE_YC_END_DATE.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.THREE_YC_COMMITMENT_REQUEST_STATUS.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.THREE_YC_RECOMMITMENT_REQUEST_STATUS.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.THREE_YC_RECOMMITMENT.value,
                        "value": [],
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.MARKET_SEGMENT_ELIGIBILITY_STATUS.value,
                        "value": None,
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.COTERM_DATE.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.GLOBAL_CUSTOMER.value,
                        "value": [None],
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.DEPLOYMENT_ID.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.DEPLOYMENTS.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.LAST_SYNC_DATE.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                    {
                        "externalId": Param.RETRY_COUNT.value,
                        "value": "",
                        "constraints": {"hidden": False, "required": False},
                    },
                ],
            },
        }

    return _order


def _get_param_constraints(order, phase, external_id):
    for param in order["parameters"][phase]:
        if param["externalId"] == external_id:
            return param["constraints"]
    return None


@pytest.mark.parametrize(
    "agreement_type",
    ["New", "Migrate", "Transfer"],
)
def test_update_agreement_parameters_visibility_for_agreement_visible_params(
    order_with_parameters,
    agreement_type,
):
    order = order_with_parameters(agreement_type=agreement_type)
    visible_set = AGREEMENT_VISIBLE_PARAMETERS[agreement_type.lower()]

    result = update_agreement_parameters_visibility_for_agreement(order)

    for phase in ("ordering", "fulfillment"):
        for param in result["parameters"][phase]:
            expected_hidden = param["externalId"] not in visible_set
            assert param["constraints"]["hidden"] is expected_hidden, (
                f"Parameter {param['externalId']} in {phase} "
                f"should have hidden={expected_hidden} for {agreement_type}"
            )
            assert param["constraints"]["required"] is False


def test_update_agreement_parameters_visibility_for_agreement_new_hides_membership(
    order_with_parameters,
):
    order = order_with_parameters(agreement_type="New")

    result = update_agreement_parameters_visibility_for_agreement(order)

    membership_constraints = _get_param_constraints(
        result, "ordering", Param.MEMBERSHIP_ID.value
    )
    assert membership_constraints["hidden"] is True
    assert membership_constraints["required"] is False


def test_update_agreement_parameters_visibility_for_agreement_migrate_shows_membership(
    order_with_parameters,
):
    order = order_with_parameters(agreement_type="Migrate")

    result = update_agreement_parameters_visibility_for_agreement(order)

    membership_constraints = _get_param_constraints(
        result, "ordering", Param.MEMBERSHIP_ID.value
    )
    assert membership_constraints["hidden"] is False
    assert membership_constraints["required"] is False


def test_update_agreement_parameters_visibility_for_agreement_transfer_shows_transfer_params(
    order_with_parameters,
):
    order = order_with_parameters(agreement_type="Transfer")

    result = update_agreement_parameters_visibility_for_agreement(order)

    admin_email_constraints = _get_param_constraints(
        result, "ordering", Param.ADOBE_CUSTOMER_ADMIN_EMAIL.value
    )
    reseller_code_constraints = _get_param_constraints(
        result, "ordering", Param.CHANGE_RESELLER_CODE.value
    )
    assert admin_email_constraints["hidden"] is False
    assert reseller_code_constraints["hidden"] is False


def test_update_agreement_parameters_visibility_for_agreement_new_hides_transfer_params(
    order_with_parameters,
):
    order = order_with_parameters(agreement_type="New")

    result = update_agreement_parameters_visibility_for_agreement(order)

    admin_email_constraints = _get_param_constraints(
        result, "ordering", Param.ADOBE_CUSTOMER_ADMIN_EMAIL.value
    )
    reseller_code_constraints = _get_param_constraints(
        result, "ordering", Param.CHANGE_RESELLER_CODE.value
    )
    assert admin_email_constraints["hidden"] is True
    assert reseller_code_constraints["hidden"] is True


def test_update_agreement_parameters_visibility_for_agreement_hides_internal_fulfillment_params(
    order_with_parameters,
):
    order = order_with_parameters(agreement_type="New")

    result = update_agreement_parameters_visibility_for_agreement(order)

    retry_constraints = _get_param_constraints(
        result, "fulfillment", Param.RETRY_COUNT.value
    )
    eligibility_constraints = _get_param_constraints(
        result, "fulfillment", Param.MARKET_SEGMENT_ELIGIBILITY_STATUS.value
    )
    assert retry_constraints["hidden"] is True
    assert eligibility_constraints["hidden"] is True


def test_update_agreement_parameters_visibility_for_agreement_does_not_mutate_original(
    order_with_parameters,
):
    order = order_with_parameters(agreement_type="New")
    original_ordering = [
        dict(p["constraints"]) for p in order["parameters"]["ordering"]
    ]
    original_fulfillment = [
        dict(p["constraints"]) for p in order["parameters"]["fulfillment"]
    ]

    update_agreement_parameters_visibility_for_agreement(order)

    for idx, param in enumerate(order["parameters"]["ordering"]):
        assert param["constraints"] == original_ordering[idx]
    for idx, param in enumerate(order["parameters"]["fulfillment"]):
        assert param["constraints"] == original_fulfillment[idx]


def test_update_agreement_parameters_visibility_for_agreement_unknown_type_hides_all(
    order_with_parameters,
):
    order = order_with_parameters(agreement_type="Unknown")

    result = update_agreement_parameters_visibility_for_agreement(order)

    for phase in ("ordering", "fulfillment"):
        for param in result["parameters"][phase]:
            assert param["constraints"]["hidden"] is True
            assert param["constraints"]["required"] is False


def test_update_agreement_parameters_visibility_for_agreement_empty_type_hides_all(
    order_with_parameters,
):
    order = order_with_parameters(agreement_type="")

    result = update_agreement_parameters_visibility_for_agreement(order)

    for phase in ("ordering", "fulfillment"):
        for param in result["parameters"][phase]:
            assert param["constraints"]["hidden"] is True
            assert param["constraints"]["required"] is False

