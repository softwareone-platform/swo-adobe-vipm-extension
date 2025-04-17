import pytest

from adobe_vipm.adobe.constants import STATUS_INACTIVE_OR_GENERIC_FAILURE
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.errors import AirTableAPIError, MPTAPIError
from adobe_vipm.flows.global_customer import check_gc_agreement_deployments


@pytest.fixture()
def gc_agreement_deployment(mocker):
    gc_agreement_deployment = mocker.MagicMock()
    gc_agreement_deployment.deployment_id = "deployment_id"
    gc_agreement_deployment.agreement_id = "AGR-1234-1234-1234"
    gc_agreement_deployment.main_agreement_id = "AGR-1234-1234-1234-main"
    gc_agreement_deployment.account_id = "ACC-123-123-123"
    gc_agreement_deployment.seller_id = "SEL-321-321"
    gc_agreement_deployment.product_id = "PRD-123-123-123"
    gc_agreement_deployment.membership_id = "membership-id"
    gc_agreement_deployment.transfer_id = "transfer-id"
    gc_agreement_deployment.status = "New"
    gc_agreement_deployment.customer_id = "P0112233"
    gc_agreement_deployment.deployment_currency = "USD"
    gc_agreement_deployment.deployment_country = "US"
    gc_agreement_deployment.licensee_id = "LC-321-321-321"
    gc_agreement_deployment.authorization_id = "AUT-1234-1234-1234"
    gc_agreement_deployment.price_list_id = "PRC-123-123-123"
    gc_agreement_deployment.listing_id = "LST-123-123-321"
    gc_agreement_deployment.error_description = ""
    gc_agreement_deployment.created_at = "2025-01-01"
    gc_agreement_deployment.updated_at = "2025-01-01"
    gc_agreement_deployment.created_by = "Stu"
    gc_agreement_deployment.updated_by = "Stu"

    return gc_agreement_deployment


def test_check_gc_agreement_deployments_no_licensee(
    mocker, settings, gc_agreement_deployment
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM", "PRD-2222-2222": "GOV"},
    }
    settings.MPT_PRODUCTS_IDS = ["PRD-1111-1111", "PRD-2222-2222"]
    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployment.licensee_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()


