import datetime as dt
import json
import logging
from urllib.parse import urljoin

import pytest
import requests
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    AdobeCustomerStatus,
    AdobeErrorCode,
    AdobeOrderStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
    ERR_ADOBE_ADDRESS,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    ERR_DUE_DATE_REACHED,
    ERR_VIPM_UNHANDLED_EXCEPTION,
    MARKET_SEGMENT_COMMERCIAL,
    TEMPLATE_EDUCATION_QUERY_SUBSEGMENT,
    TEMPLATE_NAME_PURCHASE,
    TEMPLATE_NAME_SCREENING,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.purchase import (
    CheckAccountStatus,
    CreateCustomer,
    RefreshCustomer,
    RollScreeningDueDate,
    ValidateEducationSubSegments,
    ValidateGovernmentLGA,
    fulfill_purchase_order,
)
from adobe_vipm.flows.fulfillment.renewal import RecordDiscountRedemptions
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateAssets,
    CreateOrUpdateSubscriptions,
    DiscardCarriedOverFlexDiscounts,
    GetPreviewOrder,
    NullifyFlexDiscountParam,
    SelectFlexDiscounts,
    SetOrUpdateCotermDate,
    SetupDueDate,
    StartOrderProcessing,
    SubmitNewOrder,
    SyncAgreement,
    UpdateAgreementParamsVisibility,
    ValidateDuplicateLines,
)
from adobe_vipm.flows.helpers import (
    PrepareCustomerData,
    SetupContext,
    UpdatePrices,
    Validate3YCCommitment,
)
from adobe_vipm.flows.pipeline import Pipeline
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_due_date,
    get_fulfillment_parameter,
    get_ordering_parameter,
)
from adobe_vipm.notifications import FactsSection


@pytest.fixture
def adobe_http_client(mocker, adobe_client_factory):
    adobe_client, _, _ = adobe_client_factory()
    for module in ("purchase", "shared"):
        mocker.patch(
            f"adobe_vipm.flows.fulfillment.{module}.get_adobe_client",
            autospec=True,
            return_value=adobe_client,
        )
    return adobe_client


@pytest.fixture
def processing_template_url_factory():
    def factory(template_name):
        rql_filter = (
            f"and(eq(type,'OrderProcessing'),or(eq(default,'true'),eq(name,'{template_name}')))"
        )
        return (
            "https://localhost/public/v1/catalog/products/PRD-1111-1111/templates"
            f"?{rql_filter}&order=default&limit=1"
        )

    return factory


@pytest.fixture
def processing_template_response_factory(requests_mocker, processing_template_url_factory):
    def factory(template_name, templates):
        def match_template_name(request):
            return f"eq(name,'{template_name}')" in request.url, "template name does not match"

        return requests_mocker.get(
            processing_template_url_factory(template_name),
            json={"data": templates},
            match=[match_template_name],
        )

    return factory


@pytest.fixture
def screening_template():
    return {"id": "TPL-9999", "name": TEMPLATE_NAME_SCREENING}


@pytest.fixture
def purchase_template():
    return {"id": "TPL-1234", "name": TEMPLATE_NAME_PURCHASE}


@pytest.fixture
def purchase_context(mock_order, adobe_authorizations_file):
    authorization = adobe_authorizations_file["authorizations"][0]
    return Context(
        order=mock_order,
        order_id=mock_order["id"],
        product_id="PRD-1111-1111",
        agreement_id=mock_order["agreement"]["id"],
        authorization_id=authorization["authorization_uk"],
        seller_id=authorization["resellers"][0]["seller_id"],
        market_segment="COM",
        new_lines=mock_order["lines"],
    )


def test_refresh_customer_step(mocker, mock_adobe_client, mock_order):
    mocked_customer = mocker.MagicMock()
    mocked_refreshed_customer = mocker.MagicMock()
    mock_adobe_client.get_customer.return_value = mocked_refreshed_customer
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=mock_order,
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        adobe_customer=mocked_customer,
    )
    step = RefreshCustomer()

    step(mocked_client, context, mocked_next_step)  # act

    assert context.adobe_customer == mocked_refreshed_customer
    mock_adobe_client.get_customer.assert_called_once_with(
        context.authorization_id,
        context.adobe_customer_id,
    )
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_market_segment_education_without_market_subsegments(
    mocker, order_factory, adobe_customer_factory
):
    order = order_factory()
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    adobe_customer = adobe_customer_factory()
    adobe_customer["companyProfile"]["marketSegment"] = "EDU"
    adobe_customer["companyProfile"]["marketSubSegments"] = None
    context = Context(order=order, market_segment="EDU", adobe_customer=adobe_customer)
    step = ValidateEducationSubSegments()

    step(mocked_client, context, mocked_next_step)  # act

    mocked_next_step.assert_not_called()
    mocked_switch_to_query.assert_called_once_with(
        mocked_client,
        order,
        template_name=TEMPLATE_EDUCATION_QUERY_SUBSEGMENT,
    )


def test_validate_market_segment_eligibility_commercial(
    mocker, order_factory, fulfillment_parameters_factory
):
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(),
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(
        order=order, product_id="PRD-1111-1111", market_segment=MARKET_SEGMENT_COMMERCIAL
    )
    step = ValidateEducationSubSegments()

    step(mocked_client, context, mocked_next_step)  # act

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_market_segment_eligibility_lga_agency_type_not_federal_or_state(
    mocker,
    mock_order,
):
    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    mock_order["product"]["id"] = "PRD-3333-3333"
    mock_order["parameters"]["ordering"].append({
        "id": "PAR-1164-2550-0043",
        "externalId": "companyAgencyType",
        "name": "Agency type",
        "type": "DropDown",
        "phase": "Order",
        "error": None,
    })
    context = Context(order=mock_order, product_id="PRD-3333-3333")
    step = ValidateGovernmentLGA()

    step(mocked_client, context, mocked_next_step)  # act

    mocked_switch_to_query.assert_called_once_with(
        mocked_client,
        context.order,
        template_name=TEMPLATE_NAME_PURCHASE,
    )
    mocked_next_step.assert_not_called()


