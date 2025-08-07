import logging

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe import constants
from adobe_vipm.adobe.constants import THREE_YC_TEMP_3YC_STATUSES, AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AuthorizationNotFoundError
from adobe_vipm.flows.constants import AgreementStatus, Param, SubscriptionStatus
from adobe_vipm.flows.errors import MPTAPIError
from adobe_vipm.flows.sync import (
    _add_missing_subscriptions,  # noqa: PLC2701
    _get_subscriptions_for_update,  # noqa: PLC2701
    _process_orphaned_deployment_subscriptions,  # noqa: PLC2701
    sync_agreement,
    sync_agreements_by_3yc_end_date,
    sync_agreements_by_3yc_enroll_status,
    sync_agreements_by_agreement_ids,
    sync_agreements_by_coterm_date,
    sync_agreements_by_renewal_date,
    sync_all_agreements,
)
from adobe_vipm.flows.utils import get_fulfillment_parameter

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


# TODO: mocked_mpt_client = mocker.MagicMock() replace with mock_mpt_client fixture


@pytest.fixture(autouse=True)
def mock_add_missing_subscriptions(mocker):
    return mocker.patch("adobe_vipm.flows.sync._add_missing_subscriptions", spec=True)


@pytest.fixture
def mock_create_agreement_subscription(mocker):
    return mocker.patch("adobe_vipm.flows.sync.create_agreement_subscription", spec=True)


@freeze_time("2025-06-23")
def test_sync_agreement_prices(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_adobe_client,
    mock_get_adobe_client,
    mock_get_agreement_subscription,
    mock_update_agreement_subscription,
    mock_mpt_client,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        subscriptions=[
            {"id": "SUB-1000-2000-3000", "status": "Active", "item": {"id": "ITM-0000-0001-0001"}},
            {"id": "SUB-1234-5678", "status": "Terminated", "item": {"id": "ITM-0000-0001-0002"}},
            {"id": "SUB-1000-2000-5000", "status": "Active", "item": {"id": "ITM-0000-0001-0003"}},
        ],
    )
    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )

    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, another_adobe_subscription]
    }
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")
    mock_get_agreement_subscription.side_effect = [mpt_subscription, another_mpt_subscription]

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        ],
    )

    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    assert mock_get_agreement_subscription.call_args_list == [
        mocker.call(mock_mpt_client, mpt_subscription["id"]),
        mocker.call(mock_mpt_client, another_mpt_subscription["id"]),
    ]

    assert mock_update_agreement_subscription.call_args_list == [
        mocker.call(
            mock_mpt_client,
            mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-23"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_subscription["autoRenewal"]["enabled"],
        ),
        mocker.call(
            mock_mpt_client,
            another_mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}}],
            parameters={
                "fulfillment": [
                    {
                        "externalId": "adobeSKU",
                        "value": "77777777CA01A12",
                    },
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(another_adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            another_adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": another_adobe_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-23"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
        ),
    ]

    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)

    assert mocked_update_agreement.call_args_list == [
        mocker.call(mock_mpt_client, agreement["id"], lines=expected_lines, parameters={}),
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-23"}]},
        ),
    ]
    mock_adobe_client.get_subscription.assert_not_called()


@freeze_time("2025-06-23")
def test_sync_agreement_prices_not(
    mocker, mock_mpt_client, mock_adobe_client, agreement_factory, adobe_customer_factory
):
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")
    mock_sync_agreement_prices = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement_prices",
    )

    sync_agreement(mock_mpt_client, agreement_factory(), dry_run=False, sync_prices=False)

    mock_sync_agreement_prices.assert_not_called()


def test_sync_agreement_prices_dry_run(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        )
    )
    mpt_subscription = subscriptions_factory()[0]
    adobe_subscription = adobe_subscription_factory()
    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.return_value = adobe_subscription
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        return_value=mpt_subscription,
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[{"65304578CA01A12": 1234.55}, {"77777777CA01A12": 20.22}],
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    sync_agreement(mocked_mpt_client, agreement, dry_run=True, sync_prices=True)

    mocked_get_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
    )

    mocked_update_agreement_subscription.assert_not_called()
    mocked_update_agreement.assert_not_called()


def test_sync_agreement_prices_exception(
    mocker,
    agreement_factory,
    subscriptions_factory,
    adobe_api_error_factory,
    adobe_customer_factory,
    caplog,
):
    agreement = agreement_factory()
    mpt_subscription = subscriptions_factory()[0]

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory()
    mocked_adobe_client.get_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(code="9999", message="Error from Adobe."),
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        return_value=mpt_subscription,
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )

    with caplog.at_level(logging.ERROR):
        sync_agreement(mocked_mpt_client, agreement, dry_run=False, sync_prices=True)

    assert f"Error synchronizing agreement {agreement['id']}" in caplog.text

    mocked_get_agreement_subscription.assert_called_once_with(
        mocked_mpt_client,
        mpt_subscription["id"],
    )

    mocked_update_agreement_subscription.assert_not_called()
    mocked_update_agreement.assert_not_called()
    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]


def test_sync_agreement_prices_skip_processing(
    mocker, agreement_factory, caplog, adobe_customer_factory
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

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )
    mocked_adobe_client = mocker.MagicMock()
    customer = adobe_customer_factory()
    mocked_adobe_client.get_customer.return_value = customer

    with caplog.at_level(logging.INFO):
        sync_agreement(mocked_mpt_client, agreement, dry_run=False, sync_prices=False)

    assert f"Agreement {agreement['id']} has processing subscriptions, skip it" in caplog.text

    mocked_update_agreement_subscription.assert_not_called()
    mocked_update_agreement.assert_not_called()


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_agreement_ids(mocker, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_ids",
        return_value=[agreement],
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
    )

    sync_agreements_by_agreement_ids(
        mocked_mpt_client,
        [agreement["id"]],
        dry_run=dry_run,
        sync_prices=False,
    )
    mocked_sync_agreement.assert_called_once_with(
        mocked_mpt_client,
        agreement,
        dry_run=dry_run,
        sync_prices=False,
    )


@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_all_agreements(mocker, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocked_mpt_client = mocker.MagicMock()
    mocker.patch(
        "adobe_vipm.flows.sync.get_all_agreements",
        return_value=[agreement],
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
    )

    sync_all_agreements(mocked_mpt_client, dry_run=dry_run)
    mocked_sync_agreement.assert_called_once_with(
        mocked_mpt_client,
        agreement,
        dry_run=dry_run,
        sync_prices=False,
    )


@freeze_time("2024-11-09")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_3yc_end_date(mocker, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocked_mpt_client = mocker.MagicMock()
    mocked_get_agreements_by_query = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_query",
        return_value=[agreement],
        autospec=True,
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
        autospec=True,
    )

    sync_agreements_by_3yc_end_date(mocked_mpt_client, dry_run=dry_run)

    mocked_sync_agreement.assert_called_once_with(
        mocked_mpt_client, agreement, dry_run=dry_run, sync_prices=True
    )
    mocked_get_agreements_by_query.assert_called_once_with(
        mocked_mpt_client,
        "eq(status,Active)&"
        "any(parameters.fulfillment,and(eq(externalId,3YCEndDate),eq(displayValue,2024-11-08)))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2024-11-09)))&"
        "select=lines,parameters,subscriptions,product,listing",
    )


@freeze_time("2025-06-16")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_coterm_date(mocker, agreement_factory, dry_run, mock_mpt_client):
    agreement = agreement_factory()
    mocked_get_agreements_by_query = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_query",
        return_value=[agreement],
        autospec=True,
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
        autospec=True,
    )

    sync_agreements_by_coterm_date(mock_mpt_client, dry_run=dry_run)

    mocked_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        agreement,
        dry_run=dry_run,
        sync_prices=False,
    )
    mocked_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client,
        "eq(status,Active)&"
        "any(parameters.fulfillment,and(eq(externalId,cotermDate),eq(displayValue,2025-06-15)))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2025-06-16)))&"
        "select=lines,parameters,subscriptions,product,listing",
    )


