import logging

import pytest

from adobe_vipm.adobe.constants import (
    STATUS_TRANSFER_INVALID_MEMBERSHIP,
    STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
    UNRECOVERABLE_TRANSFER_STATUSES,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_ADDRESS,
    ERR_ADDRESS_LINE_1_LENGTH,
    ERR_ADDRESS_LINE_2_LENGTH,
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_ID_ITEM,
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
    ERR_PREFERRED_LANGUAGE,
    ERR_STATE_OR_PROVINCE,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_MEMBERSHIP_ID,
    PARAM_PREFERRED_LANGUAGE,
)
from adobe_vipm.flows.utils import get_customer_data, get_ordering_parameter
from adobe_vipm.flows.validation import (
    validate_address,
    validate_company_name,
    validate_contact,
    validate_customer_data,
    validate_order,
    validate_preferred_language,
    validate_transfer,
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
    assert param["constraints"]["optional"] is False


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
    assert param["constraints"]["optional"] is False


def test_validate_preferred_language(order_factory, order_parameters_factory):
    """
    Tests the validation of the preferred language when it is valid.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(preferred_language="en-US")
    )
    customer_data = get_customer_data(order)

    has_error, order = validate_preferred_language(order, customer_data)

    assert has_error is False

    param = get_ordering_parameter(
        order,
        PARAM_PREFERRED_LANGUAGE,
    )
    assert "error" not in param


def test_validate_preferred_language_invalid(
    order_factory,
    order_parameters_factory,
):
    """
    Tests the validation of the preferred language when it is invalid.
    """
    order = order_factory(
        order_parameters=order_parameters_factory(preferred_language="invalid")
    )
    customer_data = get_customer_data(order)

    has_error, order = validate_preferred_language(order, customer_data)

    assert has_error is True

    param = get_ordering_parameter(
        order,
        PARAM_PREFERRED_LANGUAGE,
    )
    assert param["error"] == ERR_PREFERRED_LANGUAGE.to_dict(
        title=param["name"],
        languages="en-US",
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["optional"] is False


def test_validate_address(order_factory):
    """
    Tests the validation of a valid address.
    """
    order = order_factory()
    customer_data = get_customer_data(order)

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
                "postalCode": "08001",
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
    assert param["constraints"]["optional"] is False


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
                "postalCode": "94123",
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
    assert param["constraints"]["optional"] is False


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
                "postalCode": "9412312",
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
    assert param["constraints"]["optional"] is False


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
                "postalCode": "9" * 41,
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
    assert param["constraints"]["optional"] is False


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
                "postalCode": "",
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
                ERR_ADDRESS_LINE_2_LENGTH,
                ERR_CITY_LENGTH,
            ),
        ),
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["optional"] is False


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
    assert param["constraints"]["optional"] is False


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
    assert param["constraints"]["optional"] is False


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
    assert param["constraints"]["optional"] is False


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
    assert param["constraints"]["optional"] is False


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
        "validate_preferred_language",
        "validate_address",
        "validate_contact",
    ):
        order_mock = mocker.MagicMock()
        order_mocks.append(order_mock)
        fn_mocks.append(
            mocker.patch(
                f"adobe_vipm.flows.validation.{fnname}",
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
        "validate_preferred_language",
        "validate_address",
        "validate_contact",
    ],
)
def test_validate_customer_data_invalid(mocker, no_validating_fn):
    """
    Test that if one of the validation returns has_errors=True the
    `validate_customer_data` function returns has_errors=True
    """
    for fnname in (
        "validate_company_name",
        "validate_preferred_language",
        "validate_address",
        "validate_contact",
    ):
        mocker.patch(
            f"adobe_vipm.flows.validation.{fnname}",
            return_value=(fnname == no_validating_fn, mocker.MagicMock()),
        )

    has_errors, _ = validate_customer_data(mocker.MagicMock(), mocker.MagicMock())

    assert has_errors is True


def test_validate_purchase_order(mocker, caplog, order_factory, buyer, customer_data):
    """Tests the validate order entrypoint function when it validates."""
    order = order_factory()
    m_client = mocker.MagicMock()

    m_get_buyer = mocker.patch(
        "adobe_vipm.flows.validation.get_buyer", return_value=buyer
    )
    m_prepare_customer_data = mocker.patch(
        "adobe_vipm.flows.validation.prepare_customer_data",
        return_value=(order, customer_data),
    )
    m_validate_customer_data = mocker.patch(
        "adobe_vipm.flows.validation.validate_customer_data",
        return_value=(False, order),
    )
    m_update_purchase_prices = mocker.patch(
        "adobe_vipm.flows.validation.update_purchase_prices",
        return_value=order,
    )
    m_adobe_cli = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.validation.get_adobe_client", return_value=m_adobe_cli
    )

    with caplog.at_level(logging.INFO):
        assert validate_order(m_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    m_get_buyer.assert_called_once_with(m_client, order["agreement"]["buyer"]["id"])
    m_prepare_customer_data.assert_called_once_with(m_client, order, buyer)
    m_validate_customer_data.assert_called_once_with(order, customer_data)
    m_update_purchase_prices.assert_called_once_with(
        m_client,
        m_adobe_cli,
        order["agreement"]["seller"]["address"]["country"],
        order,
    )


def test_validate_purchase_order_no_validate(mocker, caplog, order_factory):
    """Tests the validate order entrypoint function when doesn't validate."""
    order = order_factory()
    m_client = mocker.MagicMock()

    mocker.patch("adobe_vipm.flows.validation.populate_order_info", return_value=order)
    mocker.patch("adobe_vipm.flows.validation.get_buyer")
    mocker.patch(
        "adobe_vipm.flows.validation.prepare_customer_data",
        return_value=(order, mocker.MagicMock()),
    )
    mocker.patch(
        "adobe_vipm.flows.validation.validate_customer_data",
        return_value=(True, order),
    )

    with caplog.at_level(logging.INFO):
        validate_order(m_client, order)

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded with errors"
    )