def test_validate_market_segment_eligibility_lga_agency_type_valid(
    mocker,
    mock_order,
):
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    mock_order["product"]["id"] = "PRD-3333-3333"
    mock_order["parameters"]["ordering"].append({
        "id": "PAR-1164-2550-0043",
        "externalId": "companyAgencyType",
        "name": "Agency type",
        "type": "DropDown",
        "phase": "Order",
        "error": None,
        "value": "FEDERAL",
    })
    context = Context(order=mock_order, product_id="PRD-3333-3333")
    step = ValidateGovernmentLGA()

    step(mocked_client, context, mocked_next_step)  # act

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_create_customer_step(
    mocker, mock_adobe_client, mock_next_step, mock_mpt_client, mock_order, adobe_customer_factory
):
    adobe_customer = adobe_customer_factory()
    mock_adobe_client.create_customer_account.return_value = adobe_customer
    mocked_save_data = mocker.patch.object(CreateCustomer, "save_data")
    context = Context(
        order=mock_order,
        product_id="PRD-1111-1111",
        agreement_id="agreement-id",
        authorization_id="auth-id",
        seller_id="seller-id",
        market_segment="COM",
    )
    step = CreateCustomer()

    step(mock_mpt_client, context, mock_next_step)  # act

    assert context.adobe_customer == adobe_customer
    assert context.adobe_customer_id == adobe_customer["customerId"]
    mock_adobe_client.create_customer_account.assert_called_once_with(
        context.authorization_id,
        context.seller_id,
        context.agreement_id,
        context.market_segment,
        context.customer_data,
    )
    mocked_save_data.assert_called_once_with(mock_mpt_client, context)
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_create_customer_lga_step(
    mocker, mock_adobe_client, mock_mpt_client, mock_next_step, mock_order, adobe_customer_factory
):
    adobe_customer = adobe_customer_factory()
    mock_adobe_client.create_customer_account_lga.return_value = adobe_customer
    mocked_save_data = mocker.patch.object(CreateCustomer, "save_data")
    context = Context(
        order=mock_order,
        product_id="PRD-3333-3333",
        agreement_id="agreement-id",
        authorization_id="auth-id",
        seller_id="seller-id",
        market_segment="COM",
    )
    step = CreateCustomer()

    step(mock_mpt_client, context, mock_next_step)  # act

    assert context.adobe_customer == adobe_customer
    assert context.adobe_customer_id == adobe_customer["customerId"]
    mock_adobe_client.create_customer_account_lga.assert_called_once_with(
        context.authorization_id,
        context.seller_id,
        context.agreement_id,
        context.market_segment,
        context.customer_data,
    )
    mocked_save_data.assert_called_once_with(mock_mpt_client, context)
    mock_next_step.assert_called_once_with(mock_mpt_client, context)


def test_create_customer_step_no_contact(
    mocker,
    mock_adobe_client,
    mock_next_step,
    mock_mpt_client,
    fulfillment_parameters_factory,
    order_factory,
    order_parameters_factory,
):
    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    mocked_save_data = mocker.patch.object(CreateCustomer, "save_data")
    order = order_factory(
        order_parameters=order_parameters_factory(contact={}),
        fulfillment_parameters=fulfillment_parameters_factory(),
    )
    context = Context(
        order=order,
        agreement_id="agreement-id",
        authorization_id="auth-id",
        seller_id="seller-id",
        market_segment="market-segment",
    )
    step = CreateCustomer()

    step(mock_mpt_client, context, mock_next_step)  # act

    assert context.adobe_customer is None
    assert context.adobe_customer_id is None
    param = get_ordering_parameter(context.order, Param.CONTACT.value)
    assert param["error"] == ERR_ADOBE_CONTACT.to_dict(
        title=param["name"], details="it is mandatory."
    )
    mocked_switch_to_query.assert_called_once_with(mock_mpt_client, context.order)
    mock_adobe_client.create_customer_account.assert_not_called()
    mocked_save_data.assert_not_called()
    mock_next_step.assert_not_called()


def test_create_customer_step_exception(
    mocker,
    mock_adobe_client,
    mock_next_step,
    mock_mpt_client,
    mock_order,
    adobe_api_error_factory,
):
    error = AdobeAPIError(400, adobe_api_error_factory("1234", "api error"))
    mock_adobe_client.create_customer_account.side_effect = error
    mocked_save_data = mocker.patch.object(CreateCustomer, "save_data")
    mocked_handle_error = mocker.patch.object(CreateCustomer, "handle_error")
    context = Context(
        product_id="PRD-1111-1111",
        order=mock_order,
        agreement_id="agreement-id",
        authorization_id="auth-id",
        seller_id="seller-id",
        market_segment="COM",
    )
    step = CreateCustomer()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_adobe_client.create_customer_account.assert_called_once_with(
        context.authorization_id,
        context.seller_id,
        context.agreement_id,
        context.market_segment,
        context.customer_data,
    )
    mocked_save_data.assert_not_called()
    mocked_handle_error.assert_called_once_with(mock_mpt_client, context, error)
    mock_next_step.assert_not_called()


