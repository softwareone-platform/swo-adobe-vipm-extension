import pytest

from adobe_vipm.flows.constants import (
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
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_LICENSES,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
)
from adobe_vipm.flows.utils import get_customer_data, get_ordering_parameter
from adobe_vipm.flows.validation.purchase import (
    validate_3yc,
    validate_address,
    validate_company_name,
    validate_contact,
    validate_customer_data,
    validate_duplicate_lines,
)

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
    order = order_factory(
        order_parameters=order_parameters_factory(company_name=company_name)
    )
    customer_data = get_customer_data(order)

    has_error, order = validate_company_name(order, customer_data)

    assert has_error is False

    param = get_ordering_parameter(order, PARAM_COMPANY_NAME)
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
    order = order_factory(
        order_parameters=order_parameters_factory(company_name=company_name)
    )
    customer_data = get_customer_data(order)
    has_error, order = validate_company_name(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(order, PARAM_COMPANY_NAME)
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
def test_validate_company_name_invalid_chars(
    order_factory, order_parameters_factory, company_name
):
    """
    Tests the validation of the Company name when it is invalid due to chars.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(company_name=company_name)
    )
    customer_data = get_customer_data(order)
    has_error, order = validate_company_name(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(order, PARAM_COMPANY_NAME)
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
    customer_data[PARAM_ADDRESS]["addressLine2"] = address_line_2
    customer_data[PARAM_ADDRESS]["state"] = state_or_province
    has_error, order = validate_address(order, customer_data)

    assert has_error is False

    param = get_ordering_parameter(
        order,
        PARAM_ADDRESS,
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

    has_error, order = validate_address(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_ADDRESS,
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

    has_error, order = validate_address(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_ADDRESS,
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

    has_error, order = validate_address(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_ADDRESS,
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

    has_error, order = validate_address(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_ADDRESS,
    )
    assert param["error"] == ERR_ADDRESS.to_dict(
        title=param["name"],
        errors=ERR_POSTAL_CODE_FORMAT,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_address_invalid_postal_code_length(
    order_factory, order_parameters_factory
):
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

    has_error, order = validate_address(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_ADDRESS,
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

    has_error, order = validate_address(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_ADDRESS,
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

    has_error, order = validate_contact(order, customer_data)

    assert has_error is False

    param = get_ordering_parameter(
        order,
        PARAM_CONTACT,
    )
    assert "error" not in param


def test_validate_contact_mandatory(order_factory, order_parameters_factory):
    order = order_factory(
        order_parameters=order_parameters_factory(
            contact={},
        ),
    )
    customer_data = get_customer_data(order)

    has_error, order = validate_contact(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_CONTACT,
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

    has_error, order = validate_contact(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_CONTACT,
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

    has_error, order = validate_contact(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_CONTACT,
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

    has_error, order = validate_contact(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_CONTACT,
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

    has_error, order = validate_contact(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_CONTACT,
    )
    assert param["error"] == ERR_CONTACT.to_dict(
        title=param["name"],
        errors=ERR_PHONE_NUMBER_LENGTH,
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["required"] is True


def test_validate_customer_data(mocker):
    """
    Test that `validate_customer_data` calls the single validation
    function in the right order and that the has_errors will be False in case of
    no errors.
    """
    order_mocks = [
        mocker.MagicMock(),
    ]
    customer_data = mocker.MagicMock()
    fn_mocks = []
    for fnname in (
        "validate_company_name",
        "validate_address",
        "validate_contact",
        "validate_3yc",
    ):
        order_mock = mocker.MagicMock()
        order_mocks.append(order_mock)
        fn_mocks.append(
            mocker.patch(
                f"adobe_vipm.flows.validation.purchase.{fnname}",
                return_value=(False, order_mock),
            ),
        )

    has_errors, order = validate_customer_data(order_mocks[0], customer_data)

    assert has_errors is False
    assert order == order_mocks[-1]

    for mock_id, fn_mock in enumerate(fn_mocks):
        fn_mock.assert_called_once_with(order_mocks[mock_id], customer_data)


@pytest.mark.parametrize(
    "no_validating_fn",
    [
        "validate_company_name",
        "validate_address",
        "validate_contact",
        "validate_3yc",
    ],
)
def test_validate_customer_data_invalid(mocker, no_validating_fn):
    """
    Test that if one of the validation returns has_errors=True the
    `validate_customer_data` function returns has_errors=True
    """
    for fnname in (
        "validate_company_name",
        "validate_address",
        "validate_contact",
        "validate_3yc",
    ):
        mocker.patch(
            f"adobe_vipm.flows.validation.purchase.{fnname}",
            return_value=(fnname == no_validating_fn, mocker.MagicMock()),
        )

    has_errors, _ = validate_customer_data(mocker.MagicMock(), mocker.MagicMock())

    assert has_errors is True


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

    has_error, order = validate_3yc(order, customer_data)

    assert has_error is False

    for param_name in (PARAM_3YC_LICENSES, PARAM_3YC_CONSUMABLES):
        param = get_ordering_parameter(order, param_name)
        assert "error" not in param


@pytest.mark.parametrize(
    ("param_name", "factory_field", "error"),
    [
        (PARAM_3YC_LICENSES, "p3yc_licenses", ERR_3YC_QUANTITY_LICENSES),
        (PARAM_3YC_CONSUMABLES, "p3yc_consumables", ERR_3YC_QUANTITY_CONSUMABLES),
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

    has_error, order = validate_3yc(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
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

    has_error, order = validate_3yc(order, customer_data)

    assert has_error is False


def test_validate_3yc_empty_minimums(order_factory, order_parameters_factory):
    order = order_factory(order_parameters=order_parameters_factory(p3yc=["Yes"]))
    customer_data = get_customer_data(order)

    has_error, order = validate_3yc(order, customer_data)

    assert has_error is True
    assert order["error"]["id"] == "VIPMV008"


def test_validate_duplicate_lines(order_factory, lines_factory):
    order = order_factory(lines=lines_factory() + lines_factory())

    has_error, order = validate_duplicate_lines(order)

    assert has_error is True
    assert order["error"]["id"] == "VIPMV009"