@freeze_time("2025-07-16")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_agreements_by_renewal_date(mocker, agreement_factory, dry_run):
    agreement = agreement_factory()
    mocked_mpt_client = mocker.MagicMock()
    mocked_get_agreements_by_query = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_query",
        return_value=[agreement],
        autospec=True,
    )
    mocked_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
        autospec=True,
    )

    sync_agreements_by_renewal_date(mocked_mpt_client, dry_run=dry_run)

    mocked_sync_agreement.assert_called_once_with(
        mocked_mpt_client,
        agreement,
        dry_run=dry_run,
        sync_prices=True,
    )
    mocked_get_agreements_by_query.assert_called_once_with(
        mocked_mpt_client,
        "eq(status,Active)&"
        "any(subscriptions,any(parameters.fulfillment,and(eq(externalId,renewalDate),in(displayValue,(2025-07-15,2025-06-15,2025-05-15,2025-04-15,2025-03-15,2025-02-15,2025-01-15,2024-12-15,2024-11-15,2024-10-15,2024-09-15,2024-08-15))))&"
        "any(parameters.fulfillment,and(eq(externalId,lastSyncDate),ne(displayValue,2025-07-16)))&"
        "select=lines,parameters,subscriptions,product,listing",
    )


@pytest.mark.parametrize(
    "status",
    [
        constants.ThreeYearCommitmentStatus.ACCEPTED,
        constants.ThreeYearCommitmentStatus.REQUESTED,
    ],
)
def test_sync_agreements_by_3yc_enroll_status_status(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    status,
):
    agreement = agreement_factory()
    mock_get_agreements_by_query = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_enroll_status",
        return_value=[agreement],
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=status)
    )
    mock_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement", autospec=True)
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    mock_get_agreements_by_query.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_update_agreement.assert_called_once_with(
        mock_mpt_client,
        agreement["id"],
        parameters={"fulfillment": [{"externalId": "3YCEnrollStatus", "value": status}]},
    )
    mock_sync_agreement.assert_not_called()


@pytest.mark.parametrize(
    "status",
    [
        constants.ThreeYearCommitmentStatus.COMMITTED,
        constants.ThreeYearCommitmentStatus.ACTIVE,
        constants.ThreeYearCommitmentStatus.DECLINED,
        constants.ThreeYearCommitmentStatus.NONCOMPLIANT,
        constants.ThreeYearCommitmentStatus.EXPIRED,
    ],
)
def test_sync_agreements_by_3yc_enroll_status_full(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    status,
):
    agreement = agreement_factory()
    mock_get_agreements_by_3yc_enroll_status = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_enroll_status",
        return_value=[agreement],
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=status)
    )
    mock_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement", autospec=True)
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    mock_get_agreements_by_3yc_enroll_status.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_update_agreement.assert_not_called()
    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        agreement,
        dry_run=False,
        sync_prices=False,
    )


def test_sync_agreements_by_3yc_enroll_status_status_error(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
):
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_enroll_status",
        side_effect=MPTAPIError(400, {"rql_validation": ["Value has to be a non empty array."]}),
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=constants.ThreeYearCommitmentStatus.EXPIRED)
    )
    mock_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement", autospec=True)
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)

    with pytest.raises(MPTAPIError):
        sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    assert "Unknown exception getting agreements by 3YC enroll status" in caplog.text
    mock_update_agreement.assert_not_called()
    mock_sync_agreement.assert_not_called()


def test_sync_agreements_by_3yc_enroll_status_error_sync(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
):
    agreement = agreement_factory()
    mock_get_agreements_by_3yc_enroll_status = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_enroll_status",
        return_value=[agreement],
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=constants.ThreeYearCommitmentStatus.COMMITTED)
    )
    mock_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
        autospec=True,
        side_effect=AuthorizationNotFoundError("Authorization with uk/id ID not found."),
    )
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    mock_get_agreements_by_3yc_enroll_status.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_update_agreement.assert_not_called()
    mock_sync_agreement.assert_called_once_with(
        mock_mpt_client,
        agreement,
        dry_run=False,
        sync_prices=False,
    )
    assert "Authorization with uk/id ID not found." in caplog.text


def test_sync_agreements_by_3yc_enroll_status_error_sync_unkn(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    adobe_commitment_factory,
    agreement_factory,
    caplog,
):
    agreement = agreement_factory()
    mock_get_agreements_by_3yc_enroll_status = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_enroll_status",
        return_value=[agreement, agreement],
        autospec=True,
    )
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        commitment=adobe_commitment_factory(status=constants.ThreeYearCommitmentStatus.COMMITTED)
    )
    mock_sync_agreement = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement",
        autospec=True,
        side_effect=Exception("Unknown exception getting agreements by 3YC enroll status"),
    )
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    mock_get_agreements_by_3yc_enroll_status.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_update_agreement.assert_not_called()
    mock_sync_agreement.assert_has_calls([
        mocker.call(mock_mpt_client, agreement, dry_run=False, sync_prices=False),
        mocker.call(mock_mpt_client, agreement, dry_run=False, sync_prices=False),
    ])
    assert caplog.messages == [
        "Checking 3YC enroll status for agreement AGR-2119-4550-8674-5962",
        "Unknown exception synchronizing 3YC enroll status for agreement AGR-2119-4550-8674-5962",
        "Checking 3YC enroll status for agreement AGR-2119-4550-8674-5962",
        "Unknown exception synchronizing 3YC enroll status for agreement AGR-2119-4550-8674-5962",
    ]


def test_sync_agreements_by_3yc_enroll_status_no_cust(
    mocker,
    caplog,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_send_exception,
    adobe_customer_factory,
    adobe_commitment_factory,
    mock_get_customer_or_process_lost_customer,
):
    agreement = agreement_factory()
    mock_get_agreements_by_3yc_enroll_status = mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_3yc_enroll_status",
        return_value=[agreement],
        autospec=True,
    )
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        status_code=int(AdobeStatus.INVALID_CUSTOMER.value),
        payload={"code": "1116", "message": "Invalid Customer", "additionalDetails": []},
    )
    mock_sync_agreement = mocker.patch("adobe_vipm.flows.sync.sync_agreement", autospec=True)
    mock_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement", autospec=True)
    mock_get_customer_or_process_lost_customer.return_value = None

    sync_agreements_by_3yc_enroll_status(mock_mpt_client, dry_run=False)

    mock_get_agreements_by_3yc_enroll_status.assert_called_once_with(
        mock_mpt_client, THREE_YC_TEMP_3YC_STATUSES
    )
    mock_get_customer_or_process_lost_customer.assert_called_once_with(
        mock_mpt_client, mock_adobe_client, agreement, customer_id=""
    )
    mock_update_agreement.assert_not_called()
    mock_sync_agreement.assert_not_called()
    assert caplog.messages == ["Checking 3YC enroll status for agreement AGR-2119-4550-8674-5962"]