def test_create_customer_step_already_created(mocker, mock_adobe_client, mock_order):
    mocked_save_data = mocker.patch.object(CreateCustomer, "save_data")
    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    context = Context(order=mock_order, adobe_customer_id="customer-id")
    step = CreateCustomer()

    step(mocked_client, context, mocked_next_step)  # act

    mock_adobe_client.create_customer_account.assert_not_called()
    mocked_save_data.assert_not_called()
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_create_customer_step_save_data(
    mocker, mock_mpt_client, mock_order, adobe_customer_factory
):
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.purchase.update_order")
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.fulfillment.purchase.update_agreement")
    adobe_customer = adobe_customer_factory()
    context = Context(
        order=mock_order,
        order_id="order-id",
        agreement_id="agreement-id",
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )
    step = CreateCustomer()

    step.save_data(mock_mpt_client, context)  # act

    assert get_adobe_customer_id(context.order) == context.adobe_customer_id
    mocked_update_order.assert_called_once_with(
        mock_mpt_client, context.order_id, parameters=context.order["parameters"]
    )
    mocked_update_agreement.assert_called_once_with(
        mock_mpt_client,
        context.agreement_id,
        externalIds={"vendor": context.adobe_customer_id},
    )


def test_create_customer_step_save_data_with_3yc_request(
    mocker,
    mock_mpt_client,
    mock_order,
    adobe_customer_factory,
    adobe_commitment_factory,
):
    mocked_update_order = mocker.patch("adobe_vipm.flows.fulfillment.purchase.update_order")
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.fulfillment.purchase.update_agreement")
    commitment = adobe_commitment_factory()
    adobe_customer = adobe_customer_factory(commitment_request=commitment)
    context = Context(
        order=mock_order,
        order_id="order-id",
        agreement_id="agreement-id",
        adobe_customer_id=adobe_customer["customerId"],
        adobe_customer=adobe_customer,
    )
    step = CreateCustomer()

    step.save_data(mock_mpt_client, context)  # act

    assert get_adobe_customer_id(context.order) == context.adobe_customer_id
    ff_param = get_fulfillment_parameter(
        context.order,
        Param.THREE_YC_COMMITMENT_REQUEST_STATUS.value,
    )
    assert ff_param["value"] == commitment["status"]
    mocked_update_order.assert_called_once_with(
        mock_mpt_client,
        context.order_id,
        parameters=context.order["parameters"],
    )
    mocked_update_agreement.assert_called_once_with(
        mock_mpt_client,
        context.agreement_id,
        externalIds={"vendor": context.adobe_customer_id},
    )


def test_create_customer_step_handle_error_unexpected_error(
    mocker, mock_mpt_client, mock_order, adobe_api_error_factory
):
    error = AdobeAPIError(400, adobe_api_error_factory("9999", "unexpected"))
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_failed"
    )
    context = Context(order=mock_order)
    step = CreateCustomer()

    step.handle_error(mock_mpt_client, context, error)  # act

    mocked_switch_to_failed.assert_called_once_with(
        mock_mpt_client,
        context.order,
        ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(error)),
    )


def test_create_customer_step_handle_error_address(
    mocker, mock_mpt_client, mock_order, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.INVALID_ADDRESS.value,
            message="Invalid address",
            details=["detail1", "detail2"],
        ),
    )
    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    context = Context(order=mock_order)
    step = CreateCustomer()

    step.handle_error(mock_mpt_client, context, error)  # act

    param = get_ordering_parameter(context.order, Param.ADDRESS.value)
    assert param["error"] == ERR_ADOBE_ADDRESS.to_dict(title=param["name"], details=str(error))
    mocked_switch_to_query.assert_called_once_with(mock_mpt_client, context.order)


def test_create_customer_step_handle_error_3yc_minimum_quantity_licenses(
    mocker, mock_mpt_client, mock_order, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.INVALID_MINIMUM_QUANTITY.value,
            message="Minimum quantity out of range",
            details=["LICENSE"],
        ),
    )
    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query"
    )
    context = Context(order=mock_order)
    step = CreateCustomer()

    step.handle_error(mock_mpt_client, context, error)  # act

    param_licenses = get_ordering_parameter(context.order, Param.THREE_YC_LICENSES.value)
    assert param_licenses["error"] == ERR_3YC_QUANTITY_LICENSES.to_dict(
        title=param_licenses["name"],
    )
    mocked_switch_to_query.assert_called_once_with(mock_mpt_client, context.order)


def test_create_customer_step_handle_error_3yc_minimum_quantity_consumables(
    mocker, mock_mpt_client, mock_order, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.INVALID_MINIMUM_QUANTITY.value,
            message="Minimum quantity out of range",
            details=["CONSUMABLES"],
        ),
    )
    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query",
    )
    context = Context(order=mock_order)
    step = CreateCustomer()

    step.handle_error(mock_mpt_client, context, error)  # act

    param_consumables = get_ordering_parameter(context.order, Param.THREE_YC_CONSUMABLES.value)
    assert param_consumables["error"] == ERR_3YC_QUANTITY_CONSUMABLES.to_dict(
        title=param_consumables["name"],
    )
    mocked_switch_to_query.assert_called_once_with(mock_mpt_client, context.order)


def test_create_customer_step_handle_error_3yc_minimum_quantity_no_minimums(
    mocker, mock_mpt_client, mock_order, adobe_api_error_factory
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.INVALID_MINIMUM_QUANTITY.value,
            message="Minimum quantity out of range",
            details=[],
        ),
    )
    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query"
    )
    context = Context(order=mock_order)
    step = CreateCustomer()

    step.handle_error(mock_mpt_client, context, error)  # act

    param_licenses = get_ordering_parameter(context.order, Param.THREE_YC_LICENSES.value)
    param_consumables = get_ordering_parameter(context.order, Param.THREE_YC_CONSUMABLES.value)
    assert context.order["error"] == ERR_3YC_NO_MINIMUMS.to_dict(
        title_min_licenses=param_licenses["name"],
        title_min_consumables=param_consumables["name"],
    )
    mocked_switch_to_query.assert_called_once_with(mock_mpt_client, context.order)


