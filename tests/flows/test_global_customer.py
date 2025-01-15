from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.errors import AirTableAPIError, MPTAPIError
from adobe_vipm.flows.global_customer import check_gc_agreement_deployments


def test_check_gc_agreement_deployments_no_licensee(mocker, mpt_client, settings):
    settings.EXTENSION_CONFIG = {
        "AIRTABLE_API_TOKEN": "api_key",
        "AIRTABLE_BASES": {"PRD-1111-1111": "base_id"},
        "PRODUCT_SEGMENT": {"PRD-1111-1111": "COM","PRD-2222-2222": "GOV"},
    }
    settings.MPT_PRODUCTS_IDS = ["PRD-1111-1111","PRD-2222-2222"]
    mocked_adobe_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.global_customer.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_gc_agreement_deployments_model = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = None
    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()


def test_check_gc_agreement_deployments_unexpected_error(
    mocker, mpt_client, settings, airtable_error_factory
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
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
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
    mocker, mpt_client, settings
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

    mocked_get_authorizations_by_currency_and_seller_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_authorizations_by_currency_and_seller_id",
        return_value=[],
    )
    mocker.patch(
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_authorizations_by_currency_and_seller_id.assert_called_once()


def test_check_gc_agreement_deployments_get_authorization_error(
    mocker, mpt_client, settings, mpt_error_factory
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
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_authorizations_by_currency_and_seller_id.assert_called_once()


def test_check_gc_agreement_deployments_get_authorization_more_than_one(
    mocker, mpt_client, settings, mpt_error_factory
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

    mocked_get_authorizations_by_currency_and_seller_id = mocker.patch(
        "adobe_vipm.flows.global_customer.get_authorizations_by_currency_and_seller_id",
        return_value=[mocker.MagicMock(), mocker.MagicMock()],
    )
    mocker.patch(
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_authorizations_by_currency_and_seller_id.assert_called_once()
    gc_agreement_deployments.save.assert_called_once()


def test_check_gc_agreement_deployments_get_price_list_error(
    mocker, mpt_client, settings, mpt_error_factory
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
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = None
    gc_agreement_deployments.price_list_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_authorizations_by_currency_and_seller_id.assert_called_once()
    mocked_get_gc_price_list_by_currency.assert_called_once()


def test_check_gc_agreement_deployments_no_price_list(
    mocker, mpt_client, settings, mpt_error_factory
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

    mocked_get_gc_price_list_by_currency = mocker.patch(
        "adobe_vipm.flows.global_customer.get_gc_price_list_by_currency",
        return_value=[],
    )

    mocker.patch(
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_gc_price_list_by_currency.assert_called_once()


def test_check_gc_agreement_deployments_get_price_more_than_one(
    mocker, mpt_client, settings, mpt_error_factory
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

    mocked_get_gc_price_list_by_currency = mocker.patch(
        "adobe_vipm.flows.global_customer.get_gc_price_list_by_currency",
        return_value=[mocker.MagicMock(), mocker.MagicMock()],
    )

    mocker.patch(
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_gc_price_list_by_currency.assert_called_once()


def test_check_gc_agreement_deployments_get_listing_error(
    mocker, mpt_client, settings, mpt_error_factory
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
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = None
    gc_agreement_deployments.listing_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_gc_price_list_by_currency.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()


def test_check_gc_agreement_deployments_create_listing(
    mocker,
    mpt_client,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
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
        return_value=mocker.MagicMock(),
    )

    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.global_customer.get_licensee",
        return_value=mocker.MagicMock(),
    )

    mocked_get_product_template_or_default = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_template_or_default",
        return_value=mocker.MagicMock(),
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
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription_factory()]
    }

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = "price_list_id"
    gc_agreement_deployments.listing_id = None
    gc_agreement_deployments.agreement_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()
    mocked_create_listing.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments.assert_called_once()
    mocked_get_product_template_or_default.assert_called_once()
    mocked_create_agreement.assert_called_once()

    mocked_update_agreement.assert_called_once()


def test_check_gc_agreement_deployments_get_listing_more_than_one(
    mocker, mpt_client, settings, mpt_error_factory
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

    mocked_get_listings_by_price_list_and_seller_and_authorization = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listings_by_price_list_and_seller_and_authorization",
        return_value=[mocker.MagicMock(), mocker.MagicMock()],
    )
    mocker.patch(
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = "price_list_id"
    gc_agreement_deployments.listing_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()


def test_check_gc_agreement_deployments_create_listing_error(
    mocker, mpt_client, settings, mpt_error_factory
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

    mocked_get_listings_by_price_list_and_seller_and_authorization = mocker.patch(
        "adobe_vipm.flows.global_customer.get_listings_by_price_list_and_seller_and_authorization",
        return_value=[],
    )
    mocker.patch(
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
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

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = "price_list_id"
    gc_agreement_deployments.listing_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()
    mocked_create_listing.assert_called_once()


def test_check_gc_agreement_deployments_create_agreement_error(
    mocker,
    mpt_client,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
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
        return_value=mocker.MagicMock(),
    )

    mocked_get_product_template_or_default = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_template_or_default",
        return_value=mocker.MagicMock(),
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
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription_factory()]
    }

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = "price_list_id"
    gc_agreement_deployments.listing_id = None
    gc_agreement_deployments.agreement_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments.assert_called_once()
    mocked_get_product_template_or_default.assert_called_once()
    mocked_create_agreement.assert_called_once()


def test_check_gc_agreement_deployments_get_adobe_subscriptions_error(
    mocker,
    mpt_client,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
    adobe_api_error_factory,
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
        return_value=mocker.MagicMock(),
    )

    mocked_get_licensee = mocker.patch(
        "adobe_vipm.flows.global_customer.get_licensee",
        return_value=mocker.MagicMock(),
    )

    mocked_get_product_template_or_default = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_template_or_default",
        return_value=mocker.MagicMock(),
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
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )

    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            "1000",
            "Error updating autorenewal quantity",
        ),
    )

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = "price_list_id"
    gc_agreement_deployments.listing_id = None
    gc_agreement_deployments.agreement_id = None

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_listings_by_price_list_and_seller_and_authorization.assert_called_once()
    mocked_create_listing.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments.assert_called_once()
    mocked_get_product_template_or_default.assert_called_once()
    mocked_create_agreement.assert_called_once()

    mocked_update_agreement.assert_called_once()


def test_check_gc_agreement_deployments_create_agreement_subscription(
    mocker,
    mpt_client,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
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
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    product_items = items_factory()
    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_items_by_skus",
        return_value=product_items,
    )
    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription_factory(deployment_id="deployment_id")]
    }

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = "price_list_id"
    gc_agreement_deployments.listing_id = "listing_id"
    gc_agreement_deployments.agreement_id = "agreement_id"
    gc_agreement_deployments.deployment_id = "deployment_id"

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments.assert_called_once()

    mocked_update_agreement.assert_called_once()
    mocked_get_product_items_by_skus.assert_called()
    mocked_get_listing_by_id.assert_called_once()
    mocked_get_subscription_by_external_id.assert_called_once()
    mocked_create_agreement_subscription.assert_called_once()


def test_check_gc_agreement_deployments_create_agreement_subscription_already_created(
    mocker,
    mpt_client,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
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
        return_value=mocker.MagicMock(),
    )
    mocked_create_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.global_customer.create_agreement_subscription",
        return_value=mocker.MagicMock(),
    )

    mocker.patch(
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    product_items = items_factory()
    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_items_by_skus",
        return_value=product_items,
    )
    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription_factory(deployment_id="deployment_id")]
    }

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = "price_list_id"
    gc_agreement_deployments.listing_id = "listing_id"
    gc_agreement_deployments.agreement_id = "agreement_id"
    gc_agreement_deployments.deployment_id = "deployment_id"

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments.assert_called_once()

    mocked_update_agreement.assert_called_once()
    mocked_get_product_items_by_skus.assert_called()
    mocked_get_listing_by_id.assert_called_once()
    mocked_get_subscription_by_external_id.assert_called_once()
    mocked_create_agreement_subscription.assert_not_called()


