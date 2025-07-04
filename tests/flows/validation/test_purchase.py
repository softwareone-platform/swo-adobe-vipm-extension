import pytest

from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
    ERR_ADDRESS,
    ERR_ADDRESS_LINE_1_LENGTH,
    ERR_ADDRESS_LINE_2_LENGTH,
    ERR_CITY_LENGTH,
    ERR_COMPANY_NAME_CHARS,
    ERR_COMPANY_NAME_LENGTH,
    ERR_CONTACT,
    ERR_COUNTRY_CODE,
    ERR_EMAIL_FORMAT,
    ERR_FIRST_NAME_FORMAT,
    ERR_LAST_NAME_FORMAT,
    ERR_PHONE_NUMBER_LENGTH,
    ERR_POSTAL_CODE_FORMAT,
    ERR_POSTAL_CODE_LENGTH,
    ERR_STATE_OR_PROVINCE,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.helpers import PrepareCustomerData, SetupContext, Validate3YCCommitment
from adobe_vipm.flows.utils import get_customer_data, get_ordering_parameter
from adobe_vipm.flows.validation.purchase import (
    CheckPurchaseValidationEnabled,
    UpdatePrices,
    ValidateCustomerData,
    validate_purchase_order,
)
from adobe_vipm.flows.validation.shared import GetPreviewOrder, ValidateDuplicateLines

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


@pytest.mark.parametrize(
    "company_name",
    [
        "Hill, Patterson and Simpson, Tuc-Dixon & Garza, Phelps Inc",
        "Bart",
        "Schneider 1997",
        "ELA L・L GEMINADA SL",
        "(Paren_tesi S.p.A.)",
        'Herma\\nos "Preciosos" SAU',
        "Precios/os 'Hermanos' SAU",
    ],
)
def test_validate_company_name(order_factory, order_parameters_factory, company_name):
    """
    Tests the validation of the Company name when it is valid.
    """
    order = order_factory(order_parameters=order_parameters_factory(company_name=company_name))
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_company_name(context)

    assert context.validation_succeeded is True

    param = get_ordering_parameter(context.order, Param.COMPANY_NAME)
    assert "error" not in param