@pytest.mark.parametrize(
    ("param_external_id", "error_constant", "error_details"),
    [
        ("contact", ERR_ADOBE_CONTACT, "companyProfile.contacts[0].firstName"),
        ("companyName", ERR_ADOBE_COMPANY_NAME, "companyProfile.companyName"),
    ],
)
def test_create_customer_step_handle_error_invalid_fields(
    mocker,
    mock_mpt_client,
    adobe_api_error_factory,
    mock_order,
    param_external_id,
    error_constant,
    error_details,
):
    error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.INVALID_FIELDS.value,
            message="Invalid fields",
            details=[error_details],
        ),
    )
    mocked_switch_to_query = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.switch_order_to_query"
    )
    context = Context(order=mock_order)
    step = CreateCustomer()

    step.handle_error(mock_mpt_client, context, error)  # act

    param = get_ordering_parameter(context.order, Param.ADDRESS.value)
    assert param["error"] == ERR_ADOBE_ADDRESS.to_dict(title=param["name"], details=str(error))
    mocked_switch_to_query.assert_called_once_with(mock_mpt_client, context.order)


@pytest.mark.parametrize(
    "status",
    [AdobeCustomerStatus.ACTIVE, AdobeCustomerStatus.INACTIVE],
)
def test_check_account_status_step_continues(
    status,
    requests_mocker,
    mock_adobe_client,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
    purchase_template,
):
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    order = order_factory(template=purchase_template)
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={**adobe_customer_factory(), "status": status.value},
    )
    step = CheckAccountStatus()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_called_once_with(mpt_client, context)
    assert context.order == order
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
    ]
    assert mock_adobe_client.mock_calls == []


@pytest.mark.parametrize("product_templates", [[{"id": "TPL-0000", "name": "Default"}], []])
def test_check_account_status_step_continues_when_screening_template_missing(
    product_templates,
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_url_factory,
    processing_template_response_factory,
):
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, product_templates)
    order = order_factory(template={"id": "TPL-0000", "name": "Default"})
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={**adobe_customer_factory(), "status": AdobeCustomerStatus.ACTIVE.value},
    )
    step = CheckAccountStatus()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_called_once_with(mpt_client, context)
    assert context.order == order
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
    ]


def test_check_account_status_step_restores_purchase_template(
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
    purchase_template,
):
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    processing_template_response_factory(TEMPLATE_NAME_PURCHASE, [purchase_template])
    order = order_factory(template={"id": screening_template["id"]})
    order_url = f"https://localhost/public/v1/commerce/orders/{order['id']}"
    mocked_update_order = requests_mocker.put(order_url, json={})
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={**adobe_customer_factory(), "status": AdobeCustomerStatus.ACTIVE.value},
    )
    step = CheckAccountStatus()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_called_once_with(mpt_client, context)
    assert context.order["template"] == purchase_template
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
        ("GET", processing_template_url_factory(TEMPLATE_NAME_PURCHASE)),
        ("PUT", order_url),
    ]
    assert json.loads(mocked_update_order.calls[0].request.body) == {"template": purchase_template}


@pytest.mark.parametrize(
    "lookup_error_response",
    [
        pytest.param(
            {"status": 500, "json": {"status": 500, "title": "Internal Server Error"}},
            id="http_500",
        ),
        pytest.param({"body": requests.ConnectionError("connection reset")}, id="connection_error"),
    ],
)
def test_check_account_status_step_continues_when_template_lookup_fails(
    lookup_error_response,
    caplog,
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_url_factory,
    screening_template,
):
    requests_mocker.get(
        processing_template_url_factory(TEMPLATE_NAME_SCREENING), **lookup_error_response
    )
    order = order_factory(template=screening_template)
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={**adobe_customer_factory(), "status": AdobeCustomerStatus.ACTIVE.value},
    )
    step = CheckAccountStatus()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_called_once_with(mpt_client, context)
    assert context.order == order
    assert "failed to restore the Purchase template" in caplog.text


def test_check_account_status_step_continues_when_template_update_fails(
    caplog,
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_response_factory,
    screening_template,
    purchase_template,
):
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    processing_template_response_factory(TEMPLATE_NAME_PURCHASE, [purchase_template])
    order = order_factory(template=screening_template)
    requests_mocker.put(
        f"https://localhost/public/v1/commerce/orders/{order['id']}",
        status=500,
        json={"status": 500, "title": "Internal Server Error"},
    )
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={**adobe_customer_factory(), "status": AdobeCustomerStatus.ACTIVE.value},
    )
    step = CheckAccountStatus()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_called_once_with(mpt_client, context)
    assert context.order["template"] == screening_template
    assert "failed to restore the Purchase template" in caplog.text


def test_check_account_status_step_restores_default_template_when_purchase_template_missing(
    caplog,
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
):
    default_template = {"id": "TPL-0000", "name": "Default"}
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    processing_template_response_factory(TEMPLATE_NAME_PURCHASE, [default_template])
    order = order_factory(template=screening_template)
    order_url = f"https://localhost/public/v1/commerce/orders/{order['id']}"
    mocked_update_order = requests_mocker.put(order_url, json={})
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={**adobe_customer_factory(), "status": AdobeCustomerStatus.ACTIVE.value},
    )
    step = CheckAccountStatus()

    with caplog.at_level("WARNING"):
        step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_called_once_with(mpt_client, context)
    assert context.order["template"] == default_template
    assert json.loads(mocked_update_order.calls[0].request.body) == {"template": default_template}
    assert "template Purchase not found for product PRD-1111-1111" in caplog.text