def test_validate_transfer(
    mocker,
    order_factory,
    items_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
    lines_factory,
):
    m_client = mocker.MagicMock()
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    product_items = items_factory()
    adobe_preview_transfer = adobe_preview_transfer_factory()
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer
    mocker.patch(
        "adobe_vipm.flows.validation.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.validation.get_product_items_by_skus",
        return_value=product_items,
    )

    has_errors, validated_order = validate_transfer(m_client, order)
    lines = lines_factory(line_id=None)
    del lines[0]["price"]
    assert has_errors is False
    assert validated_order["lines"] == lines

    mocked_get_product_items_by_skus.assert_called_once_with(
        m_client,
        order["agreement"]["product"]["id"],
        [adobe_preview_transfer["items"][0]["offerId"][:10]],
    )


@pytest.mark.parametrize(
    "status_code",
    [
        STATUS_TRANSFER_INVALID_MEMBERSHIP,
        STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
    ]
    + UNRECOVERABLE_TRANSFER_STATUSES,
)
def test_validate_transfer_membership_error(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_api_error_factory,
    status_code,
):
    m_client = mocker.MagicMock()
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    api_error = AdobeAPIError(
        adobe_api_error_factory(status_code, "An error"),
    )
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.side_effect = api_error
    mocker.patch(
        "adobe_vipm.flows.validation.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True

    param = get_ordering_parameter(validated_order, PARAM_MEMBERSHIP_ID)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID.to_dict(
        title=param["name"],
        details=str(api_error),
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["optional"] is False


def test_validate_transfer_unknown_item(
    mocker,
    order_factory,
    transfer_order_parameters_factory,
    adobe_preview_transfer_factory,
):
    m_client = mocker.MagicMock()
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    adobe_preview_transfer = adobe_preview_transfer_factory()
    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.preview_transfer.return_value = adobe_preview_transfer
    mocker.patch(
        "adobe_vipm.flows.validation.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.validation.get_product_items_by_skus",
        return_value=[],
    )

    has_errors, validated_order = validate_transfer(m_client, order)

    assert has_errors is True
    param = get_ordering_parameter(validated_order, PARAM_MEMBERSHIP_ID)
    assert param["error"] == ERR_ADOBE_MEMBERSHIP_ID_ITEM.to_dict(
        title=param["name"],
        item_sku=adobe_preview_transfer["items"][0]["offerId"][:10],
    )
    assert param["constraints"]["hidden"] is False
    assert param["constraints"]["optional"] is False


def test_validate_transfer_order(
    mocker,
    caplog,
    order_factory,
    transfer_order_parameters_factory,
):
    """Tests the validate order entrypoint function for transfer orders when it validates."""
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    m_client = mocker.MagicMock()

    m_validate_transfer = mocker.patch(
        "adobe_vipm.flows.validation.validate_transfer",
        return_value=(False, order),
    )
    m_update_purchase_prices = mocker.patch(
        "adobe_vipm.flows.validation.update_purchase_prices",
        return_value=order,
    )
    m_adobe_cli = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.validation.get_adobe_client", return_value=m_adobe_cli
    )

    with caplog.at_level(logging.INFO):
        assert validate_order(m_client, order) == order

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded without errors"
    )

    m_validate_transfer.assert_called_once_with(
        m_client,
        order,
    )
    m_update_purchase_prices.assert_called_once_with(
        m_client,
        m_adobe_cli,
        order["agreement"]["seller"]["address"]["country"],
        order,
    )


def test_validate_transfer_order_no_validate(
    mocker,
    caplog,
    order_factory,
    transfer_order_parameters_factory,
):
    """Tests the validate order entrypoint function for transfers when doesn't validate."""
    order = order_factory(order_parameters=transfer_order_parameters_factory())
    m_client = mocker.MagicMock()

    mocker.patch("adobe_vipm.flows.validation.populate_order_info", return_value=order)
    mocker.patch("adobe_vipm.flows.validation.get_buyer")
    mocker.patch(
        "adobe_vipm.flows.validation.prepare_customer_data",
        return_value=(order, mocker.MagicMock()),
    )

    mocker.patch(
        "adobe_vipm.flows.validation.validate_transfer",
        return_value=(True, order),
    )

    with caplog.at_level(logging.INFO):
        validate_order(m_client, order)

    assert caplog.records[0].message == (
        f"Validation of order {order['id']} succeeded with errors"
    )