def test_check_gc_agreement_deployments_create_agreement_subscription_error(
    mocker,
    mpt_client,
    settings,
    mpt_error_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    items_factory,
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
        "adobe_vipm.flows.airtable.get_gc_agreement_deployment_model",
        return_value=mocked_gc_agreement_deployments_model,
    )
    product_items = items_factory()
    mocked_get_product_items_by_skus = mocker.patch(
        "adobe_vipm.flows.global_customer.get_product_items_by_skus",
        return_value=product_items,
    )
    adobe_customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = adobe_customer
    mocked_adobe_client.get_customer_deployments.return_value = mocker.MagicMock()
    mocked_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription_factory(deployment_id="deployment_id")]
    }

    gc_agreement_deployments = mocker.MagicMock()
    gc_agreement_deployments.licensee_id = "licensee_id"
    gc_agreement_deployments.authorization_id = "authorization_id"
    gc_agreement_deployments.price_list_id = "price_list_id"
    gc_agreement_deployments.listing_id = "listing_id"
    gc_agreement_deployments.agreement_id = "agreement_id"
    gc_agreement_deployments.deployment_id = "deployment_id"

    mocked_gc_agreement_deployments_model.all.return_value = [gc_agreement_deployments]

    check_gc_agreement_deployments()
    mocked_gc_agreement_deployments_model.all.assert_called_once()
    mocked_get_licensee.assert_called_once()
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_adobe_client.get_customer_deployments.assert_called_once()

    mocked_update_agreement.assert_called_once()
    mocked_get_product_items_by_skus.assert_called()
    mocked_get_listing_by_id.assert_called_once()
    mocked_get_subscription_by_external_id.assert_called_once()
    mocked_create_agreement_subscription.assert_called_once()