@freeze_time("2024-11-09 12:30:00")
def test_sync_agreement_prices_with_3yc(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_commitment_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_adobe_client,
    mock_get_adobe_client,
    mock_mpt_client,
    mock_update_agreement_subscription,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11)
    )
    mpt_subscription = subscriptions_factory()[0]
    adobe_subscription = adobe_subscription_factory()
    mock_adobe_client.get_subscriptions.return_value = {"items": [adobe_subscription]}
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04",
        commitment=adobe_commitment_factory(licenses=9, consumables=1220),
        recommitment_request=adobe_commitment_factory(status="ACCEPTED"),
    )
    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription", return_value=mpt_subscription
    )
    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_3yc_skus",
        side_effect=[{"65304578CA01A12": 1234.55}, {"77777777CA01A12": 20.22}],
    )
    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    mocked_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        mpt_subscription["id"],
    )
    mock_update_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        mpt_subscription["id"],
        lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
        parameters={
            "fulfillment": [
                {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                {
                    "externalId": Param.CURRENT_QUANTITY.value,
                    "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                },
                {
                    "externalId": Param.RENEWAL_QUANTITY.value,
                    "value": str(adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]),
                },
                {
                    "externalId": "renewalDate",
                    "value": adobe_subscription["renewalDate"],
                },
                {"externalId": "lastSyncDate", "value": "2024-11-09"},
            ]
        },
        commitmentDate="2025-04-04",
        autoRenew=adobe_subscription["autoRenewal"]["enabled"],
    )

    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)

    assert mocked_update_agreement.call_args_list == [
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=expected_lines,
            parameters={
                "fulfillment": [
                    {"externalId": "3YCRecommitmentRequestStatus", "value": "ACCEPTED"},
                    {"externalId": "3YCRecommitment", "value": None},
                    {"externalId": "3YCEnrollStatus", "value": "COMMITTED"},
                    {"externalId": "3YCStartDate", "value": "2024-01-01"},
                    {"externalId": "3YCEndDate", "value": "2025-01-01"},
                ],
                "ordering": [
                    {"externalId": "3YCLicenses", "value": "9"},
                    {"externalId": "3YCConsumables", "value": "1220"},
                ],
            },
        ),
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2024-11-09"}]},
        ),
    ]


@freeze_time("2025-06-19")
@pytest.mark.parametrize("dry_run", [True, False])
def test_sync_global_customer_parameter(
    mocker,
    agreement_factory,
    subscriptions_factory,
    fulfillment_parameters_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_mpt_client,
    mock_adobe_client,
    mock_get_adobe_client,
    dry_run,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        subscriptions=[
            {"id": "SUB-1000-2000-3000", "status": "Active", "item": {"id": "ITM-0000-0001-0001"}},
            {"id": "SUB-1234-5678", "status": "Terminated", "item": {"id": "ITM-0000-0001-0002"}},
            {"id": "SUB-1000-2000-5000", "status": "Active", "item": {"id": "ITM-0000-0001-0003"}},
        ],
    )
    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    deployment_subscription = subscriptions_factory(adobe_subscription_id="d-sub-id")[0]
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    adobe_deployment_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=20,
        renewal_quantity=20,
    )
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription,
            another_adobe_subscription,
            adobe_deployment_subscription,
            {**adobe_deployment_subscription, "subscriptionId": "d-sub-id"},
        ]
    }
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04", global_sales_enabled=True
    )
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    deployment_agreements = [
        agreement_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id="deployment-1", deployments=""
            ),
            lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        )
    ]
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_customer_deployments",
        return_value=deployment_agreements,
    )
    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        side_effect=[mpt_subscription, another_mpt_subscription, deployment_subscription],
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        ],
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription"
    )

    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")

    sync_agreement(mock_mpt_client, agreement, dry_run=dry_run, sync_prices=True)

    assert mocked_get_agreement_subscription.call_args_list == [
        mocker.call(mock_mpt_client, mpt_subscription["id"]),
        mocker.call(mock_mpt_client, another_mpt_subscription["id"]),
        mocker.call(mock_mpt_client, deployment_subscription["id"]),
    ]

    if not dry_run:
        assert mocked_update_agreement_subscription.call_args_list == [
            mocker.call(
                mock_mpt_client,
                mpt_subscription["id"],
                lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
                parameters={
                    "fulfillment": [
                        {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                        {
                            "externalId": Param.CURRENT_QUANTITY.value,
                            "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                        },
                        {
                            "externalId": Param.RENEWAL_QUANTITY.value,
                            "value": str(
                                adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                            ),
                        },
                        {
                            "externalId": "renewalDate",
                            "value": adobe_subscription["renewalDate"],
                        },
                        {"externalId": "lastSyncDate", "value": "2025-06-19"},
                    ]
                },
                commitmentDate="2025-04-04",
                autoRenew=adobe_subscription["autoRenewal"]["enabled"],
            ),
            mocker.call(
                mock_mpt_client,
                another_mpt_subscription["id"],
                lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}}],
                parameters={
                    "fulfillment": [
                        {"externalId": "adobeSKU", "value": "77777777CA01A12"},
                        {
                            "externalId": Param.CURRENT_QUANTITY.value,
                            "value": str(another_adobe_subscription[Param.CURRENT_QUANTITY.value]),
                        },
                        {
                            "externalId": Param.RENEWAL_QUANTITY.value,
                            "value": str(
                                another_adobe_subscription["autoRenewal"][
                                    Param.RENEWAL_QUANTITY.value
                                ]
                            ),
                        },
                        {
                            "externalId": "renewalDate",
                            "value": another_adobe_subscription["renewalDate"],
                        },
                        {"externalId": "lastSyncDate", "value": "2025-06-19"},
                    ]
                },
                commitmentDate="2025-04-04",
                autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
            ),
            mocker.call(
                mock_mpt_client,
                deployment_subscription["id"],
                lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}}],
                parameters={
                    "fulfillment": [
                        {"externalId": "adobeSKU", "value": "77777777CA01A12"},
                        {
                            "externalId": Param.CURRENT_QUANTITY.value,
                            "value": str(
                                adobe_deployment_subscription[Param.CURRENT_QUANTITY.value]
                            ),
                        },
                        {
                            "externalId": Param.RENEWAL_QUANTITY.value,
                            "value": str(
                                adobe_deployment_subscription["autoRenewal"][
                                    Param.RENEWAL_QUANTITY.value
                                ]
                            ),
                        },
                        {
                            "externalId": "renewalDate",
                            "value": adobe_deployment_subscription["renewalDate"],
                        },
                        {"externalId": "lastSyncDate", "value": "2025-06-19"},
                    ]
                },
                commitmentDate="2025-04-04",
                autoRenew=adobe_deployment_subscription["autoRenewal"]["enabled"],
            ),
        ]

    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)
    if not dry_run:
        assert mocked_update_agreement.call_args_list == [
            mocker.call(mock_mpt_client, agreement["id"], lines=expected_lines, parameters={}),
            mocker.call(
                mock_mpt_client,
                agreement["id"],
                parameters={
                    "fulfillment": [
                        {"externalId": "globalCustomer", "value": ["Yes"]},
                        {"externalId": "deployments", "value": "deployment-id - DE"},
                    ]
                },
            ),
            mocker.call(
                mock_mpt_client, deployment_agreements[0]["id"], lines=expected_lines, parameters={}
            ),
            mocker.call(
                mock_mpt_client,
                deployment_agreements[0]["id"],
                parameters={
                    "fulfillment": [
                        {
                            "id": "PAR-3528-2927",
                            "name": "3YC End Date",
                            "externalId": "3YCEndDate",
                            "type": "Date",
                            "value": "",
                        },
                        {
                            "id": "PAR-9876-5432",
                            "name": "3YC Enroll Status",
                            "externalId": "3YCEnrollStatus",
                            "type": "SingleLineText",
                            "value": "",
                        },
                        {
                            "id": "PAR-2266-4848",
                            "name": "3YC Start Date",
                            "externalId": "3YCStartDate",
                            "type": "Date",
                            "value": "",
                        },
                    ]
                },
            ),
            mocker.call(
                mock_mpt_client,
                deployment_agreements[0]["id"],
                parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-19"}]},
            ),
        ]