def test_check_gc_agreement_deployments_unexpected_error(
    mocker, settings, airtable_error_factory
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    error = AirTableAPIError(
        400,
        airtable_error_factory(
            "Bad Request",
            "BAD_REQUEST",
        ),
    )
    mocked_gc_agreement_deployments_model.all.side_effect = error

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()


def test_check_gc_agreement_deployments_no_authorization_id(
    mocker,
    settings,
    gc_agreement_deployment,
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_authorizations_by_currency_and_seller_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_authorizations_by_currency_and_seller_id",
        return_value=[],
    )
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployment.authorization_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_authorizations_by_currency_and_seller_id.assert_called_once()


def test_check_gc_agreement_deployments_get_authorization_error(
    mocker, settings, mpt_error_factory, gc_agreement_deployment
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()
    error_data = mpt_error_factory(
        400,
        "Bad Request",
        "One or more validation errors occurred.",
        trace_id="trace-id",
        errors={"id": ["The value of 'id' does not match expected format."]},
    )
    error = MPTAPIError(400, error_data)
    mocked_get_authorizations_by_currency_and_seller_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_authorizations_by_currency_and_seller_id",
        side_effect=error,
    )
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployment.authorization_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_authorizations_by_currency_and_seller_id.assert_called_once()


def test_check_gc_agreement_deployments_get_authorization_more_than_one(
    mocker, settings, mpt_error_factory, gc_agreement_deployment
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_authorizations_by_currency_and_seller_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_authorizations_by_currency_and_seller_id",
        return_value=[mocker.MagicMock(), mocker.MagicMock()],
    )
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployment.authorization_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_authorizations_by_currency_and_seller_id.assert_called_once()
    gc_agreement_deployment.save.assert_called_once()


def test_check_gc_agreement_deployments_get_price_list_error(
    mocker, settings, mpt_error_factory, gc_agreement_deployment
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"
    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()
    error_data = mpt_error_factory(
        400,
        "Bad Request",
        "One or more validation errors occurred.",
        trace_id="trace-id",
        errors={"id": ["The value of 'id' does not match expected format."]},
    )
    error = MPTAPIError(400, error_data)
    mocked_get_gc_price_list_by_currency = mocker.patch(
        "adobe_vipm.flows.global_customer.get_gc_price_list_by_currency",
        side_effect=error,
    )
    mocked_get_authorizations_by_currency_and_seller_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_authorizations_by_currency_and_seller_id",
        return_value=[mocker.MagicMock()],
    )
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployment.authorization_id = None
    gc_agreement_deployment.price_list_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_authorizations_by_currency_and_seller_id.assert_called_once()
    mocked_get_gc_price_list_by_currency.assert_called_once()


def test_check_gc_agreement_deployments_no_price_list(
    mocker, settings, mpt_error_factory, gc_agreement_deployment
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_gc_price_list_by_currency = mocker.patch(
        "adobe_vipm.flows.global_customer.get_gc_price_list_by_currency",
        return_value=[],
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployment.price_list_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_gc_price_list_by_currency.assert_called_once()


def test_check_gc_agreement_deployments_get_price_more_than_one(
    mocker, settings, mpt_error_factory, gc_agreement_deployment
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_gc_price_list_by_currency = mocker.patch(
        "adobe_vipm.flows.global_customer.get_gc_price_list_by_currency",
        return_value=[mocker.MagicMock(), mocker.MagicMock()],
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployment.price_list_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_gc_price_list_by_currency.assert_called_once()


def test_check_gc_agreement_deployments_get_listing_error(
    mocker, settings, mpt_error_factory, gc_agreement_deployment
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    price_list = mocker.MagicMock()
    price_list.externalIds = "price_list_global"
    mocked_get_gc_price_list_by_currency = mocker.patch(
        "adobe_vipm.flows.global_customer.get_gc_price_list_by_currency",
        return_value=[price_list],
    )
    error_data = mpt_error_factory(
        400,
        "Bad Request",
        "One or more validation errors occurred.",
        trace_id="trace-id",
        errors={"id": ["The value of 'id' does not match expected format."]},
    )
    error = MPTAPIError(400, error_data)
    mocked_get_listings_by_price_list_and_seller_and_authorization = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listings_by_price_list_and_seller_and_authorization",
        side_effect=error,
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployment.price_list_id = None
    gc_agreement_deployment.listing_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_gc_price_list_by_currency.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()


def test_check_gc_agreement_deployments_create_listing(
    mocker,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
    provisioning_agreement,
    gc_agreement_deployment,
    listing,
    licensee,
    template,
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_listings_by_price_list_and_seller_and_authorization = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listings_by_price_list_and_seller_and_authorization",
        return_value=[],
    )

    mocked_create_listing = mocker.patch(
        "adobe_vipm.flows.global_customer.create_listing",
        return_value=listing,
    )

    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.global_customer.get_licensee",
        return_value=licensee,
    )

    mocked_get_product_template_or_default = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_template_or_default",
        return_value=template,
    )

    mocked_create_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.create_agreement",
        return_value=mocker.MagicMock(),
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.update_agreement",
        return_value=mocker.MagicMock(),
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments_active_status.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription_factory()]
    }

    gc_agreement_deployment.listing_id = None
    gc_agreement_deployment.agreement_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]
    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement",
        return_value=provisioning_agreement,
    )

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()
    mocked_create_listing.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments_active_status.assert_called_once()
    mocked_get_product_template_or_default.assert_called_once()
    mocked_create_agreement.assert_called_with(
        mocker.ANY,
        {
            "authorization": {"id": "AUT-1234-1234-1234"},
            "buyer": {"id": "BUY-3731-7971"},
            "client": {"id": "ACC-123-123-123"},
            "externalIds": {"vendor": "a-client-id"},
            "licensee": {"id": "LC-321-321-321"},
            "lines": [],
            "listing": {"id": "LST-9401-9279"},
            "name": "Adobe for Commercial for Client Account - US",
            "parameters": {
                "fulfillment": [
                    {"externalId": "globalCustomer", "value": ["Yes"]},
                    {"externalId": "deploymentId", "value": "deployment_id"},
                    {"externalId": "deployments", "value": ""},
                    {"externalId": "customerId", "value": "P0112233"},
                    {"externalId": "cotermDate", "value": "2024-01-23"},
                ],
                "ordering": [
                    {"externalId": "agreementType", "value": "Migrate"},
                    {"externalId": "companyName", "value": "Migrated Company"},
                    {
                        "externalId": "address",
                        "value": {
                            "addressLine1": "addressLine1",
                            "addressLine2": "addressLine2",
                            "city": "city",
                            "country": "US",
                            "postCode": "postalCode",
                            "state": "region",
                        },
                    },
                    {
                        "externalId": "contact",
                        "value": {
                            "email": "email",
                            "firstName": "firstName",
                            "lastName": "lastName",
                            "phone": {"number": "8004449890", "prefix": "+1"},
                        },
                    },
                    {"externalId": "membershipId", "value": "membership-id"},
                ],
            },
            "product": {"id": "PRD-123-123-123"},
            "seller": {"id": "SEL-321-321"},
            "status": "Active",
            "subscriptions": [],
            "template": {"id": "TPL-1234-1234-4321", "name": "Default Template"},
            "termsAndConditions": [],
            "vendor": {"id": "ACC-1234-vendor-id"},
        },
    )
    mocked_get_agreement.assert_called_once()

    mocked_update_agreement.assert_called_once()


