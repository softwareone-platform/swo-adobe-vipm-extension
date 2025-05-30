import copy

import pytest

from adobe_vipm.adobe.constants import (
    STATUS_INVALID_ADDRESS,
    STATUS_INVALID_FIELDS,
    STATUS_INVALID_MINIMUM_QUANTITY,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
    ERR_ADOBE_ADDRESS,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    ERR_MARKET_SEGMENT_NOT_ELIGIBLE,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    MARKET_SEGMENT_COMMERCIAL,
    PARAM_3YC_COMMITMENT_REQUEST_STATUS,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_LICENSES,
    PARAM_ADDRESS,
    PARAM_CONTACT,
    STATUS_MARKET_SEGMENT_ELIGIBLE,
    STATUS_MARKET_SEGMENT_NOT_ELIGIBLE,
    STATUS_MARKET_SEGMENT_PENDING,
    TEMPLATE_NAME_PURCHASE,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.purchase import (
    CreateCustomer,
    RefreshCustomer,
    ValidateMarketSegmentEligibility,
    fulfill_purchase_order,
)
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    SetOrUpdateCotermNextSyncDates,
    SetupDueDate,
    StartOrderProcessing,
    SubmitNewOrder,
    ValidateDuplicateLines,
)
from adobe_vipm.flows.helpers import PrepareCustomerData, SetupContext, UpdatePrices
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_fulfillment_parameter,
    get_ordering_parameter,
)


def test_refresh_customer_step(mocker, order_factory):
    mocked_customer = mocker.MagicMock()
    mocked_refreshed_customer = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_customer.return_value = mocked_refreshed_customer

    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    order = order_factory()

    context = Context(
        order=order,
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_customer=mocked_customer,
    )

    step = RefreshCustomer()
    step(mocked_client, context, mocked_next_step)

    assert context.adobe_customer == mocked_refreshed_customer
    mocked_adobe_client.get_customer.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


@pytest.mark.parametrize("segment", ["EDU", "GOV"])
def test_validate_market_segment_eligibility_step(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
    segment,
):
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            market_segment_eligibility_status=STATUS_MARKET_SEGMENT_ELIGIBLE,
        ),
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        market_segment=segment,
    )

    step = ValidateMarketSegmentEligibility()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_market_segment_eligibility_commercial(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
):
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            market_segment_eligibility_status=STATUS_MARKET_SEGMENT_ELIGIBLE,
        ),
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        market_segment=MARKET_SEGMENT_COMMERCIAL,
    )

    step = ValidateMarketSegmentEligibility()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mocked_client, context)


@pytest.mark.parametrize("segment", ["EDU", "GOV"])
def test_validate_market_segment_eligibility_step_status_not_set(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
    segment,
):
    order = order_factory()
    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        market_segment=segment,
    )

    step = ValidateMarketSegmentEligibility()
    step(mocked_client, context, mocked_next_step)
    mocked_switch_to_query.assert_called_once_with(
        mocked_client,
        order_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                market_segment_eligibility_status=STATUS_MARKET_SEGMENT_PENDING,
            ),
        ),
        template_name=TEMPLATE_NAME_PURCHASE,
    )
    mocked_next_step.assert_not_called()


@pytest.mark.parametrize("segment", ["EDU", "GOV"])
def test_validate_market_segment_eligibility_step_status_pending(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
    segment,
):
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            market_segment_eligibility_status=STATUS_MARKET_SEGMENT_PENDING,
        ),
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        market_segment=segment,
    )

    step = ValidateMarketSegmentEligibility()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_not_called()


@pytest.mark.parametrize("segment", ["EDU", "GOV"])
def test_validate_market_segment_eligibility_step_status_eligible(
    mocker,
    order_factory,
    fulfillment_parameters_factory,
    segment,
):
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(
            market_segment_eligibility_status=STATUS_MARKET_SEGMENT_NOT_ELIGIBLE,
        ),
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_failed",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order,
        market_segment=segment,
    )

    step = ValidateMarketSegmentEligibility()
    step(mocked_client, context, mocked_next_step)

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client, order, ERR_MARKET_SEGMENT_NOT_ELIGIBLE.to_dict(segment=segment)
    )

    mocked_next_step.assert_not_called()