@freeze_time("2025-06-19")
def test_sync_global_customer_parameter_not_prices(
    mocker, caplog, mock_mpt_client, mock_adobe_client, agreement_factory
):
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mocker.patch(
        "adobe_vipm.flows.sync.get_agreements_by_customer_deployments",
        return_value=[agreement_factory()],
    )
    mock_sync_agreement_prices = mocker.patch(
        "adobe_vipm.flows.sync.sync_agreement_prices",
    )

    sync_agreement(mock_mpt_client, agreement_factory(), dry_run=False, sync_prices=False)

    mock_sync_agreement_prices.assert_not_called()
    assert caplog.messages == [
        "Synchronizing agreement AGR-2119-4550-8674-5962...",
        "Skipping price sync - sync_prices False.",
        "Agreement updated AGR-2119-4550-8674-5962",
        "Setting global customer for agreement AGR-2119-4550-8674-5962",
        "Setting deployments for agreement AGR-2119-4550-8674-5962",
        "Looking for orphaned deployment subscriptions in Adobe.",
        "Skipping price sync - sync_prices False.",
        "Agreement updated AGR-2119-4550-8674-5962",
        "Updating Last Sync Date for agreement AGR-2119-4550-8674-5962",
    ]


@freeze_time("2025-06-30")
def test_sync_global_customer_update_not_required(
    mocker,
    agreement_factory,
    fulfillment_parameters_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_adobe_client,
    mock_mpt_client,
    mock_get_adobe_client,
    mock_get_agreement_subscription,
    mock_get_prices_for_skus,
    mock_get_agreements_by_customer_deployments,
    mock_update_agreement_subscription,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        fulfillment_parameters=[
            {"externalId": "globalCustomer", "value": ["Yes"]},
            {"externalId": "deployments", "value": "deployment-id - DE"},
        ],
        subscriptions=[
            {"id": "SUB-1000-2000-3000", "status": "Active", "item": {"id": "ITM-0000-0001-0001"}},
            {"id": "SUB-1234-5678", "status": "Terminated", "item": {"id": "ITM-0000-0001-0002"}},
            {"id": "SUB-1000-2000-5000", "status": "Active", "item": {"id": "ITM-0000-0001-0003"}},
        ],
    )
    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    deployment_subscription = subscriptions_factory(adobe_subscription_id="d-sub-id")[0]
    another_deployment_subscription = subscriptions_factory(adobe_subscription_id="d-sub-id")[0]
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    adobe_deployment_subscription = adobe_subscription_factory()
    another_adobe_deployment_subscription = adobe_subscription_factory()
    mock_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        another_adobe_subscription,
        adobe_deployment_subscription,
        another_adobe_deployment_subscription,
    ]
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription,
            another_adobe_subscription,
            adobe_deployment_subscription,
            another_adobe_deployment_subscription,
            {**another_adobe_deployment_subscription, "subscriptionId": "d-sub-id"},
        ]
    }
    mock_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "DE"}},
        }
    ]
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04", global_sales_enabled=True
    )
    mock_get_agreement_subscription.side_effect = [
        mpt_subscription,
        another_mpt_subscription,
        deployment_subscription,
        another_deployment_subscription,
    ]
    mock_get_prices_for_skus.return_value = {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22}
    mock_get_agreements_by_customer_deployments.return_value = [
        agreement_factory(
            fulfillment_parameters=fulfillment_parameters_factory(
                global_customer="", deployment_id=f"deployment-{i}", deployments=""
            )
        )
        for i in range(2)
    ]
    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    assert mock_get_agreement_subscription.call_args_list == [
        mocker.call(mock_mpt_client, mpt_subscription["id"]),
        mocker.call(mock_mpt_client, another_mpt_subscription["id"]),
        mocker.call(mock_mpt_client, deployment_subscription["id"]),
        mocker.call(mock_mpt_client, another_deployment_subscription["id"]),
    ]
    assert mock_update_agreement_subscription.call_args_list == [
        mocker.call(
            mock_mpt_client,
            mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {"externalId": "renewalDate", "value": adobe_subscription["renewalDate"]},
                    {"externalId": "lastSyncDate", "value": "2025-06-30"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_subscription["autoRenewal"]["enabled"],
        ),
        mocker.call(
            mock_mpt_client,
            another_mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}}],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "77777777CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(another_adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            another_adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": another_adobe_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-30"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
        ),
        mocker.call(
            mock_mpt_client,
            deployment_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_deployment_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_deployment_subscription["autoRenewal"][
                                Param.RENEWAL_QUANTITY.value
                            ]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_deployment_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-30"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_deployment_subscription["autoRenewal"]["enabled"],
        ),
        mocker.call(
            mock_mpt_client,
            another_deployment_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(
                            another_adobe_deployment_subscription[Param.CURRENT_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            another_adobe_deployment_subscription["autoRenewal"][
                                Param.RENEWAL_QUANTITY.value
                            ]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": another_adobe_deployment_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-30"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=another_adobe_deployment_subscription["autoRenewal"]["enabled"],
        ),
    ]
    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)
    assert mocked_update_agreement.mock_calls[0] == mocker.call(
        mock_mpt_client, agreement["id"], lines=expected_lines, parameters={}
    )
    mock_adobe_client.get_customer_deployments_active_status.assert_called_once()