def test_check_gc_agreement_deployments_get_listing_more_than_one(
    mocker, settings, mpt_error_factory, gc_agreement_deployment
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"
    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_listings_by_price_list_and_seller_and_authorization = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listings_by_price_list_and_seller_and_authorization",
        return_value=[mocker.MagicMock(), mocker.MagicMock()],
    )
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployment.listing_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()


def test_check_gc_agreement_deployments_create_listing_error(
    mocker, settings, mpt_error_factory, gc_agreement_deployment
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_listings_by_price_list_and_seller_and_authorization = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listings_by_price_list_and_seller_and_authorization",
        return_value=[],
    )
    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    error_data = mpt_error_factory(
        400,
        "Bad Request",
        "One or more validation errors occurred.",
        trace_id="trace-id",
        errors={"id": ["The value of 'id' does not match expected format."]},
    )
    error = MPTAPIError(400, error_data)
    mocked_create_listing = mocker.patch(
        "adobe_vipm.flows.global_customer.create_listing",
        side_effect=error,
    )

    gc_agreement_deployment.listing_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()
    mocked_create_listing.assert_called_once()


def test_check_gc_agreement_deployments_create_agreement_error(
    mocker,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
    provisioning_agreement,
    gc_agreement_deployment,
    licensee,
    template,
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_listings_by_price_list_and_seller_and_authorization = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listings_by_price_list_and_seller_and_authorization",
        return_value=[mocker.MagicMock()],
    )

    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.global_customer.get_licensee",
        return_value=licensee,
    )

    mocked_get_product_template_or_default = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_template_or_default",
        return_value=template,
    )
    error_data = mpt_error_factory(
        400,
        "Bad Request",
        "One or more validation errors occurred.",
        trace_id="trace-id",
        errors={"id": ["The value of 'id' does not match expected format."]},
    )
    error = MPTAPIError(400, error_data)
    mocked_create_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.create_agreement",
        side_effect=error,
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments_active_status.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription_factory()]
    }

    gc_agreement_deployment.listing_id = None
    gc_agreement_deployment.agreement_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]
    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement",
        return_value=provisioning_agreement,
    )

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments_active_status.assert_called_once()
    mocked_get_product_template_or_default.assert_called_once()
    mocked_create_agreement.assert_called_once()
    mocked_get_agreement.assert_called_once()


def test_check_gc_agreement_deployments_get_adobe_subscriptions_error(
    mocker,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
    adobe_api_error_factory,
    provisioning_agreement,
    gc_agreement_deployment,
    licensee,
    listing,
    template,
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_listings_by_price_list_and_seller_and_authorization = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listings_by_price_list_and_seller_and_authorization",
        return_value=[],
    )

    mocked_create_listing = mocker.patch(
        "adobe_vipm.flows.global_customer.create_listing",
        return_value=listing,
    )

    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.global_customer.get_licensee",
        return_value=licensee,
    )

    mocked_get_product_template_or_default = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_template_or_default",
        return_value=template,
    )

    mocked_create_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.create_agreement",
        return_value=mocker.MagicMock(),
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.update_agreement",
        return_value=mocker.MagicMock(),
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement",
        return_value=provisioning_agreement,
    )

    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments_active_status.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            "1000",
            "Error updating autorenewal quantity",
        ),
    )

    gc_agreement_deployment.listing_id = None
    gc_agreement_deployment.agreement_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()
    mocked_create_listing.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments_active_status.assert_called_once()
    mocked_get_product_template_or_default.assert_called_once()
    mocked_create_agreement.assert_called_once()
    mocked_get_agreement.assert_called_once()

    mocked_update_agreement.assert_called_once()


def test_check_gc_agreement_deployments_create_agreement_subscription(
    mocker,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
    provisioning_agreement,
    gc_agreement_deployment,
    licensee,
    listing,
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.global_customer.get_licensee",
        return_value=licensee,
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.update_agreement",
        return_value=mocker.MagicMock(),
    )

    mocked_get_listing_by_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listing_by_id",
        return_value=listing,
    )
    mocked_get_subscription_by_external_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement_subscription_by_external_id",
        return_value=[],
    )

    mocked_create_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.global_customer.create_agreement_subscription",
        return_value=mocker.MagicMock(),
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    product_items = items_factory()
    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_items_by_skus",
        return_value=product_items,
    )
    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments_active_status.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription_factory(deployment_id="deployment_id"),
            adobe_subscription_factory(deployment_id=""),
            adobe_subscription_factory(
                deployment_id="deployment_id", status=STATUS_INACTIVE_OR_GENERIC_FAILURE
            ),
        ]
    }

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement",
        return_value=provisioning_agreement,
    )

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments_active_status.assert_called_once()

    mocked_update_agreement.assert_called_once()
    mocked_get_product_items_by_skus.assert_called()
    mocked_get_listing_by_id.assert_called_once()
    mocked_get_subscription_by_external_id.assert_called_once()
    mocked_create_agreement_subscription.assert_called_once()
    mocked_get_agreement.assert_called_once()


