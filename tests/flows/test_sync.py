import logging

from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.sync import sync_prices
from adobe_vipm.flows.utils import get_adobe_customer_id


def test_sync_prices(
    mocker,
    agreement_factory,
    subscriptions_factory,
    adobe_subscription_factory,
    items_factory,
    pricelist_items_factory,
):
    agreement = agreement_factory()
    mpt_subscription = subscriptions_factory(commitment_date="2025-04-04")[0]
    adobe_subscription = adobe_subscription_factory()

    authorization_id = agreement["authorization"]["id"]
    customer_id = get_adobe_customer_id(agreement)

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_subscription

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_next_sync",
        return_value=[agreement],
    )

    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        return_value=mpt_subscription,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_product_items_by_skus",
        return_value=items_factory(),
    )
    mocker.patch(
        "adobe_vipm.flows.sync.get_pricelist_items_by_product_items",
        return_value=pricelist_items_factory(),
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    sync_prices(mocked_mpt_client)

    mocked_get_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
    )
    mocked_adobe_client.get_subscription.assert_called_once_with(
        authorization_id,
        customer_id,
        mpt_subscription["externalIds"]["vendor"],
    )

    mocked_update_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
        lines=[{'id': 'ALI-2119-4550-8674-5962-0001', 'price': {'unitPP': 1234.55}}],
        parameters={'fulfillment': [{'externalId': 'adobeSKU', 'value': '65304578CA01A12'}]},
    )

    mocked_update_agreement.assert_called_once_with(
        mocked_mpt_client,
        agreement["id"],
        parameters={'fulfillment': [{'externalId': 'nextSync', 'value': '2025-04-05'}]},
    )


def test_sync_prices_exception(
    mocker,
    agreement_factory,
    subscriptions_factory,
    adobe_api_error_factory,
    caplog,
):
    agreement = agreement_factory()
    mpt_subscription = subscriptions_factory(commitment_date="2025-04-04")[0]

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(code="9999", message="Error from Adobe."),
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_next_sync",
        return_value=[agreement],
    )

    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        side_effect=mpt_subscription,
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    with caplog.at_level(logging.ERROR):
        sync_prices(mocked_mpt_client)

    assert f"Cannot sync agreement {agreement['id']}" in caplog.text

    mocked_get_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
    )

    mocked_update_agreement_subscription.assert_not_called()
    mocked_update_agreement.assert_not_called()


def test_sync_prices_skip_processing(
    mocker,
    agreement_factory,
    caplog,
):
    agreement = agreement_factory(
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Updating",
            },
            {
                "id": "SUB-1234-5678",
                "status": "Terminating",
            },
        ],
    )
    mocked_mpt_client = mocker.MagicMock()

    mocker.patch("adobe_vipm.flows.sync.get_adobe_client")

    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_next_sync",
        return_value=[agreement],
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    with caplog.at_level(logging.INFO):
        sync_prices(mocked_mpt_client)

    assert f"Agreement {agreement['id']} has processing subscriptions, skip it" in caplog.text

    mocked_update_agreement_subscription.assert_not_called()
    mocked_update_agreement.assert_not_called()