@freeze_time("2025-06-30")
def test_sync_global_customer_update_adobe_error(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_api_error_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_adobe_client,
    mock_get_adobe_client,
    mock_mpt_client,
):
    agreement = agreement_factory(
        lines=lines_factory(external_vendor_id="77777777CA", unit_purchase_price=10.11),
        fulfillment_parameters=[
            {"externalId": "globalCustomer", "value": ["Yes"]},
            {"externalId": "deployments", "value": "deployment-id - DE"},
        ],
        subscriptions=[
            {"id": "SUB-1000-2000-3000", "status": "Active", "item": {"id": "ITM-0000-0001-0001"}},
            {"id": "SUB-1234-5678", "status": "Terminated", "item": {"id": "ITM-0000-0001-0002"}},
            {"id": "SUB-1000-2000-5000", "status": "Active", "item": {"id": "ITM-0000-0001-0003"}},
        ],
    )
    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [adobe_subscription, another_adobe_subscription]
    }
    adobe_error = AdobeAPIError(400, adobe_api_error_factory("9999", "some error"))
    mock_adobe_client.get_customer_deployments_active_status.side_effect = adobe_error
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04", global_sales_enabled=True
    )
    mocked_get_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        side_effect=[mpt_subscription, another_mpt_subscription],
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        ],
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription"
    )

    mocked_update_agreement = mocker.patch("adobe_vipm.flows.sync.update_agreement")

    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams"
    )

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    assert mocked_get_agreement_subscription.call_args_list == [
        mocker.call(mock_mpt_client, mpt_subscription["id"]),
        mocker.call(mock_mpt_client, another_mpt_subscription["id"]),
    ]

    assert mocked_update_agreement_subscription.call_args_list == [
        mocker.call(
            mock_mpt_client,
            mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 1234.55}}],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "65304578CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": adobe_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-30"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=adobe_subscription["autoRenewal"]["enabled"],
        ),
        mocker.call(
            mock_mpt_client,
            another_mpt_subscription["id"],
            lines=[{"id": "ALI-2119-4550-8674-5962-0001", "price": {"unitPP": 20.22}}],
            parameters={
                "fulfillment": [
                    {"externalId": "adobeSKU", "value": "77777777CA01A12"},
                    {
                        "externalId": Param.CURRENT_QUANTITY.value,
                        "value": str(another_adobe_subscription[Param.CURRENT_QUANTITY.value]),
                    },
                    {
                        "externalId": Param.RENEWAL_QUANTITY.value,
                        "value": str(
                            another_adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
                        ),
                    },
                    {
                        "externalId": "renewalDate",
                        "value": another_adobe_subscription["renewalDate"],
                    },
                    {"externalId": "lastSyncDate", "value": "2025-06-30"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=another_adobe_subscription["autoRenewal"]["enabled"],
        ),
    ]

    expected_lines = lines_factory(external_vendor_id="77777777CA", unit_purchase_price=20.22)
    mocked_update_agreement.assert_called_once_with(
        mock_mpt_client, agreement["id"], lines=expected_lines, parameters={}
    )
    mock_adobe_client.get_customer_deployments_active_status.assert_called_once()
    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]


def test_sync_global_customer_parameters_error(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_api_error_factory,
    mock_get_adobe_product_by_marketplace_sku,
    caplog,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        ),
        fulfillment_parameters=[
            {"externalId": "globalCustomer", "value": ["Yes"]},
            {"externalId": "deployments", "value": "deployment-id - DE"},
        ],
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0001",
                },
            },
            {
                "id": "SUB-1234-5678",
                "status": "Terminated",
                "item": {
                    "id": "ITM-0000-0001-0002",
                },
            },
            {
                "id": "SUB-1000-2000-5000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0003",
                },
            },
        ],
    )
    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )

    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()
    mocked_adobe_client.get_subscription.side_effect = [
        adobe_subscription,
        another_adobe_subscription,
    ]
    mocked_adobe_client.get_customer_deployments_active_status.return_value = [
        {
            "deploymentId": "deployment-id",
            "status": "1000",
            "companyProfile": {"address": {"country": "UK"}},
        }
    ]
    mocked_adobe_client.get_customer.return_value = adobe_customer_factory(
        coterm_date="2025-04-04",
        global_sales_enabled=True,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        side_effect=[mpt_subscription, another_mpt_subscription],
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
            {"65304578CA01A12": 1234.55, "77777777CA01A12": 20.22},
        ],
    )

    mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )

    mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
        side_effect=[mocker.MagicMock(), AdobeAPIError(400, {"error": "some error"})],
    )

    mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )

    with caplog.at_level(logging.ERROR):
        sync_agreement(mocked_mpt_client, agreement, dry_run=False, sync_prices=False)

    # TODO: real exception here is TypeError: '>' not supported between instances
    # of 'MagicMock' and 'MagicMock'. Need to fix.
    assert caplog.records[0].message == (
        "Error setting global customer parameters for agreement AGR-2119-4550-8674-5962."
    )


def test_sync_agreement_error_getting_adobe_customer(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    adobe_api_error_factory,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        ),
        fulfillment_parameters=[
            {"externalId": "globalCustomer", "value": ["Yes"]},
            {"externalId": "deployments", "value": "deployment-id - DE"},
        ],
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0001",
                },
            },
            {
                "id": "SUB-1234-5678",
                "status": "Terminated",
                "item": {
                    "id": "ITM-0000-0001-0002",
                },
            },
            {
                "id": "SUB-1000-2000-5000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0003",
                },
            },
        ],
    )
    mocked_mpt_client = mocker.MagicMock()

    mocked_adobe_client = mocker.MagicMock()

    adobe_error = AdobeAPIError(
        400,
        adobe_api_error_factory(
            "9999",
            "some error",
        ),
    )
    mocked_adobe_client.get_customer.side_effect = adobe_error

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )
    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )
    sync_agreement(mocked_mpt_client, agreement, dry_run=False, sync_prices=False)
    mocked_adobe_client.get_customer.assert_called_once()
    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]


def test_sync_agreement_notify_exception(
    mocker,
    agreement_factory,
):
    mock_notify_agreement_unhandled_exception_in_teams = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams"
    )
    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_customer_id",
        side_effect=Exception("Test exception"),
    )
    mpt_client = mocker.MagicMock()
    agreement = agreement_factory()
    sync_agreement(mpt_client, agreement, dry_run=False, sync_prices=False)
    mock_notify_agreement_unhandled_exception_in_teams.assert_called_once()
    assert (
        mock_notify_agreement_unhandled_exception_in_teams.call_args_list[0].args[0]
        == agreement["id"]
    )


def test_sync_agreement_empty_discounts(
    mocker,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    caplog,
):
    agreement = agreement_factory(
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0001",
                },
            },
        ],
    )

    mocked_mpt_client = mocker.MagicMock()
    mocked_adobe_client = mocker.MagicMock()

    customer = adobe_customer_factory()
    customer["discounts"] = []

    mocked_adobe_client.get_customer.return_value = customer

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mocked_adobe_client,
    )

    mocked_notifier = mocker.patch(
        "adobe_vipm.flows.sync.notify_agreement_unhandled_exception_in_teams",
    )

    sync_agreement(mocked_mpt_client, agreement, dry_run=False, sync_prices=False)

    mocked_notifier.assert_called_once()
    assert mocked_notifier.call_args_list[0].args[0] == agreement["id"]
    assert "does not have discounts information" in mocked_notifier.call_args_list[0].args[1]