def test_check_gc_agreement_deployments_create_agreement_subscription_already_created(
    mocker,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
    provisioning_agreement,
    gc_agreement_deployment,
    licensee,
    listing,
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.global_customer.get_licensee",
        return_value=licensee,
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.update_agreement",
        return_value=mocker.MagicMock(),
    )

    mocked_get_listing_by_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listing_by_id",
        return_value=listing,
    )
    mocked_get_subscription_by_external_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement_subscription_by_external_id",
        return_value=mocker.MagicMock(),
    )
    mocked_create_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.global_customer.create_agreement_subscription",
        return_value=mocker.MagicMock(),
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    product_items = items_factory()
    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_items_by_skus",
        return_value=product_items,
    )
    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments_active_status.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription_factory(deployment_id="deployment_id")]
    }

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement",
        return_value=provisioning_agreement,
    )

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments_active_status.assert_called_once()

    mocked_update_agreement.assert_called_once()
    mocked_get_product_items_by_skus.assert_called()
    mocked_get_listing_by_id.assert_called_once()
    mocked_get_subscription_by_external_id.assert_called_once()
    mocked_create_agreement_subscription.assert_not_called()
    mocked_get_agreement.assert_called_once()


def test_check_gc_agreement_deployments_create_agreement_subscription_error(
    mocker,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
    provisioning_agreement,
    gc_agreement_deployment,
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.global_customer.get_licensee",
        return_value=mocker.MagicMock(),
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.update_agreement",
        return_value=mocker.MagicMock(),
    )

    mocked_get_listing_by_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listing_by_id",
        return_value=mocker.MagicMock(),
    )
    mocked_get_subscription_by_external_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement_subscription_by_external_id",
        return_value=[],
    )
    error_data = mpt_error_factory(
        400,
        "Bad Request",
        "One or more validation errors occurred.",
        trace_id="trace-id",
        errors={"id": ["The value of 'id' does not match expected format."]},
    )
    error = MPTAPIError(400, error_data)
    mocked_create_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.global_customer.create_agreement_subscription",
        side_effect=error,
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    product_items = items_factory()
    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_items_by_skus",
        return_value=product_items,
    )
    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments_active_status.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription_factory(deployment_id="deployment_id")]
    }

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]

    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement",
        return_value=provisioning_agreement,
    )

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments_active_status.assert_called_once()

    mocked_update_agreement.assert_called_once()
    mocked_get_product_items_by_skus.assert_called()
    mocked_get_listing_by_id.assert_called_once()
    mocked_get_subscription_by_external_id.assert_called_once()
    mocked_create_agreement_subscription.assert_called_once()
    mocked_get_agreement.assert_called_once()


def test_check_gc_agreement_deployments_create_agreement_subscription_enable_auto_renew(
    mocker,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
    provisioning_agreement,
    gc_agreement_deployment,
):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM"},
    }
    settings.MPT_API_TOKEN_OPERATIONS = "operations_api_key"

    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()

    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.global_customer.get_licensee",
        return_value=mocker.MagicMock(),
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.update_agreement",
        return_value=mocker.MagicMock(),
    )

    mocked_get_listing_by_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listing_by_id",
        return_value=mocker.MagicMock(),
    )
    mocked_get_subscription_by_external_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement_subscription_by_external_id",
        return_value=[],
    )

    mocked_create_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.global_customer.create_agreement_subscription",
        return_value=mocker.MagicMock(),
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    product_items = items_factory()
    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_items_by_skus",
        return_value=product_items,
    )
    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments_active_status.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription_factory(
                deployment_id="deployment_id", autorenewal_enabled=False
            )
        ]
    }

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployment]
    mocked_get_agreement = mocker.patch(
        "adobe_vipm.flows.global_customer.get_agreement",
        return_value=provisioning_agreement,
    )

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments_active_status.assert_called_once()
    mocked_adobe_client.update_subscription.assert_called_once()

    mocked_update_agreement.assert_called_once()
    mocked_get_product_items_by_skus.assert_called()
    mocked_get_listing_by_id.assert_called_once()
    mocked_get_subscription_by_external_id.assert_called_once()
    mocked_create_agreement_subscription.assert_called_once()
    mocked_get_agreement.assert_called_once()