def test_check_account_status_step_keeps_template_when_no_processing_template(
    caplog,
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
):
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    processing_template_response_factory(TEMPLATE_NAME_PURCHASE, [])
    order = order_factory(template=screening_template)
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={**adobe_customer_factory(), "status": AdobeCustomerStatus.ACTIVE.value},
    )
    step = CheckAccountStatus()

    with caplog.at_level("WARNING"):
        step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_called_once_with(mpt_client, context)
    assert context.order == order
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
        ("GET", processing_template_url_factory(TEMPLATE_NAME_PURCHASE)),
    ]
    assert "no processing template found for product PRD-1111-1111" in caplog.text


@pytest.mark.parametrize("order_template", [{"id": "TPL-1234"}, None])
def test_check_account_status_step_screening_sets_template(
    order_template,
    requests_mocker,
    mock_adobe_client,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
):
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    order = order_factory(template=order_template)
    order_url = f"https://localhost/public/v1/commerce/orders/{order['id']}"
    mocked_update_order = requests_mocker.put(order_url, json={})
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={
            **adobe_customer_factory(),
            "status": AdobeCustomerStatus.SCREENING.value,
        },
    )
    step = CheckAccountStatus()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_not_called()
    assert context.order["template"] == screening_template
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
        ("PUT", order_url),
    ]
    assert json.loads(mocked_update_order.calls[0].request.body) == {"template": screening_template}
    assert mock_adobe_client.mock_calls == []


def test_check_account_status_step_screening_template_already_set(
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
):
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    order = order_factory(template={"id": screening_template["id"]})
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={
            **adobe_customer_factory(),
            "status": AdobeCustomerStatus.SCREENING.value,
        },
    )
    step = CheckAccountStatus()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_not_called()
    assert context.order == order
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
    ]


@pytest.mark.parametrize("product_templates", [[{"id": "TPL-0000", "name": "Default"}], []])
def test_check_account_status_step_screening_template_missing(
    product_templates,
    caplog,
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_url_factory,
    processing_template_response_factory,
    purchase_template,
):
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, product_templates)
    order = order_factory(template=purchase_template)
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={
            **adobe_customer_factory(),
            "status": AdobeCustomerStatus.SCREENING.value,
        },
    )
    step = CheckAccountStatus()

    with caplog.at_level("WARNING"):
        step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_not_called()
    assert context.order == order
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
    ]
    assert "template Screening not found for product PRD-1111-1111" in caplog.text


@pytest.mark.parametrize(
    "lookup_error_response",
    [
        pytest.param(
            {"status": 500, "json": {"status": 500, "title": "Internal Server Error"}},
            id="http_500",
        ),
        pytest.param({"body": requests.ConnectionError("connection reset")}, id="connection_error"),
    ],
)
def test_check_account_status_step_screening_waits_when_template_lookup_fails(
    lookup_error_response,
    caplog,
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    adobe_customer_factory,
    processing_template_url_factory,
    purchase_template,
):
    requests_mocker.get(
        processing_template_url_factory(TEMPLATE_NAME_SCREENING), **lookup_error_response
    )
    order = order_factory(template=purchase_template)
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={
            **adobe_customer_factory(),
            "status": AdobeCustomerStatus.SCREENING.value,
        },
    )
    step = CheckAccountStatus()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_not_called()
    assert context.order == order
    assert "failed to set the Screening template" in caplog.text