@freeze_time("2025-06-19")
def test_sync_agreement_prices_with_missing_prices(
    mocker,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    mock_get_adobe_product_by_marketplace_sku,
    mock_terminate_subscription,
    mock_mpt_client,
    mock_adobe_client,
    caplog,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        ),
        subscriptions=[
            {
                "id": "SUB-1000-2000-3000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0001",
                },
            },
            {
                "id": "SUB-1000-2000-5000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0003",
                },
            },
            {
                "id": "SUB-1000-2000-6000",
                "status": "Active",
                "item": {
                    "id": "ITM-0000-0001-0004",
                },
            },
        ],
    )

    mpt_subscription = subscriptions_factory()[0]
    another_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A12",
        adobe_subscription_id="b-sub-id",
        subscription_id="SUB-1000-2000-5000",
    )[0]
    terminated_mpt_subscription = subscriptions_factory(
        adobe_sku="77777777CA01A13",
        adobe_subscription_id="c-sub-id",
        subscription_id="SUB-1000-2000-6000",
    )[0]

    adobe_subscription = adobe_subscription_factory()
    another_adobe_subscription = adobe_subscription_factory(
        subscription_id="b-sub-id",
        offer_id="77777777CA01A12",
        current_quantity=15,
        renewal_quantity=15,
    )
    terminated_adobe_subscription = adobe_subscription_factory(
        subscription_id="c-sub-id",
        offer_id="77777777CA01A13",
        current_quantity=10,
        renewal_quantity=10,
        status="1004",
    )
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription,
            another_adobe_subscription,
            terminated_adobe_subscription,
        ]
    }
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")

    mocker.patch(
        "adobe_vipm.flows.sync.get_adobe_client",
        return_value=mock_adobe_client,
    )

    mocker.patch(
        "adobe_vipm.flows.sync.get_agreement_subscription",
        side_effect=[
            mpt_subscription,
            another_mpt_subscription,
            terminated_mpt_subscription,
        ],
    )

    mocker.patch(
        "adobe_vipm.airtable.models.get_prices_for_skus",
        side_effect=[
            {"77777777CA01A12": 20.22},
            {"77777777CA01A12": 20.22},
        ],
    )

    mocked_notify_missing_prices = mocker.patch(
        "adobe_vipm.flows.sync.notify_missing_prices",
    )

    mocked_update_agreement_subscription = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement_subscription",
    )
    mocked_update_agreement = mocker.patch(
        "adobe_vipm.flows.sync.update_agreement",
    )

    with caplog.at_level(logging.ERROR):
        sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=True)

    assert "Skipping subscription" in caplog.text
    assert "65304578CA01A12" in caplog.text

    mocked_notify_missing_prices.assert_called_once()
    call_args = mocked_notify_missing_prices.call_args[0]
    assert call_args[0] == agreement["id"]
    assert "65304578CA01A12" in call_args[1]
    assert call_args[2] == agreement["product"]["id"]
    assert call_args[3] == agreement["listing"]["priceList"]["currency"]

    mocked_update_agreement.call_args_list = [
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            lines=agreement["lines"],
        ),
        mocker.call(
            mock_mpt_client,
            agreement["id"],
            parameters={"fulfillment": [{"externalId": "lastSyncDate", "value": "2025-06-19"}]},
        ),
    ]

    mock_adobe_client.get_subscriptions.assert_called_once_with("AUT-1234-5678", "a-client-id")

    assert mocked_update_agreement_subscription.mock_calls == [
        mocker.call(
            mock_mpt_client,
            another_mpt_subscription["id"],
            lines=[{"price": {"unitPP": 20.22}, "id": "ALI-2119-4550-8674-5962-0001"}],
            parameters={
                "fulfillment": [
                    {"externalId": Param.ADOBE_SKU.value, "value": "77777777CA01A12"},
                    {"externalId": Param.CURRENT_QUANTITY.value, "value": "15"},
                    {"externalId": Param.RENEWAL_QUANTITY.value, "value": "15"},
                    {"externalId": Param.RENEWAL_DATE.value, "value": "2026-06-20"},
                    {"externalId": Param.LAST_SYNC_DATE.value, "value": "2025-06-19"},
                ]
            },
            commitmentDate="2025-04-04",
            autoRenew=True,
        ),
    ]
    mock_terminate_subscription.assert_called_once_with(
        mock_mpt_client, "SUB-1000-2000-6000", "Adobe subscription status 1004."
    )


@pytest.mark.usefixtures("mock_get_agreements_by_customer_deployments")
def test_sync_agreement_lost_customer(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    agreement_factory,
    mock_terminate_subscription,
    mock_notify_processing_lost_customer,
    caplog,
):
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        status_code=int(AdobeStatus.INVALID_CUSTOMER.value),
        payload={"code": "1116", "message": "Invalid Customer", "additionalDetails": []},
    )

    sync_agreement(mock_mpt_client, agreement_factory(), dry_run=False, sync_prices=False)

    assert mock_terminate_subscription.mock_calls == [
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
    ]
    assert mock_notify_processing_lost_customer.mock_calls == [
        mocker.call(
            "🔥 Executing Lost Customer Procedure.",
            "Received Adobe error 1116 - Invalid Customer, assuming lost customer and proceeding"
            " with lost customer procedure.",
            "#541c2e",
            button=None,
            facts=None,
        )
    ]
    assert [rec.message for rec in caplog.records] == [
        "Synchronizing agreement AGR-2119-4550-8674-5962...",
        "Received Adobe error 1116 - Invalid Customer, assuming lost customer and"
        " proceeding with lost customer procedure.",
        ">>> Suspected Lost Customer: Terminating subscription SUB-1000-2000-3000.",
    ]


@pytest.mark.usefixtures("mock_get_agreements_by_customer_deployments")
def test_sync_agreement_lost_customer_error(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    mpt_error_factory,
    agreement_factory,
    mock_terminate_subscription,
    mock_notify_processing_lost_customer,
    caplog,
):
    mock_adobe_client.get_customer.side_effect = AdobeAPIError(
        status_code=int(AdobeStatus.INVALID_CUSTOMER.value),
        payload={"code": "1116", "message": "Invalid Customer", "additionalDetails": []},
    )
    mock_terminate_subscription.side_effect = [
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
        MPTAPIError(500, mpt_error_factory(500, "Internal Server Error", "Oops!")),
    ]

    sync_agreement(mock_mpt_client, agreement_factory(), dry_run=False, sync_prices=False)

    assert mock_terminate_subscription.mock_calls == [
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
        mocker.call(mock_mpt_client, "SUB-1000-2000-3000", "Suspected Lost Customer"),
    ]
    assert mock_notify_processing_lost_customer.mock_calls == [
        mocker.call(
            "🔥 Executing Lost Customer Procedure.",
            "Received Adobe error 1116 - Invalid Customer, assuming lost customer and proceeding"
            " with lost customer procedure.",
            "#541c2e",
            button=None,
            facts=None,
        ),
        mocker.call(
            "🔥 Executing Lost Customer Procedure.",
            ">>> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000: 500"
            " Internal Server Error - Oops!"
            " (00-27cdbfa231ecb356ab32c11b22fd5f3c-721db10d009dfa2a-00)",
            "#541c2e",
            button=None,
            facts=None,
        ),
        mocker.call(
            "🔥 Executing Lost Customer Procedure.",
            ">>> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000: 500"
            " Internal Server Error - Oops!"
            " (00-27cdbfa231ecb356ab32c11b22fd5f3c-721db10d009dfa2a-00)",
            "#541c2e",
            button=None,
            facts=None,
        ),
        mocker.call(
            "🔥 Executing Lost Customer Procedure.",
            ">>> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000: 500"
            " Internal Server Error - Oops!"
            " (00-27cdbfa231ecb356ab32c11b22fd5f3c-721db10d009dfa2a-00)",
            "#541c2e",
            button=None,
            facts=None,
        ),
    ]

    assert [rec.message for rec in caplog.records] == [
        "Synchronizing agreement AGR-2119-4550-8674-5962...",
        "Received Adobe error 1116 - Invalid Customer, assuming lost customer and"
        " proceeding with lost customer procedure.",
        ">>> Suspected Lost Customer: Terminating subscription SUB-1000-2000-3000.",
        ">>> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000.",
        ">>> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000.",
        ">>> Suspected Lost Customer: Error terminating subscription SUB-1000-2000-3000.",
    ]