def test_create_customer_step(
    mocker, order_factory, customer_data, adobe_customer_factory
):
    adobe_customer = adobe_customer_factory()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_customer_account.return_value = adobe_customer

    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory()

    mocked_save_data = mocker.patch.object(
        CreateCustomer,
        "save_data",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        customer_data=customer_data,
        agreement_id="agreement-id",
        authorization_id="auth-id",
        seller_id="seller-id",
        market_segment="market-segment",
    )

    step = CreateCustomer()
    step(mocked_client, context, mocked_next_step)

    assert context.adobe_customer == adobe_customer
    assert context.adobe_customer_id == adobe_customer["customerId"]

    mocked_adobe_client.create_customer_account.assert_called_once_with(
        context.authorization_id,
        context.seller_id,
        context.agreement_id,
        context.market_segment,
        customer_data,
    )
    mocked_save_data.assert_called_once_with(mocked_client, context)
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_create_customer_step_no_contact(
    mocker,
    order_factory,
    customer_data,
):
    customer_data_without_contact = copy.copy(customer_data)
    del customer_data_without_contact["contact"]

    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory()

    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )

    mocked_save_data = mocker.patch.object(
        CreateCustomer,
        "save_data",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        customer_data=customer_data_without_contact,
        agreement_id="agreement-id",
        authorization_id="auth-id",
        seller_id="seller-id",
        market_segment="market-segment",
    )

    step = CreateCustomer()
    step(mocked_client, context, mocked_next_step)

    assert context.adobe_customer is None
    assert context.adobe_customer_id is None

    param = get_ordering_parameter(context.order, PARAM_CONTACT)
    assert param["error"] == ERR_ADOBE_CONTACT.to_dict(
        title=param["name"], details="it is mandatory."
    )

    mocked_switch_to_query.assert_called_once_with(
        mocked_client,
        context.order,
    )
    mocked_adobe_client.create_customer_account.assert_not_called()
    mocked_save_data.assert_not_called()
    mocked_next_step.assert_not_called()


def test_create_customer_step_exception(
    mocker,
    order_factory,
    customer_data,
    adobe_api_error_factory,
):
    error = AdobeAPIError(400, adobe_api_error_factory("1234", "api error"))

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.create_customer_account.side_effect = error

    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory()

    mocked_save_data = mocker.patch.object(
        CreateCustomer,
        "save_data",
    )

    mocked_handle_error = mocker.patch.object(
        CreateCustomer,
        "handle_error",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        customer_data=customer_data,
        agreement_id="agreement-id",
        authorization_id="auth-id",
        seller_id="seller-id",
        market_segment="market-segment",
    )

    step = CreateCustomer()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.create_customer_account.assert_called_once_with(
        context.authorization_id,
        context.seller_id,
        context.agreement_id,
        context.market_segment,
        customer_data,
    )
    mocked_save_data.assert_not_called()
    mocked_handle_error.assert_called_once_with(mocked_client, context, error)
    mocked_next_step.assert_not_called()


def test_create_customer_step_already_created(
    mocker,
    order_factory,
):
    mocked_adobe_client = mocker.MagicMock()

    mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    order = order_factory()

    mocked_save_data = mocker.patch.object(
        CreateCustomer,
        "save_data",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(
        order=order,
        adobe_customer_id="customer-id",
    )

    step = CreateCustomer()
    step(mocked_client, context, mocked_next_step)

    mocked_adobe_client.create_customer_account.assert_not_called()
    mocked_save_data.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_create_customer_step_save_data(
    mocker,
    order_factory,
    adobe_customer_factory,
):
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.update_order",
    )
    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.update_agreement",
    )

    order = order_factory()
    adobe_customer = adobe_customer_factory()

    mocked_client = mocker.MagicMock()

    context = Context(
        order=order,
        order_id="order-id",
        agreement_id="agreement-id",
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = CreateCustomer()
    step.save_data(mocked_client, context)

    assert get_adobe_customer_id(context.order) == context.adobe_customer_id
    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    mocked_update_agreement.assert_called_once_with(
        mocked_client,
        context.agreement_id,
        externalIds={"vendor": context.adobe_customer_id},
    )


def test_create_customer_step_save_data_with_3yc_request(
    mocker,
    order_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
):
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.update_order",
    )
    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.update_agreement",
    )

    order = order_factory()
    commitment = adobe_commitment_factory()
    adobe_customer = adobe_customer_factory(commitment_request=commitment)

    mocked_client = mocker.MagicMock()

    context = Context(
        order=order,
        order_id="order-id",
        agreement_id="agreement-id",
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )

    step = CreateCustomer()
    step.save_data(mocked_client, context)

    assert get_adobe_customer_id(context.order) == context.adobe_customer_id

    ff_param = get_fulfillment_parameter(
        context.order,
        PARAM_3YC_COMMITMENT_REQUEST_STATUS,
    )
    assert ff_param["value"] == commitment["status"]

    mocked_update_order.assert_called_once_with(
        mocked_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    mocked_update_agreement.assert_called_once_with(
        mocked_client,
        context.agreement_id,
        externalIds={"vendor": context.adobe_customer_id},
    )


def test_create_customer_step_handle_error_unexpected_error(
    mocker, order_factory, adobe_api_error_factory
):
    error = AdobeAPIError(400, adobe_api_error_factory("9999", "unexpected"))

    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_failed",
    )
    mocked_client = mocker.MagicMock()

    order = order_factory()

    context = Context(order=order)

    step = CreateCustomer()
    step.handle_error(mocked_client, context, error)

    mocked_switch_to_failed.assert_called_once_with(
        mocked_client,
        context.order,
        ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(error)),
    )


def test_create_customer_step_handle_error_address(
    mocker, order_factory, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=STATUS_INVALID_ADDRESS,
            message="Invalid address",
            details=["detail1", "detail2"],
        ),
    )

    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    mocked_client = mocker.MagicMock()

    order = order_factory()

    context = Context(order=order)

    step = CreateCustomer()
    step.handle_error(mocked_client, context, error)

    param = get_ordering_parameter(context.order, PARAM_ADDRESS)
    assert param["error"] == ERR_ADOBE_ADDRESS.to_dict(
        title=param["name"],
        details=str(error),
    )

    mocked_switch_to_query.assert_called_once_with(
        mocked_client,
        context.order,
    )