def test_check_account_status_step_pending(
    mocker, mock_adobe_client, mock_mpt_client, mock_next_step, mock_order, adobe_customer_factory
):
    mocked_update_order = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.update_order", autospec=True
    )
    context = Context(
        order=mock_order,
        adobe_customer_id="a-client-id",
        adobe_customer={
            **adobe_customer_factory(),
            "status": AdobeCustomerStatus.PENDING.value,
        },
    )
    step = CheckAccountStatus()

    step(mock_mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_not_called()
    mocked_update_order.assert_not_called()
    assert context.order == mock_order
    assert mock_mpt_client.mock_calls == []
    assert mock_adobe_client.mock_calls == []


@pytest.fixture
def mock_mark_order_as_failed(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.purchase.mark_order_as_failed", autospec=True)


@pytest.fixture
def mock_purchase_send_error(mocker):
    return mocker.patch("adobe_vipm.flows.fulfillment.purchase.send_error", autospec=True)


@pytest.fixture
def compliance_block_context(mock_order, adobe_customer_factory):
    return Context(
        order=mock_order,
        order_id=mock_order["id"],
        agreement_id=mock_order["agreement"]["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={
            **adobe_customer_factory(),
            "status": AdobeCustomerStatus.COMPLIANCE_BLOCK.value,
        },
    )


def test_check_account_status_step_compliance_block(
    caplog,
    mock_mpt_client,
    mock_next_step,
    mock_order,
    mock_mark_order_as_failed,
    mock_purchase_send_error,
    compliance_block_context,
):
    caplog.set_level(logging.ERROR, logger="adobe_vipm.flows.fulfillment.purchase")
    step = CheckAccountStatus()

    step(mock_mpt_client, compliance_block_context, mock_next_step)  # act

    mock_next_step.assert_not_called()
    mock_mark_order_as_failed.assert_called_once_with(
        mock_mpt_client,
        mock_order,
        {
            "id": "VIPM0060",
            "message": (
                "Account creation failed during screening as part of Adobe's ongoing trade "
                "compliance program. Please contact your SoftwareOne representative."
            ),
        },
    )
    assert caplog.messages == [
        (
            f"{compliance_block_context}: Adobe customer a-client-id is in compliance block, "
            f"order {mock_order['id']} of agreement {mock_order['agreement']['id']} failed"
        ),
    ]
    mock_purchase_send_error.assert_called_once_with(
        "Adobe account compliance block",
        f"The order **{mock_order['id']}** has been failed because Adobe blocked the new "
        "customer account **a-client-id** during its trade compliance screening.",
        facts=FactsSection(
            "Blocked account",
            {
                "Order": mock_order["id"],
                "Agreement": mock_order["agreement"]["id"],
                "Adobe customer": "a-client-id",
            },
        ),
    )


def test_check_account_status_step_compliance_block_fail_order_error(
    caplog,
    mock_mpt_client,
    mock_next_step,
    mock_mark_order_as_failed,
    mock_purchase_send_error,
    compliance_block_context,
):
    caplog.set_level(logging.ERROR, logger="adobe_vipm.flows.fulfillment.purchase")
    mock_mark_order_as_failed.side_effect = RuntimeError("update failed")
    step = CheckAccountStatus()

    with pytest.raises(RuntimeError, match="update failed"):
        step(mock_mpt_client, compliance_block_context, mock_next_step)

    mock_purchase_send_error.assert_not_called()
    assert caplog.messages == []


@freeze_time("2025-01-05")
@pytest.mark.parametrize("due_date", [None, "2025-01-04", "2025-01-10", "2025-02-03"])
def test_roll_screening_due_date_step(
    due_date,
    requests_mocker,
    mpt_client,
    mock_adobe_client,
    mock_next_step,
    order_factory,
    fulfillment_parameters_factory,
    adobe_customer_factory,
):
    order = order_factory(fulfillment_parameters=fulfillment_parameters_factory(due_date=due_date))
    order_url = f"https://localhost/public/v1/commerce/orders/{order['id']}"
    requests_mocker.put(order_url, json={})
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={
            **adobe_customer_factory(),
            "status": AdobeCustomerStatus.SCREENING.value,
        },
    )
    step = RollScreeningDueDate()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_called_once_with(mpt_client, context)
    assert get_due_date(context.order) == dt.date(2025, 2, 4)
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("PUT", order_url),
    ]
    sent_due_date = get_fulfillment_parameter(
        json.loads(requests_mocker.calls[0].request.body), Param.DUE_DATE.value
    )
    assert sent_due_date["value"] == "2025-02-04"
    assert mock_adobe_client.mock_calls == []


@freeze_time("2025-01-05")
def test_roll_screening_due_date_step_already_rolled(
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    fulfillment_parameters_factory,
    adobe_customer_factory,
):
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(due_date="2025-02-04")
    )
    context = Context(
        order=order,
        order_id=order["id"],
        adobe_customer_id="a-client-id",
        adobe_customer={
            **adobe_customer_factory(),
            "status": AdobeCustomerStatus.SCREENING.value,
        },
    )
    step = RollScreeningDueDate()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_called_once_with(mpt_client, context)
    assert context.order == order
    assert len(requests_mocker.calls) == 0


@freeze_time("2025-01-05")
@pytest.mark.parametrize(
    "adobe_customer",
    [
        None,
        {"status": AdobeCustomerStatus.PENDING.value},
        {"status": AdobeCustomerStatus.ACTIVE.value},
        {"status": AdobeCustomerStatus.COMPLIANCE_BLOCK.value},
    ],
)
def test_roll_screening_due_date_step_not_in_screening(
    adobe_customer,
    requests_mocker,
    mpt_client,
    mock_next_step,
    order_factory,
    fulfillment_parameters_factory,
):
    order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(due_date="2025-01-10")
    )
    context = Context(order=order, order_id=order["id"], adobe_customer=adobe_customer)
    step = RollScreeningDueDate()

    step(mpt_client, context, mock_next_step)  # act

    mock_next_step.assert_called_once_with(mpt_client, context)
    assert context.order == order
    assert len(requests_mocker.calls) == 0


def test_purchase_pipeline_first_run_account_pending(
    requests_mocker,
    settings,
    mpt_client,
    purchase_context,
    adobe_http_client,
    adobe_customer_factory,
):
    adobe_api_url = settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"]
    requests_mocker.post(
        urljoin(adobe_api_url, "/v3/customers"),
        status=201,
        json={**adobe_customer_factory(), "status": AdobeCustomerStatus.PENDING.value},
    )
    requests_mocker.put(
        f"https://localhost/public/v1/commerce/orders/{purchase_context.order_id}", json={}
    )
    requests_mocker.put(
        f"https://localhost/public/v1/commerce/agreements/{purchase_context.agreement_id}",
        json={},
    )
    pipeline = Pipeline(
        CreateCustomer(),
        CheckAccountStatus(),
        GetPreviewOrder(),
        SubmitNewOrder(),
    )

    pipeline.run(mpt_client, purchase_context)  # act

    assert get_adobe_customer_id(purchase_context.order) == "a-client-id"
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("POST", urljoin(adobe_api_url, "/v3/customers")),
        ("PUT", f"https://localhost/public/v1/commerce/orders/{purchase_context.order_id}"),
        (
            "PUT",
            f"https://localhost/public/v1/commerce/agreements/{purchase_context.agreement_id}",
        ),
    ]


def test_purchase_pipeline_later_run_account_pending(
    requests_mocker, mpt_client, purchase_context, adobe_http_client, adobe_customer_factory
):
    purchase_context.adobe_customer_id = "a-client-id"
    purchase_context.adobe_customer = {
        **adobe_customer_factory(),
        "status": AdobeCustomerStatus.PENDING.value,
    }
    pipeline = Pipeline(
        CreateCustomer(),
        CheckAccountStatus(),
        GetPreviewOrder(),
        SubmitNewOrder(),
    )

    pipeline.run(mpt_client, purchase_context)  # act

    assert len(requests_mocker.calls) == 0