@pytest.mark.parametrize(
    "status",
    (s.value for s in AgreementStatus if s is not AgreementStatus.ACTIVE),
)
def test_sync_agreement_skips_inactive_agreement(
    mock_mpt_client, mock_get_adobe_client, mock_update_last_sync_date, status
):
    agreement = {"id": "1", "status": status, "subscriptions": []}

    sync_agreement(mock_mpt_client, agreement, dry_run=False, sync_prices=False)

    mock_update_last_sync_date.assert_not_called()


def test_get_subscriptions_for_update_skip_adobe_inactive(
    mock_mpt_client,
    mock_adobe_client,
    adobe_customer_factory,
    agreement_factory,
    adobe_subscription_factory,
    mock_get_agreement_subscription,
):
    customer_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]

    assert (
        _get_subscriptions_for_update(
            mock_mpt_client, agreement_factory(), adobe_customer_factory(), customer_subscriptions
        )
        == []
    )


@freeze_time("2025-07-23")
def test_get_subscriptions_for_update_terminated(
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_terminate_subscription,
    mock_get_agreement_subscription,
    mock_update_agreement_subscription,
):
    customer_subscriptions = [
        adobe_subscription_factory(status=AdobeStatus.SUBSCRIPTION_TERMINATED.value)
    ]

    _get_subscriptions_for_update(
        mock_mpt_client, agreement_factory(), adobe_customer_factory(), customer_subscriptions
    )

    mock_get_agreement_subscription.assert_called_once_with(
        mock_mpt_client, mock_get_agreement_subscription.return_value["id"]
    )
    mock_terminate_subscription.assert_called_once_with(
        mock_mpt_client,
        mock_get_agreement_subscription.return_value["id"],
        "Adobe subscription status 1004.",
    )
    mock_update_agreement_subscription.assert_not_called()


def test_add_missing_subscriptions_none(
    mocker,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_create_agreement_subscription,
):
    customer_subscriptions = [
        adobe_subscription_factory(subscription_id=f"subscriptionId{i}") for i in range(3)
    ]

    _add_missing_subscriptions(
        mock_mpt_client,
        mock_adobe_client,
        adobe_customer_factory(),
        agreement_factory(),
        subscriptions_for_update=("subscriptionId2", "subscriptionId1", "subscriptionId0"),
        customer_subscriptions=customer_subscriptions,
    )

    mock_create_agreement_subscription.assert_not_called()


@freeze_time("2025-07-24")
def test_add_missing_subscriptions(
    mocker,
    items_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_get_prices_for_skus,
    mock_get_product_items_by_skus,
    mock_create_agreement_subscription,
    mock_notify_processing_lost_customer,
):
    customer_subscriptions = [
        adobe_subscription_factory(subscription_id=f"subscriptionId{i}") for i in range(4)
    ]
    customer_subscriptions[-1]["deploymentId"] = "deploymentId"
    mock_get_prices_for_skus.return_value = {s["offerId"]: 12.14 for s in customer_subscriptions}

    _add_missing_subscriptions(
        mock_mpt_client,
        mock_adobe_client,
        adobe_customer_factory(),
        agreement_factory(),
        subscriptions_for_update=("subscriptionId1", "b-sub-id"),
        customer_subscriptions=customer_subscriptions,
    )

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", ["65304578CA", "65304578CA", "65304578CA"]
    )
    assert mock_create_agreement_subscription.mock_calls == [
        mocker.call(
            mock_mpt_client,
            {
                "status": SubscriptionStatus.ACTIVE.value,
                "commitmentDate": "2026-07-25",
                "price": {"unitPP": {"65304578CA01A12": 12.14}},
                "parameters": {
                    "fulfillment": [
                        {"externalId": Param.ADOBE_SKU.value, "value": "65304578CA01A12"},
                        {"externalId": Param.CURRENT_QUANTITY.value, "value": "10"},
                        {"externalId": Param.RENEWAL_QUANTITY.value, "value": "10"},
                        {"externalId": Param.RENEWAL_DATE.value, "value": "2026-07-25"},
                    ]
                },
                "agreement": {"id": "AGR-2119-4550-8674-5962"},
                "buyer": {"id": "BUY-3731-7971"},
                "licensee": {"id": "LC-321-321-321"},
                "seller": {"id": "SEL-9121-8944"},
                "lines": [
                    {
                        "quantity": 10,
                        "item": {
                            "id": "ITM-1234-1234-1234-0001",
                            "name": "Awesome product",
                            "externalIds": {"vendor": "65304578CA"},
                            "terms": {"period": "1y"},
                        },
                        "price": {"unitPP": 12.14},
                    }
                ],
                "name": "Subscription for {agreement['product']['name']}",
                "startDate": "2019-05-20T22:49:55Z",
                "externalIds": {"vendor": "subscriptionId0"},
                "product": {"id": "PRD-1111-1111"},
                "autoRenew": True,
            },
        ),
        mocker.call(
            mock_mpt_client,
            {
                "status": SubscriptionStatus.ACTIVE.value,
                "commitmentDate": "2026-07-25",
                "price": {"unitPP": {"65304578CA01A12": 12.14}},
                "parameters": {
                    "fulfillment": [
                        {"externalId": Param.ADOBE_SKU.value, "value": "65304578CA01A12"},
                        {"externalId": Param.CURRENT_QUANTITY.value, "value": "10"},
                        {"externalId": Param.RENEWAL_QUANTITY.value, "value": "10"},
                        {"externalId": Param.RENEWAL_DATE.value, "value": "2026-07-25"},
                    ]
                },
                "agreement": {"id": "AGR-2119-4550-8674-5962"},
                "buyer": {"id": "BUY-3731-7971"},
                "licensee": {"id": "LC-321-321-321"},
                "seller": {"id": "SEL-9121-8944"},
                "lines": [
                    {
                        "quantity": 10,
                        "item": {
                            "id": "ITM-1234-1234-1234-0001",
                            "name": "Awesome product",
                            "externalIds": {"vendor": "65304578CA"},
                            "terms": {"period": "1y"},
                        },
                        "price": {"unitPP": 12.14},
                    }
                ],
                "name": "Subscription for {agreement['product']['name']}",
                "startDate": "2019-05-20T22:49:55Z",
                "externalIds": {"vendor": "subscriptionId2"},
                "product": {"id": "PRD-1111-1111"},
                "autoRenew": True,
            },
        ),
    ]