@pytest.mark.parametrize(
    "company_name",
    [
        "Hill, Patterson and Simpson, Tuc-Dixon & Garza, Phelps & Maria Addolorata Inc",
        "Bar",
    ],
)
def test_validate_company_name_invalid_length(
    order_factory, order_parameters_factory, company_name
):
    """
    Tests the validation of the Company name when it is invalid due to length.
    """
    order = order_factory(order_parameters=order_parameters_factory(company_name=company_name))
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_company_name(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(context.order, Param.COMPANY_NAME)
    assert param["error"] == ERR_COMPANY_NAME_LENGTH.to_dict(title=param["name"])
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


@pytest.mark.parametrize(
    "company_name",
    [
        "Felici ☺ SRL",
        "Quasimodo $ 23",
        "Euro € Company",
        "Star * of the Sky",
    ],
)
def test_validate_company_name_invalid_chars(order_factory, order_parameters_factory, company_name):
    """
    Tests the validation of the Company name when it is invalid due to chars.
    """
    order = order_factory(order_parameters=order_parameters_factory(company_name=company_name))
    customer_data = get_customer_data(order)
    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_company_name(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(context.order, Param.COMPANY_NAME)
    assert param["error"] == ERR_COMPANY_NAME_CHARS.to_dict(title=param["name"])
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


@pytest.mark.parametrize("state_or_province", ["CA", "California", "Californio"])
@pytest.mark.parametrize("address_line_2", ["", "a value"])
def test_validate_address(order_factory, address_line_2, state_or_province):
    """
    Tests the validation of a valid address.
    """
    order = order_factory()
    customer_data = get_customer_data(order)
    customer_data[Param.ADDRESS]["addressLine2"] = address_line_2
    customer_data[Param.ADDRESS]["state"] = state_or_province
    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_address(context)

    assert context.validation_succeeded is True

    param = get_ordering_parameter(
        context.order,
        Param.ADDRESS,
    )
    assert "error" not in param


def test_validate_address_invalid_country(order_factory, order_parameters_factory):
    """
    Tests the validation of an address when the country is invalid.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(
            address={
                "country": "ES",
                "state": "B",
                "city": "Barcelona",
                "addressLine1": "Plaza Catalunya 1",
                "addressLine2": "1o 1a",
                "postCode": "08001",
            },
        )
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_address(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.ADDRESS,
    )
    assert param["error"] == ERR_ADDRESS.to_dict(
        title=param["name"],
        errors=ERR_COUNTRY_CODE,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_address_invalid_state(order_factory, order_parameters_factory):
    """
    Tests the validation of an address when the state or province is invalid.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(
            address={
                "country": "US",
                "state": "ZZ",
                "city": "San Jose",
                "addressLine1": "3601 Lyon St",
                "addressLine2": "",
                "postCode": "94123",
            },
        )
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_address(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.ADDRESS,
    )
    assert param["error"] == ERR_ADDRESS.to_dict(
        title=param["name"],
        errors=ERR_STATE_OR_PROVINCE,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_address_invalid_state_did_u_mean(order_factory, order_parameters_factory):
    order = order_factory(
        order_parameters=order_parameters_factory(
            address={
                "country": "US",
                "state": "Coliflornia",
                "city": "San Jose",
                "addressLine1": "3601 Lyon St",
                "addressLine2": "",
                "postCode": "94123",
            },
        )
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_address(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.ADDRESS,
    )
    error = f"{ERR_STATE_OR_PROVINCE} (Did you mean California, Colorado ?)"
    assert param["error"] == ERR_ADDRESS.to_dict(
        title=param["name"],
        errors=error,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_address_invalid_postal_code(order_factory, order_parameters_factory):
    """
    Tests the validation of an address when the postal code doesn't match
    the expected pattern.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(
            address={
                "country": "US",
                "state": "CA",
                "city": "San Jose",
                "addressLine1": "3601 Lyon St",
                "addressLine2": "",
                "postCode": "9412312",
            },
        )
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_address(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.ADDRESS,
    )
    assert param["error"] == ERR_ADDRESS.to_dict(
        title=param["name"],
        errors=ERR_POSTAL_CODE_FORMAT,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_address_invalid_postal_code_length(order_factory, order_parameters_factory):
    """
    Tests the validation of an address when the postal code doesn't match
    the expected length.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(
            address={
                "country": "VU",
                "state": "TOB",
                "city": "Lalala",
                "addressLine1": "Blah blah",
                "addressLine2": "",
                "postCode": "9" * 41,
            },
        )
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_address(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.ADDRESS,
    )
    assert param["error"] == ERR_ADDRESS.to_dict(
        title=param["name"],
        errors=ERR_POSTAL_CODE_LENGTH,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_address_invalid_others(order_factory, order_parameters_factory):
    """
    Tests the validation of an address when address lines or city exceed the the
    maximum allowed length.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(
            address={
                "country": "VU",
                "state": "TOB",
                "city": "C" * 41,
                "addressLine1": "1" * 61,
                "addressLine2": "2" * 61,
                "postCode": "",
            },
        )
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_address(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.ADDRESS,
    )

    assert param["error"] == ERR_ADDRESS.to_dict(
        title=param["name"],
        errors="; ".join(
            (
                ERR_ADDRESS_LINE_1_LENGTH,
                ERR_CITY_LENGTH,
                ERR_ADDRESS_LINE_2_LENGTH,
            ),
        ),
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_contact(order_factory):
    """
    Tests the validation of a valid contact.
    """
    order = order_factory()
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_contact(context)

    assert context.validation_succeeded is True

    param = get_ordering_parameter(
        context.order,
        Param.CONTACT,
    )
    assert "error" not in param


def test_validate_contact_mandatory(order_factory, order_parameters_factory):
    order = order_factory(
        order_parameters=order_parameters_factory(
            contact={},
        ),
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_contact(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.CONTACT,
    )
    assert param["error"] == ERR_CONTACT.to_dict(
        title=param["name"],
        errors="it is mandatory.",
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_contact_invalid_first_name(order_factory, order_parameters_factory):
    """
    Tests the validation of a contact when the first name is invalid.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(
            contact={
                "firstName": "First N@m€",
                "lastName": "Last Name",
                "email": "test@example.com",
            },
        ),
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_contact(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.CONTACT,
    )
    assert param["error"] == ERR_CONTACT.to_dict(
        title=param["name"],
        errors=ERR_FIRST_NAME_FORMAT,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_contact_invalid_last_name(order_factory, order_parameters_factory):
    """
    Tests the validation of a contact when the last name is invalid.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(
            contact={
                "firstName": "First Name",
                "lastName": "L@ast N@m€",
                "email": "test@example.com",
            },
        ),
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_contact(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.CONTACT,
    )
    assert param["error"] == ERR_CONTACT.to_dict(
        title=param["name"],
        errors=ERR_LAST_NAME_FORMAT,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_contact_invalid_email(order_factory, order_parameters_factory):
    """
    Tests the validation of a contact when the email is invalid.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(
            contact={
                "firstName": "First Name",
                "lastName": "Last Name",
                "email": "test_example.com",
            },
        ),
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_contact(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.CONTACT,
    )
    assert param["error"] == ERR_CONTACT.to_dict(
        title=param["name"],
        errors=ERR_EMAIL_FORMAT,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_contact_invalid_phone(order_factory, order_parameters_factory):
    """
    Tests the validation of a contact when the phone is invalid.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(
            contact={
                "firstName": "First Name",
                "lastName": "Last Name",
                "email": "test@example.com",
                "phone": {
                    "prefix": "+1",
                    "number": "4082954078" * 5,
                },
            },
        ),
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_contact(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        Param.CONTACT,
    )
    assert param["error"] == ERR_CONTACT.to_dict(
        title=param["name"],
        errors=ERR_PHONE_NUMBER_LENGTH,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_customer_data_step(mocker):
    """
    Test that the validation functions are invoked
    and the validation pipeline continue to the next
    step.
    """
    mocked_validate_company_name = mocker.patch.object(
        ValidateCustomerData,
        "validate_company_name",
    )
    mocked_validate_address = mocker.patch.object(
        ValidateCustomerData,
        "validate_address",
    )
    mocked_validate_contact = mocker.patch.object(
        ValidateCustomerData,
        "validate_contact",
    )
    mocked_validate_3yc = mocker.patch.object(
        ValidateCustomerData,
        "validate_3yc",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=mocker.MagicMock())

    step = ValidateCustomerData()
    step(mocked_client, context, mocked_next_step)

    mocked_validate_company_name.assert_called_once_with(context)
    mocked_validate_address.assert_called_once_with(context)
    mocked_validate_contact.assert_called_once_with(context)
    mocked_validate_3yc.assert_called_once_with(context)
    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_validate_customer_data_step_no_validate(mocker):
    """
    Test that the validation functions are invoked
    but the validation pipeline doesn't continue to the next
    step because at least one validation failed.
    """
    mocked_validate_company_name = mocker.patch.object(
        ValidateCustomerData,
        "validate_company_name",
    )
    mocked_validate_address = mocker.patch.object(
        ValidateCustomerData,
        "validate_address",
    )
    mocked_validate_contact = mocker.patch.object(
        ValidateCustomerData,
        "validate_contact",
    )
    mocked_validate_3yc = mocker.patch.object(
        ValidateCustomerData,
        "validate_3yc",
    )

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=mocker.MagicMock(), validation_succeeded=False)

    step = ValidateCustomerData()
    step(mocked_client, context, mocked_next_step)

    mocked_validate_company_name.assert_called_once_with(context)
    mocked_validate_address.assert_called_once_with(context)
    mocked_validate_contact.assert_called_once_with(context)
    mocked_validate_3yc.assert_called_once_with(context)
    mocked_next_step.assert_not_called()


@pytest.mark.parametrize(
    "quantities",
    [
        {"p3yc_licenses": "11"},
        {"p3yc_consumables": "1213"},
        {"p3yc_licenses": "13", "p3yc_consumables": "2300"},
    ],
)
def test_validate_3yc(order_factory, order_parameters_factory, quantities):
    order = order_factory(
        order_parameters=order_parameters_factory(
            p3yc=["Yes"],
            **quantities,
        ),
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_3yc(context)

    assert context.validation_succeeded is True

    for param_name in (Param.THREE_YC_LICENSES, Param.THREE_YC_CONSUMABLES):
        param = get_ordering_parameter(context.order, param_name)
        assert "error" not in param


@pytest.mark.parametrize(
    ("param_name", "factory_field", "error"),
    [
        (Param.THREE_YC_LICENSES, "p3yc_licenses", ERR_3YC_QUANTITY_LICENSES),
        (Param.THREE_YC_CONSUMABLES, "p3yc_consumables", ERR_3YC_QUANTITY_CONSUMABLES),
    ],
)
@pytest.mark.parametrize("quantity", ["a", "-3"])
def test_validate_3yc_invalid(
    order_factory, order_parameters_factory, param_name, factory_field, quantity, error
):
    order = order_factory(
        order_parameters=order_parameters_factory(
            p3yc=["Yes"],
            **{factory_field: quantity},
        ),
    )
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_3yc(context)

    assert context.validation_succeeded is False

    param = get_ordering_parameter(
        context.order,
        param_name,
    )
    assert param["error"] == error.to_dict(
        title=param["name"],
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is False


def test_validate_3yc_unchecked(order_factory, order_parameters_factory):
    order = order_factory(order_parameters=order_parameters_factory())
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_3yc(context)

    assert context.validation_succeeded is True


def test_validate_3yc_empty_minimums(order_factory, order_parameters_factory):
    order = order_factory(order_parameters=order_parameters_factory(p3yc=["Yes"]))
    customer_data = get_customer_data(order)

    context = Context(
        order=order,
        customer_data=customer_data,
    )

    step = ValidateCustomerData()
    step.validate_3yc(context)

    assert context.validation_succeeded is False
    error = ERR_3YC_NO_MINIMUMS.to_dict(
        title_min_licenses="3YCLicenses",
        title_min_consumables="3YCConsumables",
    )
    assert context.order["error"] == error


def test_check_purchase_validation_enabled_step(mocker, order_factory):
    order = order_factory()

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()

    context = Context(order=order)

    step = CheckPurchaseValidationEnabled()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_called_once_with(mocked_client, context)


def test_check_purchase_validation_enabled_step_disabled(mocker, order_factory):
    order = order_factory()

    mocked_client = mocker.MagicMock()
    mocked_next_step = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.validation.purchase.is_purchase_validation_enabled",
        return_value=False,
    )

    context = Context(order=order)

    step = CheckPurchaseValidationEnabled()
    step(mocked_client, context, mocked_next_step)

    mocked_next_step.assert_not_called()


def test_validate_purchase_order(mocker):
    """Tests the validate order entrypoint function when it validates."""

    mocked_pipeline_instance = mocker.MagicMock()

    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.validation.purchase.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.validation.purchase.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    validate_purchase_order(mocked_client, mocked_order)

    assert len(mocked_pipeline_ctor.mock_calls[0].args) == 8

    expected_steps = [
        SetupContext,
        PrepareCustomerData,
        CheckPurchaseValidationEnabled,
        ValidateCustomerData,
        ValidateDuplicateLines,
        Validate3YCCommitment,
        GetPreviewOrder,
        UpdatePrices,
    ]

    actual_steps = [type(step) for step in mocked_pipeline_ctor.mock_calls[0].args]
    assert actual_steps == expected_steps

    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(
        mocked_client,
        mocked_context,
    )
