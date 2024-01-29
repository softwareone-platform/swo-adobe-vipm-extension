import copy

import pytest

from adobe_vipm.adobe.constants import (
    STATUS_ACCOUNT_ALREADY_EXISTS,
    STATUS_INVALID_ADDRESS,
    STATUS_INVALID_FIELDS,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.shared import create_customer_account


def test_create_customer_account(
    mocker,
    buyer,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    """
    Test create a customer account in Adobe.
    Customer data is available as ordering parameters.
    """
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_customer_account.return_value = "adobe-customer-id"
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.shared.update_order",
        return_value={"updated": "order"},
    )

    updated_order = create_customer_account(
        mocked_mpt_client,
        "US",
        buyer,
        order,
    )

    mocked_adobe_client.create_customer_account.assert_called_once_with(
        "US",
        buyer["id"],
        {param["name"]: param["value"] for param in order_parameters_factory()},
    )
    mocked_update_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "order": order_parameters_factory(),
                "fulfillment": fulfillment_parameters_factory(customer_id="adobe-customer-id"),
            }
        },
    )
    assert updated_order == {"updated": "order"}


def test_create_customer_account_empty_order_parameters(
    mocker,
    buyer,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
):
    """
    Test create a customer account in Adobe.
    Customer data must be taken getting the buyer associated with the order.
    """
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_customer_account.return_value = "adobe-customer-id"
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.shared.update_order",
        return_value=copy.deepcopy(order),
    )

    order["parameters"]["order"] = order_parameters_factory(
        company_name="",
        preferred_language="",
        address={},
        contact={},
    )

    create_customer_account(
        mocked_mpt_client,
        "US",
        buyer,
        order,
    )

    mocked_adobe_client.create_customer_account.assert_called_once_with(
        "US",
        buyer["id"],
        {param["name"]: param["value"] for param in order_parameters_factory()},
    )

    assert mocked_update_order.call_count == 2

    assert mocked_update_order.mock_calls[0].args == (
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "order": order_parameters_factory(),
                "fulfillment": fulfillment_parameters_factory(),
            }
        },
    )

    assert mocked_update_order.mock_calls[1].args == (
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "order": order_parameters_factory(),
                "fulfillment": fulfillment_parameters_factory(customer_id="adobe-customer-id"),
            }
        },
    )


def test_create_customer_account_address_error(
    mocker,
    buyer,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
    settings,
):
    """
    Test address validation error handling when create a customer account in Adobe.
    """
    settings.EXTENSION_CONFIG["QUERYING_TEMPLATE_ID"] = "TPL-0000"
    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        adobe_api_error_factory(
            code=STATUS_INVALID_ADDRESS,
            message="Invalid address",
            details=["detail1", "detail2"],
        ),
    )
    mocked_adobe_client.create_customer_account.side_effect = adobe_error
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_query_order = mocker.patch(
        "adobe_vipm.flows.shared.query_order",
        return_value={"query": "order"},
    )

    updated_order = create_customer_account(
        mocked_mpt_client,
        "US",
        buyer,
        order,
    )

    ordering_parameters = order_parameters_factory()
    address_param = next(filter(lambda x: x["name"] == "Address", ordering_parameters))
    address_param["error"] = str(adobe_error)
    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "order": ordering_parameters,
                "fulfillment": fulfillment_parameters_factory(),
            },
            "template": {"id": "TPL-0000"},
        },
    )
    assert updated_order is None


@pytest.mark.parametrize(
    ("param_name", "error_details"),
    [
        ("Contact", "companyProfile.contacts[0].firstName"),
        ("CompanyName", "companyProfile.companyName"),
        ("PreferredLanguage", "companyProfile.preferredLanguage"),
    ],
)
def test_create_customer_account_fields_error(
    mocker,
    buyer,
    order,
    order_parameters_factory,
    fulfillment_parameters_factory,
    adobe_api_error_factory,
    settings,
    param_name,
    error_details,
):
    """
    Test fields validation error handling when create a customer account in Adobe.
    """
    settings.EXTENSION_CONFIG["QUERYING_TEMPLATE_ID"] = "TPL-0000"
    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        adobe_api_error_factory(
            code=STATUS_INVALID_FIELDS,
            message="Invalid fields",
            details=[error_details],
        ),
    )
    mocked_adobe_client.create_customer_account.side_effect = adobe_error
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_query_order = mocker.patch(
        "adobe_vipm.flows.shared.query_order",
        return_value={"query": "order"},
    )

    updated_order = create_customer_account(
        mocked_mpt_client,
        "US",
        buyer,
        order,
    )

    ordering_parameters = order_parameters_factory()
    param = next(filter(lambda x: x["name"] == param_name, ordering_parameters))
    param["error"] = str(adobe_error)
    mocked_query_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        {
            "parameters": {
                "order": ordering_parameters,
                "fulfillment": fulfillment_parameters_factory(),
            },
            "template": {"id": "TPL-0000"},
        },
    )
    assert updated_order is None


def test_create_customer_account_other_error(
    mocker,
    buyer,
    order,
    adobe_api_error_factory,
):
    """
    Test unrecoverable error handling when create a customer account in Adobe.
    """
    mocked_adobe_client = mocker.MagicMock()
    adobe_error = AdobeAPIError(
        adobe_api_error_factory(
            code=STATUS_ACCOUNT_ALREADY_EXISTS,
            message="Account already exists.",
        ),
    )
    mocked_adobe_client.create_customer_account.side_effect = adobe_error
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.shared.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_fail_order = mocker.patch(
        "adobe_vipm.flows.shared.fail_order",
        return_value={"failed": "order"},
    )

    updated_order = create_customer_account(
        mocked_mpt_client,
        "US",
        buyer,
        order,
    )

    mocked_fail_order.assert_called_once_with(
        mocked_mpt_client,
        order["id"],
        str(adobe_error),
    )
    assert updated_order is None