@freeze_time("2025-07-24")
def test_add_missing_subscriptions_deployment(
    items_factory,
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_get_prices_for_skus,
    mock_get_product_items_by_skus,
    fulfillment_parameters_factory,
    mock_create_agreement_subscription,
    mock_notify_processing_lost_customer,
):
    adobe_subscriptions = [
        adobe_subscription_factory(subscription_id=f"subscriptionId{i}") for i in range(4)
    ]
    adobe_subscriptions[-1]["deploymentId"] = "deploymentId"
    mock_adobe_client.get_subscriptions.return_value = {"items": adobe_subscriptions}
    adobe_customer = adobe_customer_factory()
    mock_get_prices_for_skus.return_value = {s["offerId"]: 12.14 for s in adobe_subscriptions}

    _add_missing_subscriptions(
        mock_mpt_client,
        mock_adobe_client,
        adobe_customer,
        agreement_factory(
            fulfillment_parameters=fulfillment_parameters_factory(deployment_id="deploymentId")
        ),
        subscriptions_for_update=("subscriptionId1", "b-sub-id"),
        customer_subscriptions=adobe_subscriptions,
    )

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", ["65304578CA"]
    )
    mock_create_agreement_subscription.assert_called_once_with(
        mock_mpt_client,
        {
            "status": SubscriptionStatus.ACTIVE.value,
            "commitmentDate": "2026-07-25",
            "price": {"unitPP": {"65304578CA01A12": 12.14}},
            "parameters": {
                "fulfillment": [
                    {"externalId": Param.ADOBE_SKU.value, "value": "65304578CA01A12"},
                    {"externalId": Param.CURRENT_QUANTITY.value, "value": "10"},
                    {"externalId": Param.RENEWAL_QUANTITY.value, "value": "10"},
                    {"externalId": Param.RENEWAL_DATE.value, "value": "2026-07-25"},
                ]
            },
            "agreement": {"id": "AGR-2119-4550-8674-5962"},
            "buyer": {"id": "BUY-3731-7971"},
            "licensee": {"id": "LC-321-321-321"},
            "seller": {"id": "SEL-9121-8944"},
            "lines": [
                {
                    "quantity": 10,
                    "item": {
                        "id": "ITM-1234-1234-1234-0001",
                        "name": "Awesome product",
                        "externalIds": {"vendor": "65304578CA"},
                        "terms": {"period": "1y"},
                    },
                    "price": {"unitPP": 12.14},
                }
            ],
            "name": "Subscription for {agreement['product']['name']}",
            "startDate": "2019-05-20T22:49:55Z",
            "externalIds": {"vendor": "subscriptionId3"},
            "product": {"id": "PRD-1111-1111"},
            "autoRenew": True,
        },
    )


@freeze_time("2025-07-27")
def test_add_missing_subscriptions_wrong_currency(
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    mock_send_exception,
    adobe_customer_factory,
    adobe_subscription_factory,
    mock_get_product_items_by_skus,
    mock_create_agreement_subscription,
    mock_notify_processing_lost_customer,
):
    customer_subscriptions = [
        adobe_subscription_factory(
            subscription_id=f"subscriptionId{i}", currency_code="GBP", renewal_date="2026-07-27"
        )
        for i in range(3)
    ]

    _add_missing_subscriptions(
        mock_mpt_client,
        mock_adobe_client,
        adobe_customer_factory(),
        agreement_factory(),
        subscriptions_for_update=("subscriptionId1", "subscriptionId0"),
        customer_subscriptions=customer_subscriptions,
    )

    mock_get_product_items_by_skus.assert_called_once_with(
        mock_mpt_client, "PRD-1111-1111", ["65304578CA", "65304578CA", "65304578CA"]
    )
    mock_adobe_client.update_subscription.assert_called_once_with(
        "AUT-1234-5678", "a-client-id", "subscriptionId2", auto_renewal=False
    )
    mock_send_exception.assert_called_once_with(
        title="Price currency mismatch detected!",
        text="{'subscriptionId': 'subscriptionId2', 'offerId': '65304578CA01A12', "
        "'currentQuantity': 10, 'currencyCode': 'GBP', 'autoRenewal': "
        "{'enabled': True, 'renewalQuantity': 10}, 'creationDate': "
        "'2019-05-20T22:49:55Z', 'renewalDate': '2026-07-27', 'status': "
        "'1000', 'deploymentId': ''}",
    )
    mock_create_agreement_subscription.assert_not_called()


def test_process_orphaned_deployment_subscriptions(
    agreement_factory, adobe_subscription_factory, mock_adobe_client
):
    _process_orphaned_deployment_subscriptions(
        mock_adobe_client,
        "authorization_id",
        "customer_id",
        [agreement_factory()],
        [
            adobe_subscription_factory(subscription_id="a-sub-id", deployment_id="deployment_id"),
            adobe_subscription_factory(subscription_id="b-sub-id", deployment_id=""),
        ],
    )

    mock_adobe_client.update_subscription.assert_called_once_with(
        "authorization_id", "customer_id", "a-sub-id", auto_renewal=False
    )


def test_process_orphaned_deployment_subscriptions_none(
    agreement_factory, adobe_subscription_factory, mock_adobe_client
):
    agreement = agreement_factory()

    _process_orphaned_deployment_subscriptions(
        mock_adobe_client,
        "authorization_id",
        "customer_id",
        [agreement],
        [
            adobe_subscription_factory(
                subscription_id=get_fulfillment_parameter(
                    agreement["subscriptions"][0], Param.ADOBE_SKU
                )["value"],
                deployment_id="deployment_id",
            )
        ],
    )

    mock_adobe_client.update_subscription.assert_not_called()


def test_process_orphaned_deployment_subscriptions_error(
    agreement_factory,
    adobe_subscription_factory,
    mock_adobe_client,
    mock_send_exception,
):
    mock_adobe_client.update_subscription.side_effect = Exception("Boom!")

    _process_orphaned_deployment_subscriptions(
        mock_adobe_client,
        "authorization_id",
        "customer_id",
        [agreement_factory()],
        [
            adobe_subscription_factory(subscription_id="a-sub-id", deployment_id="deployment_id"),
            adobe_subscription_factory(subscription_id="b-sub-id", deployment_id=""),
        ],
    )

    mock_send_exception.assert_called_once_with(
        "Error disabling auto-renewal for orphaned Adobe subscription a-sub-id.", "Boom!"
    )


def test_sync_agreement_without_subscriptions(
    mock_mpt_client,
    mock_adobe_client,
    agreement_factory,
    subscriptions_factory,
    lines_factory,
    adobe_subscription_factory,
    adobe_customer_factory,
    caplog,
):
    agreement = agreement_factory(
        lines=lines_factory(
            external_vendor_id="77777777CA",
            unit_purchase_price=10.11,
        )
    )
    adobe_subscription = adobe_subscription_factory()

    mock_adobe_client.get_subscription.return_value = adobe_subscription
    mock_adobe_client.get_subscriptions.return_value = {"items": []}
    mock_adobe_client.get_customer.return_value = adobe_customer_factory(coterm_date="2025-04-04")

    with caplog.at_level(logging.INFO):
        sync_agreement(mock_mpt_client, agreement, dry_run=True, sync_prices=True)

    assert "Skipping price sync - no subscriptions found for the customer" in caplog.text