@freeze_time("2025-01-05")
@pytest.mark.parametrize("due_date", ["2025-01-04", "2025-02-03"])
def test_purchase_pipeline_later_run_account_screening_rolls_due_date(
    due_date,
    requests_mocker,
    mpt_client,
    purchase_context,
    adobe_http_client,
    adobe_customer_factory,
    order_factory,
    fulfillment_parameters_factory,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
):
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    order_url = f"https://localhost/public/v1/commerce/orders/{purchase_context.order_id}"
    requests_mocker.put(order_url, json={})
    purchase_context.order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(due_date=due_date)
    )
    purchase_context.order["template"] = screening_template
    purchase_context.adobe_customer_id = "a-client-id"
    purchase_context.adobe_customer = {
        **adobe_customer_factory(),
        "status": AdobeCustomerStatus.SCREENING.value,
    }
    pipeline = Pipeline(
        RollScreeningDueDate(),
        SetupDueDate(),
        CreateCustomer(),
        CheckAccountStatus(),
        GetPreviewOrder(),
        SubmitNewOrder(),
    )

    pipeline.run(mpt_client, purchase_context)  # act

    assert get_due_date(purchase_context.order) == dt.date(2025, 2, 4)
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("PUT", order_url),
        ("PUT", order_url),
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
    ]


@freeze_time("2025-01-05")
def test_purchase_pipeline_later_run_account_pending_due_date_reached(
    mocker,
    requests_mocker,
    mpt_client,
    purchase_context,
    adobe_http_client,
    adobe_customer_factory,
    order_factory,
    fulfillment_parameters_factory,
):
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed", autospec=True
    )
    purchase_context.order = order_factory(
        fulfillment_parameters=fulfillment_parameters_factory(due_date="2025-01-04")
    )
    purchase_context.adobe_customer_id = "a-client-id"
    purchase_context.adobe_customer = {
        **adobe_customer_factory(),
        "status": AdobeCustomerStatus.PENDING.value,
    }
    pipeline = Pipeline(
        RollScreeningDueDate(),
        SetupDueDate(),
        CreateCustomer(),
        CheckAccountStatus(),
        GetPreviewOrder(),
        SubmitNewOrder(),
    )

    pipeline.run(mpt_client, purchase_context)  # act

    mocked_switch_to_failed.assert_called_once_with(
        mpt_client,
        purchase_context.order,
        ERR_DUE_DATE_REACHED.to_dict(due_date="2025-01-04"),
    )
    assert len(requests_mocker.calls) == 0


def test_purchase_pipeline_later_run_account_active(
    requests_mocker,
    settings,
    mpt_client,
    purchase_context,
    adobe_http_client,
    adobe_customer_factory,
    adobe_order_factory,
    mock_get_adobe_product_by_marketplace_sku,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
):
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    adobe_orders_url = urljoin(
        settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/customers/a-client-id/orders"
    )
    requests_mocker.post(
        adobe_orders_url,
        status=200,
        json=adobe_order_factory(order_type=ORDER_TYPE_PREVIEW),
    )
    requests_mocker.post(
        adobe_orders_url,
        status=202,
        json=adobe_order_factory(order_type=ORDER_TYPE_NEW, status=AdobeOrderStatus.OPEN.value),
    )
    requests_mocker.put(
        f"https://localhost/public/v1/commerce/orders/{purchase_context.order_id}", json={}
    )
    purchase_context.adobe_customer_id = "a-client-id"
    purchase_context.adobe_customer = {
        **adobe_customer_factory(),
        "status": AdobeCustomerStatus.ACTIVE.value,
    }
    pipeline = Pipeline(
        CreateCustomer(),
        CheckAccountStatus(),
        GetPreviewOrder(),
        SubmitNewOrder(),
    )

    pipeline.run(mpt_client, purchase_context)  # act

    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
        ("POST", f"{adobe_orders_url}?fetch-price=true"),
        ("POST", adobe_orders_url),
        ("PUT", f"https://localhost/public/v1/commerce/orders/{purchase_context.order_id}"),
    ]


def test_purchase_pipeline_first_run_account_screening(
    requests_mocker,
    settings,
    mpt_client,
    purchase_context,
    adobe_http_client,
    adobe_customer_factory,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
    purchase_template,
):
    adobe_customers_url = urljoin(settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/customers")
    requests_mocker.post(
        adobe_customers_url,
        status=201,
        json={**adobe_customer_factory(), "status": AdobeCustomerStatus.SCREENING.value},
    )
    processing_template_response_factory(TEMPLATE_NAME_PURCHASE, [purchase_template])
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    order_url = f"https://localhost/public/v1/commerce/orders/{purchase_context.order_id}"
    agreement_url = (
        f"https://localhost/public/v1/commerce/agreements/{purchase_context.agreement_id}"
    )
    mocked_update_order = requests_mocker.put(order_url, json={})
    requests_mocker.put(agreement_url, json={})
    purchase_context.order["template"] = purchase_template
    pipeline = Pipeline(
        StartOrderProcessing(TEMPLATE_NAME_PURCHASE, template_to_keep=TEMPLATE_NAME_SCREENING),
        CreateCustomer(),
        CheckAccountStatus(),
        GetPreviewOrder(),
        SubmitNewOrder(),
    )

    pipeline.run(mpt_client, purchase_context)  # act

    assert get_adobe_customer_id(purchase_context.order) == "a-client-id"
    assert purchase_context.order["template"] == screening_template
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_PURCHASE)),
        ("POST", adobe_customers_url),
        ("PUT", order_url),
        ("PUT", agreement_url),
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
        ("PUT", order_url),
    ]
    assert json.loads(mocked_update_order.calls[1].request.body) == {"template": screening_template}