def test_create_customer_step_handle_error_3yc_minimum_quantity_licenses(
    mocker, order_factory, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=STATUS_INVALID_MINIMUM_QUANTITY,
            message="Minimum quantity out of range",
            details=["LICENSE"],
        ),
    )

    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    mocked_client = mocker.MagicMock()

    order = order_factory()

    context = Context(order=order)

    step = CreateCustomer()
    step.handle_error(mocked_client, context, error)

    param_licenses = get_ordering_parameter(context.order, PARAM_3YC_LICENSES)
    assert param_licenses["error"] == ERR_3YC_QUANTITY_LICENSES.to_dict(
        title=param_licenses["name"],
    )

    mocked_switch_to_query.assert_called_once_with(
        mocked_client,
        context.order,
    )


def test_create_customer_step_handle_error_3yc_minimum_quantity_consumables(
    mocker, order_factory, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=STATUS_INVALID_MINIMUM_QUANTITY,
            message="Minimum quantity out of range",
            details=["CONSUMABLES"],
        ),
    )

    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    mocked_client = mocker.MagicMock()

    order = order_factory()

    context = Context(order=order)

    step = CreateCustomer()
    step.handle_error(mocked_client, context, error)

    param_consumables = get_ordering_parameter(context.order, PARAM_3YC_CONSUMABLES)
    assert param_consumables["error"] == ERR_3YC_QUANTITY_CONSUMABLES.to_dict(
        title=param_consumables["name"],
    )

    mocked_switch_to_query.assert_called_once_with(
        mocked_client,
        context.order,
    )


def test_create_customer_step_handle_error_3yc_minimum_quantity_no_minimums(
    mocker, order_factory, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=STATUS_INVALID_MINIMUM_QUANTITY,
            message="Minimum quantity out of range",
            details=[],
        ),
    )

    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    mocked_client = mocker.MagicMock()

    order = order_factory()

    context = Context(order=order)

    step = CreateCustomer()
    step.handle_error(mocked_client, context, error)

    param_licenses = get_ordering_parameter(context.order, PARAM_3YC_LICENSES)
    param_consumables = get_ordering_parameter(context.order, PARAM_3YC_CONSUMABLES)

    assert context.order["error"] == ERR_3YC_NO_MINIMUMS.to_dict(
        title_min_licenses=param_licenses["name"],
        title_min_consumables=param_consumables["name"],
    )

    mocked_switch_to_query.assert_called_once_with(
        mocked_client,
        context.order,
    )


@pytest.mark.parametrize(
    ("param_external_id", "error_constant", "error_details"),
    [
        ("contact", ERR_ADOBE_CONTACT, "companyProfile.contacts[0].firstName"),
        ("companyName", ERR_ADOBE_COMPANY_NAME, "companyProfile.companyName"),
    ],
)
def test_create_customer_step_handle_error_invalid_fields(
    mocker,
    adobe_api_error_factory,
    order_factory,
    param_external_id,
    error_constant,
    error_details,
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=STATUS_INVALID_FIELDS,
            message="Invalid fields",
            details=[error_details],
        ),
    )

    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    mocked_client = mocker.MagicMock()

    order = order_factory()

    context = Context(order=order)

    step = CreateCustomer()
    step.handle_error(mocked_client, context, error)

    param = get_ordering_parameter(context.order, param_external_id)
    assert param["error"] == error_constant.to_dict(
        title=param["name"],
        details=str(error),
    )

    mocked_switch_to_query.assert_called_once_with(
        mocked_client,
        context.order,
    )


def test_fulfill_purchase_order(mocker):
    """
    Tests the purchase order pipeline is created with the
    expected steps and executed.
    """
    mocked_pipeline_instance = mocker.MagicMock()

    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    fulfill_purchase_order(mocked_client, mocked_order)

    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 14

    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[0], SetupContext)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[1], SetupDueDate)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[2],
        ValidateDuplicateLines,
    )
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[3],
        ValidateMarketSegmentEligibility,
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[4], StartOrderProcessing)
    assert (
        mocked_pipeline_ctor.mock_calls[0].args[4].template_name
        == TEMPLATE_NAME_PURCHASE
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[5], PrepareCustomerData)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[6], CreateCustomer)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[7], GetPreviewOrder)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[8], SubmitNewOrder)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[9], CreateOrUpdateSubscriptions
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[10], RefreshCustomer)
    assert isinstance(
        mocked_pipeline_ctor.mock_calls[0].args[11], SetOrUpdateCotermNextSyncDates
    )
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[12], UpdatePrices)
    assert isinstance(mocked_pipeline_ctor.mock_calls[0].args[13], CompleteOrder)
    assert (
        mocked_pipeline_ctor.mock_calls[0].args[13].template_name
        == TEMPLATE_NAME_PURCHASE
    )
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mocked_client,
        mocked_context,
    )