def test_purchase_pipeline_later_run_account_screening(
    requests_mocker,
    mpt_client,
    purchase_context,
    adobe_http_client,
    adobe_customer_factory,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
    purchase_template,
):
    processing_template_response_factory(TEMPLATE_NAME_PURCHASE, [purchase_template])
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    purchase_context.order["template"] = screening_template
    purchase_context.adobe_customer_id = "a-client-id"
    purchase_context.adobe_customer = {
        **adobe_customer_factory(),
        "status": AdobeCustomerStatus.SCREENING.value,
    }
    pipeline = Pipeline(
        StartOrderProcessing(TEMPLATE_NAME_PURCHASE, template_to_keep=TEMPLATE_NAME_SCREENING),
        CreateCustomer(),
        CheckAccountStatus(),
        GetPreviewOrder(),
        SubmitNewOrder(),
    )

    pipeline.run(mpt_client, purchase_context)  # act

    assert purchase_context.order["template"] == screening_template
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_PURCHASE)),
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
    ]


def test_purchase_pipeline_account_active_after_screening(
    requests_mocker,
    settings,
    mpt_client,
    purchase_context,
    adobe_http_client,
    adobe_customer_factory,
    adobe_order_factory,
    mock_get_adobe_product_by_marketplace_sku,
    processing_template_url_factory,
    processing_template_response_factory,
    screening_template,
    purchase_template,
):
    processing_template_response_factory(TEMPLATE_NAME_PURCHASE, [purchase_template])
    processing_template_response_factory(TEMPLATE_NAME_SCREENING, [screening_template])
    adobe_orders_url = urljoin(
        settings.EXTENSION_CONFIG["ADOBE_API_BASE_URL"], "/v3/customers/a-client-id/orders"
    )
    requests_mocker.post(
        adobe_orders_url,
        status=200,
        json=adobe_order_factory(order_type=ORDER_TYPE_PREVIEW),
    )
    requests_mocker.post(
        adobe_orders_url,
        status=202,
        json=adobe_order_factory(order_type=ORDER_TYPE_NEW, status=AdobeOrderStatus.OPEN.value),
    )
    order_url = f"https://localhost/public/v1/commerce/orders/{purchase_context.order_id}"
    mocked_update_order = requests_mocker.put(order_url, json={})
    purchase_context.order["template"] = screening_template
    purchase_context.adobe_customer_id = "a-client-id"
    purchase_context.adobe_customer = {
        **adobe_customer_factory(),
        "status": AdobeCustomerStatus.ACTIVE.value,
    }
    pipeline = Pipeline(
        StartOrderProcessing(TEMPLATE_NAME_PURCHASE, template_to_keep=TEMPLATE_NAME_SCREENING),
        CreateCustomer(),
        CheckAccountStatus(),
        GetPreviewOrder(),
        SubmitNewOrder(),
    )

    pipeline.run(mpt_client, purchase_context)  # act

    assert purchase_context.order["template"] == purchase_template
    assert [(call.request.method, call.request.url) for call in requests_mocker.calls] == [
        ("GET", processing_template_url_factory(TEMPLATE_NAME_PURCHASE)),
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
        ("GET", processing_template_url_factory(TEMPLATE_NAME_SCREENING)),
        ("GET", processing_template_url_factory(TEMPLATE_NAME_PURCHASE)),
        ("PUT", order_url),
        ("POST", f"{adobe_orders_url}?fetch-price=true"),
        ("POST", adobe_orders_url),
        ("PUT", order_url),
    ]
    assert json.loads(mocked_update_order.calls[0].request.body) == {"template": purchase_template}


def test_fulfill_purchase_order(mocker, mock_mpt_client, mock_order):
    mocked_pipeline_instance = mocker.MagicMock()
    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.purchase.Context", return_value=mocked_context
    )

    fulfill_purchase_order(mock_mpt_client, mock_order)  # act

    expected_steps = [
        SetupContext,
        DiscardCarriedOverFlexDiscounts,
        StartOrderProcessing,
        RollScreeningDueDate,
        SetupDueDate,
        ValidateDuplicateLines,
        ValidateGovernmentLGA,
        PrepareCustomerData,
        CreateCustomer,
        CheckAccountStatus,
        ValidateEducationSubSegments,
        Validate3YCCommitment,
        SelectFlexDiscounts,
        GetPreviewOrder,
        UpdatePrices,
        SubmitNewOrder,
        CreateOrUpdateAssets,
        CreateOrUpdateSubscriptions,
        RefreshCustomer,
        SetOrUpdateCotermDate,
        UpdateAgreementParamsVisibility,
        CompleteOrder,
        RecordDiscountRedemptions,
        NullifyFlexDiscountParam,
        SyncAgreement,
    ]
    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args]
    assert actual_steps == expected_steps
    assert mocked_pipeline_ctor.mock_calls[0].args[2].template_name == TEMPLATE_NAME_PURCHASE
    assert mocked_pipeline_ctor.mock_calls[0].args[2].template_to_keep == TEMPLATE_NAME_SCREENING
    assert mocked_pipeline_ctor.mock_calls[0].args[21].template_name == TEMPLATE_NAME_PURCHASE
    mocked_context_ctor.assert_called_once_with(order=mock_order)
    mocked_pipeline_instance.run.assert_called_once_with(mock_mpt_client, mocked_context)
