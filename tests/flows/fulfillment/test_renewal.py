import datetime as dt

import pytest
from freezegun import freeze_time

from adobe_vipm.adobe.constants import (
    ORDER_TYPE_PREVIEW_RENEWAL,
    AdobeErrorCode,
    AdobeSubscriptionStatus,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import TEMPLATE_NAME_CHANGE, Param
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.renewal import (
    CreateNetNewMptSubscriptions,
    CreateNetNewSubscriptions,
    PreviewRenewal,
    RecordDiscountRedemptions,
    RecordFlexDiscounts,
    SetupRenewalPlan,
    UpdateRenewalSubscriptions,
    fulfill_renewal_order,
)
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    SetOrUpdateCotermDate,
    SetSubscriptionTemplate,
    SetupDueDate,
    StartOrderProcessing,
    SyncAgreement,
    UpdateAgreementParamsVisibility,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.utils import get_fulfillment_parameter

pytestmark = pytest.mark.usefixtures("mock_adobe_config")


@pytest.fixture
def renewal_order(order_factory, order_parameters_factory, lines_factory, renewal_payload):
    lines = (
        lines_factory(line_id=1, item_id=1, external_vendor_id="65304578CA", quantity=15)
        + lines_factory(line_id=2, item_id=2, external_vendor_id="77777777CA", quantity=10)
        + lines_factory(line_id=3, item_id=3, external_vendor_id="65322651CA", quantity=5)
    )
    return order_factory(
        order_type="Change",
        order_parameters=order_parameters_factory(renewal_payload=renewal_payload),
        lines=lines,
    )


@pytest.fixture
def renewal_context(renewal_order, renewal_payload):
    return Context(
        order=renewal_order,
        order_id=renewal_order["id"],
        product_id="PRD-1111-1111",
        authorization_id="authorization-id",
        adobe_customer_id="customer-id",
        renewal_payload=renewal_payload,
    )


def plan_entry(
    *,
    subscription_id="renewing-sub-id",
    offer_id="65304578CA01A12",
    renew=True,
    renewal_quantity=15,
    flex_discount_codes=None,
    snapshot_enabled=True,
    snapshot_quantity=10,
    snapshot_codes=None,
):
    return {
        "subscription_id": subscription_id,
        "offer_id": offer_id,
        "renew": renew,
        "renewal_quantity": renewal_quantity,
        "flex_discount_codes": flex_discount_codes or [],
        "snapshot": {
            "enabled": snapshot_enabled,
            "renewal_quantity": snapshot_quantity,
            "flex_discount_codes": snapshot_codes or [],
        },
    }


def test_setup_renewal_plan_step(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context, adobe_subscription_factory
):
    renewing_sub = adobe_subscription_factory(
        subscription_id="renewing-sub-id",
        offer_id="65304578CA01A12",
        renewal_quantity=10,
    )
    # Already committed in a previous renewal order: renewedQuantity is populated.
    lapsing_sub = {
        **adobe_subscription_factory(
            subscription_id="lapsing-sub-id",
            offer_id="77777777CA01A12",
            renewal_quantity=10,
        ),
        "renewedQuantity": 8,
    }
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [renewing_sub, lapsing_sub],
        "totalCount": 2,
    }
    renewal_context.renewal_payload = None
    mocked_next_step = mocker.MagicMock()
    step = SetupRenewalPlan()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    assert renewal_context.renewal_payload is not None
    assert renewal_context.adobe_customer_subscriptions == [renewing_sub, lapsing_sub]
    assert renewal_context.renewal_plan_subscriptions == [
        {
            "subscription_id": "renewing-sub-id",
            "offer_id": "65304578CA01A12",
            "renew": True,
            "renewal_quantity": 15,
            "flex_discount_codes": ["CODE-1"],
            "snapshot": {
                "enabled": True,
                "renewal_quantity": 10,
                "flex_discount_codes": [],
                "renewed_quantity": None,
            },
        },
        {
            "subscription_id": "lapsing-sub-id",
            "offer_id": "77777777CA01A12",
            "renew": False,
            "renewal_quantity": 0,
            "flex_discount_codes": [],
            "snapshot": {
                "enabled": True,
                "renewal_quantity": 10,
                "flex_discount_codes": [],
                "renewed_quantity": 8,
            },
        },
    ]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_setup_renewal_plan_step_subscription_not_found(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context, adobe_subscription_factory
):
    mock_adobe_client.get_subscriptions.return_value = {
        "items": [
            adobe_subscription_factory(
                subscription_id="renewing-sub-id",
                offer_id="65304578CA01A12",
            )
        ],
        "totalCount": 1,
    }
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.shared.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = SetupRenewalPlan()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "lapsing-sub-id" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_preview_renewal_step(mocker, mock_adobe_client, mock_mpt_client, renewal_context):
    renewal_context.renewal_plan_subscriptions = [
        plan_entry(flex_discount_codes=["CODE-1"]),
        plan_entry(
            subscription_id="lapsing-sub-id",
            offer_id="77777777CA01A12",
            renew=False,
            renewal_quantity=0,
        ),
    ]
    preview = {"orderId": "", "orderType": ORDER_TYPE_PREVIEW_RENEWAL}
    mock_adobe_client.create_renewal_order.return_value = preview
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewal()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mock_adobe_client.create_renewal_order.assert_called_once_with(
        renewal_context.authorization_id,
        renewal_context.adobe_customer_id,
        renewal_context.order_id,
        [
            {
                "extLineItemNumber": 1,
                "offerId": "65304578CA01A12",
                "subscriptionId": "renewing-sub-id",
                "quantity": 15,
                "flexDiscountCodes": ["CODE-1"],
            },
        ],
        order_type=ORDER_TYPE_PREVIEW_RENEWAL,
        recommendation_tracker_id=renewal_context.renewal_payload["recommendationTrackerId"],
    )
    assert renewal_context.preview_renewal_order == preview
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_preview_renewal_step_no_renewing_subscriptions(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context
):
    renewal_context.renewal_plan_subscriptions = [
        plan_entry(
            subscription_id="lapsing-sub-id",
            offer_id="77777777CA01A12",
            renew=False,
            renewal_quantity=0,
        ),
    ]
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewal()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mock_adobe_client.create_renewal_order.assert_not_called()
    assert renewal_context.preview_renewal_order is None
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_preview_renewal_step_adobe_error(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context, adobe_api_error_factory
):
    renewal_context.renewal_plan_subscriptions = [plan_entry()]
    mock_adobe_client.create_renewal_order.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.INVALID_FIELDS.value,
            message="Invalid discount code",
        ),
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = PreviewRenewal()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mocked_switch_to_failed.assert_called_once()
    assert "Invalid discount code" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_create_net_new_subscriptions_step(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context, adobe_subscription_factory
):
    created_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id",
        offer_id="65322651CA01A12",
        current_quantity=0,
        renewal_quantity=5,
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    mock_adobe_client.create_customer_subscription.return_value = created_sub
    mocked_next_step = mocker.MagicMock()
    step = CreateNetNewSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mock_adobe_client.create_customer_subscription.assert_called_once_with(
        renewal_context.authorization_id,
        renewal_context.adobe_customer_id,
        "65322651CA01A12",
        5,
        deployment_id="",
        recommendation_tracker_id="8fe13fb6-72a1-451b-901b-d92da956282d",
    )
    assert renewal_context.renewal_net_new_subscriptions == {"65322651CA01A12": created_sub}
    assert renewal_context.renewal_created_net_new_subscriptions == {"65322651CA01A12": created_sub}
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_create_net_new_subscriptions_step_reuses_scheduled_subscription(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context, adobe_subscription_factory
):
    scheduled_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id",
        offer_id="65322651CA01A12",
        current_quantity=0,
        renewal_quantity=5,
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    renewal_context.adobe_customer_subscriptions = [scheduled_sub]
    mocked_next_step = mocker.MagicMock()
    step = CreateNetNewSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mock_adobe_client.create_customer_subscription.assert_not_called()
    mock_adobe_client.update_subscription.assert_not_called()
    assert renewal_context.renewal_net_new_subscriptions == {"65322651CA01A12": scheduled_sub}
    assert renewal_context.renewal_created_net_new_subscriptions == {}
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_create_net_new_subscriptions_step_restores_neutralized_scheduled_subscription(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context, adobe_subscription_factory
):
    neutralized_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id",
        offer_id="65322651CA01A12",
        current_quantity=0,
        renewal_quantity=0,
        autorenewal_enabled=False,
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    restored_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id",
        offer_id="65322651CA01A12",
        current_quantity=0,
        renewal_quantity=5,
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    renewal_context.adobe_customer_subscriptions = [neutralized_sub]
    mock_adobe_client.update_subscription.return_value = restored_sub
    mocked_next_step = mocker.MagicMock()
    step = CreateNetNewSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mock_adobe_client.create_customer_subscription.assert_not_called()
    mock_adobe_client.update_subscription.assert_called_once_with(
        renewal_context.authorization_id,
        renewal_context.adobe_customer_id,
        "net-new-sub-id",
        auto_renewal=True,
        quantity=5,
    )
    assert renewal_context.renewal_net_new_subscriptions == {"65322651CA01A12": restored_sub}
    assert renewal_context.renewal_created_net_new_subscriptions == {
        "65322651CA01A12": restored_sub
    }
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_create_net_new_subscriptions_step_restore_adobe_error(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_context,
    adobe_subscription_factory,
    adobe_api_error_factory,
):
    neutralized_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id",
        offer_id="65322651CA01A12",
        current_quantity=0,
        renewal_quantity=0,
        autorenewal_enabled=False,
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    renewal_context.adobe_customer_subscriptions = [neutralized_sub]
    mock_adobe_client.update_subscription.side_effect = AdobeAPIError(
        400,
        adobe_api_error_factory(
            code=AdobeErrorCode.INVALID_FIELDS.value,
            message="Ineligible product or orderType",
        ),
    )
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = CreateNetNewSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mock_adobe_client.create_customer_subscription.assert_not_called()
    mocked_switch_to_failed.assert_called_once()
    assert "65322651CA01A12" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    assert renewal_context.renewal_net_new_subscriptions == {}
    mocked_next_step.assert_not_called()


def test_create_net_new_subscriptions_step_no_net_new_items(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context
):
    renewal_context.renewal_payload = {**renewal_context.renewal_payload, "netNewItems": []}
    mocked_next_step = mocker.MagicMock()
    step = CreateNetNewSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mock_adobe_client.create_customer_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_create_net_new_subscriptions_step_adobe_error(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_context,
    adobe_subscription_factory,
    adobe_api_error_factory,
):
    renewal_context.renewal_payload = {
        **renewal_context.renewal_payload,
        "netNewItems": [
            {"offerId": "65322651CA01A12", "quantity": 5},
            {"offerId": "88888888CA01A12", "quantity": 3},
        ],
    }
    created_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id",
        offer_id="65322651CA01A12",
        current_quantity=0,
        renewal_quantity=5,
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    mock_adobe_client.create_customer_subscription.side_effect = [
        created_sub,
        AdobeAPIError(
            400,
            adobe_api_error_factory(
                code=AdobeErrorCode.INVALID_FIELDS.value,
                message="Ineligible product or orderType",
            ),
        ),
    ]
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = CreateNetNewSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mock_adobe_client.update_subscription.assert_called_once_with(
        renewal_context.authorization_id,
        renewal_context.adobe_customer_id,
        "net-new-sub-id",
        auto_renewal=False,
    )
    mocked_switch_to_failed.assert_called_once()
    assert "88888888CA01A12" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_update_renewal_subscriptions_step_additive_before_subtractive(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context
):
    renewal_context.renewal_plan_subscriptions = [
        plan_entry(
            subscription_id="decrease-sub-id",
            renewal_quantity=3,
            snapshot_quantity=10,
        ),
        plan_entry(
            subscription_id="disable-sub-id",
            renew=False,
            renewal_quantity=0,
            snapshot_enabled=True,
        ),
        plan_entry(
            subscription_id="enable-sub-id",
            renewal_quantity=5,
            snapshot_enabled=False,
        ),
        plan_entry(
            subscription_id="increase-sub-id",
            renewal_quantity=20,
            snapshot_quantity=10,
            flex_discount_codes=["CODE-1"],
        ),
    ]
    mocked_next_step = mocker.MagicMock()
    step = UpdateRenewalSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    assert mock_adobe_client.update_subscription.mock_calls == [
        mocker.call(
            renewal_context.authorization_id,
            renewal_context.adobe_customer_id,
            "enable-sub-id",
            auto_renewal=True,
            quantity=5,
            flex_discount_codes=None,
        ),
        mocker.call(
            renewal_context.authorization_id,
            renewal_context.adobe_customer_id,
            "increase-sub-id",
            auto_renewal=True,
            quantity=20,
            flex_discount_codes=["CODE-1"],
        ),
        mocker.call(
            renewal_context.authorization_id,
            renewal_context.adobe_customer_id,
            "decrease-sub-id",
            auto_renewal=True,
            quantity=3,
            flex_discount_codes=None,
        ),
        mocker.call(
            renewal_context.authorization_id,
            renewal_context.adobe_customer_id,
            "disable-sub-id",
            auto_renewal=False,
            quantity=None,
            flex_discount_codes=None,
        ),
    ]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_update_renewal_subscriptions_step_skips_operations_already_in_place(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context
):
    renewal_context.renewal_plan_subscriptions = [
        plan_entry(renewal_quantity=10, snapshot_quantity=10),
        plan_entry(
            subscription_id="lapsed-sub-id",
            renew=False,
            renewal_quantity=0,
            snapshot_enabled=False,
        ),
    ]
    mocked_next_step = mocker.MagicMock()
    step = UpdateRenewalSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mock_adobe_client.update_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_update_renewal_subscriptions_step_reverses_applied_operations_on_failure(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_context,
    adobe_subscription_factory,
    adobe_api_error_factory,
):
    renewal_context.renewal_plan_subscriptions = [
        plan_entry(
            subscription_id="enable-sub-id",
            renewal_quantity=5,
            snapshot_enabled=False,
            snapshot_quantity=2,
        ),
        plan_entry(
            subscription_id="increase-sub-id",
            renewal_quantity=20,
            snapshot_quantity=10,
        ),
    ]
    created_net_new_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id",
        offer_id="65322651CA01A12",
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    reused_net_new_sub = adobe_subscription_factory(
        subscription_id="reused-net-new-sub-id",
        offer_id="88888888CA01A12",
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    renewal_context.renewal_net_new_subscriptions = {
        "65322651CA01A12": created_net_new_sub,
        "88888888CA01A12": reused_net_new_sub,
    }
    renewal_context.renewal_created_net_new_subscriptions = {
        "65322651CA01A12": created_net_new_sub,
    }
    mock_adobe_client.update_subscription.side_effect = [
        {"subscriptionId": "enable-sub-id"},
        AdobeAPIError(
            400,
            adobe_api_error_factory(
                code=AdobeErrorCode.INVALID_RENEWAL_STATE.value,
                message="Invalid renewal state",
            ),
        ),
        {"subscriptionId": "enable-sub-id"},
        {"subscriptionId": "net-new-sub-id"},
    ]
    mocked_switch_to_failed = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.switch_order_to_failed"
    )
    mocked_next_step = mocker.MagicMock()
    step = UpdateRenewalSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    assert mock_adobe_client.update_subscription.mock_calls[2:] == [
        mocker.call(
            renewal_context.authorization_id,
            renewal_context.adobe_customer_id,
            "enable-sub-id",
            auto_renewal=False,
            quantity=2,
            flex_discount_codes=[],
        ),
        mocker.call(
            renewal_context.authorization_id,
            renewal_context.adobe_customer_id,
            "net-new-sub-id",
            auto_renewal=False,
        ),
    ]
    # The reused scheduled subscription was not created by this run: its
    # auto-renewal is preserved during the reversal.
    assert not any(
        call.args[2] == "reused-net-new-sub-id"
        for call in mock_adobe_client.update_subscription.mock_calls
    )
    mocked_switch_to_failed.assert_called_once()
    assert "Invalid renewal state" in mocked_switch_to_failed.mock_calls[0].args[2]["message"]
    mocked_next_step.assert_not_called()


def test_create_net_new_mpt_subscriptions_step(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context, adobe_subscription_factory
):
    adobe_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id",
        offer_id="65322651CA01A12",
        current_quantity=0,
        renewal_quantity=5,
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    renewal_context.renewal_net_new_subscriptions = {"65322651CA01A12": adobe_sub}
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.create_subscription",
        return_value={"id": "SUB-1000-2000-3000"},
    )
    mocked_next_step = mocker.MagicMock()
    step = CreateNetNewMptSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mocked_create_subscription.assert_called_once()
    subscription_data = mocked_create_subscription.mock_calls[0].args[2]
    assert subscription_data["externalIds"] == {"vendor": "net-new-sub-id"}
    assert subscription_data["startDate"] == adobe_sub["renewalDate"]
    assert subscription_data["commitmentDate"] == adobe_sub["renewalDate"]
    assert subscription_data["autoRenew"] is True
    assert subscription_data["lines"] == [{"id": renewal_context.order["lines"][2]["id"]}]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_create_net_new_mpt_subscriptions_step_skips_existing_subscription(
    mocker,
    mock_adobe_client,
    mock_mpt_client,
    renewal_context,
    adobe_subscription_factory,
):
    adobe_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id",
        offer_id="65322651CA01A12",
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    renewal_context.renewal_net_new_subscriptions = {"65322651CA01A12": adobe_sub}
    net_new_line = renewal_context.order["lines"][2]
    renewal_context.order["subscriptions"] = [
        {
            "id": "SUB-1000-2000-3000",
            "lines": [{"id": net_new_line["id"], "item": {"id": net_new_line["item"]["id"]}}],
        },
    ]
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.create_subscription"
    )
    mocked_next_step = mocker.MagicMock()
    step = CreateNetNewMptSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mocked_create_subscription.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_create_net_new_mpt_subscriptions_step_missing_renewal_values(
    mocker, mock_adobe_client, mock_mpt_client, renewal_context, adobe_subscription_factory
):
    adobe_sub = adobe_subscription_factory(
        subscription_id="net-new-sub-id",
        offer_id="65322651CA01A12",
        status=AdobeSubscriptionStatus.SCHEDULED.value,
    )
    adobe_sub.pop("renewalDate")
    adobe_sub["autoRenewal"].pop(Param.RENEWAL_QUANTITY.value)
    renewal_context.renewal_net_new_subscriptions = {"65322651CA01A12": adobe_sub}
    mocked_create_subscription = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.create_subscription",
        return_value={"id": "SUB-1000-2000-3000"},
    )
    mocked_next_step = mocker.MagicMock()
    step = CreateNetNewMptSubscriptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    subscription_data = mocked_create_subscription.mock_calls[0].args[2]
    parameters = {
        param["externalId"]: param["value"]
        for param in subscription_data["parameters"]["fulfillment"]
    }
    assert not parameters[Param.RENEWAL_QUANTITY.value]
    assert not parameters[Param.RENEWAL_DATE.value]
    assert subscription_data["startDate"] == adobe_sub["creationDate"]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_record_flex_discounts_step(mocker, mock_mpt_client, renewal_context):
    renewal_context.renewal_plan_subscriptions = [
        plan_entry(flex_discount_codes=["CODE-1"]),
        plan_entry(
            subscription_id="lapsing-sub-id",
            offer_id="77777777CA01A12",
            renew=False,
            renewal_quantity=0,
        ),
    ]
    mocked_next_step = mocker.MagicMock()
    step = RecordFlexDiscounts()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    flex_param = get_fulfillment_parameter(renewal_context.order, Param.FLEXIBLE_DISCOUNTS.value)
    assert flex_param["value"] == [
        {
            "offerId": "65304578CA01A12",
            "subscriptionId": "renewing-sub-id",
            "flexDiscountCode": ["CODE-1"],
        },
    ]
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_record_flex_discounts_step_without_codes(mocker, mock_mpt_client, renewal_context):
    renewal_context.renewal_plan_subscriptions = [plan_entry()]
    mocked_next_step = mocker.MagicMock()
    step = RecordFlexDiscounts()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    flex_param = get_fulfillment_parameter(renewal_context.order, Param.FLEXIBLE_DISCOUNTS.value)
    assert not flex_param.get("value")
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


@freeze_time("2026-08-12 10:00:00")
def test_record_discount_redemptions_step(mocker, mock_mpt_client, renewal_context):
    renewal_context.renewal_plan_subscriptions = [
        plan_entry(flex_discount_codes=["CODE-1", "CODE-2"]),
        plan_entry(
            subscription_id="another-renewing-sub-id",
            offer_id="65322651CA01A12",
            flex_discount_codes=["CODE-2"],
        ),
        plan_entry(
            subscription_id="lapsing-sub-id",
            offer_id="77777777CA01A12",
            renew=False,
            renewal_quantity=0,
            flex_discount_codes=["CODE-3"],
        ),
    ]
    mocked_create_redemptions = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.create_discount_redemptions",
    )
    mocked_next_step = mocker.MagicMock()
    step = RecordDiscountRedemptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    redeemed_at = dt.datetime(2026, 8, 12, 10, 0, tzinfo=dt.UTC)
    mocked_create_redemptions.assert_called_once_with([
        {
            "code": "CODE-1",
            "customer_id": "customer-id",
            "order_id": renewal_context.order_id,
            "redeemed_at": redeemed_at,
        },
        {
            "code": "CODE-2",
            "customer_id": "customer-id",
            "order_id": renewal_context.order_id,
            "redeemed_at": redeemed_at,
        },
    ])
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_record_discount_redemptions_step_without_codes(mocker, mock_mpt_client, renewal_context):
    renewal_context.renewal_plan_subscriptions = [plan_entry()]
    mocked_create_redemptions = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.create_discount_redemptions",
    )
    mocked_next_step = mocker.MagicMock()
    step = RecordDiscountRedemptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mocked_create_redemptions.assert_not_called()
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_record_discount_redemptions_step_airtable_error(mocker, mock_mpt_client, renewal_context):
    renewal_context.renewal_plan_subscriptions = [plan_entry(flex_discount_codes=["CODE-1"])]
    mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.create_discount_redemptions",
        side_effect=Exception("airtable is down"),
    )
    mocked_send_exception = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.send_exception",
    )
    mocked_next_step = mocker.MagicMock()
    step = RecordDiscountRedemptions()

    step(mock_mpt_client, renewal_context, mocked_next_step)  # act

    mocked_send_exception.assert_called_once()
    notification_text = mocked_send_exception.mock_calls[0].args[1]
    assert "customer-id" in notification_text
    assert renewal_context.order_id in notification_text
    assert "CODE-1" in notification_text
    mocked_next_step.assert_called_once_with(mock_mpt_client, renewal_context)


def test_fulfill_renewal_order(mocker):
    mocked_pipeline_instance = mocker.MagicMock()
    mocked_pipeline_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.Pipeline",
        return_value=mocked_pipeline_instance,
    )
    mocked_context = mocker.MagicMock()
    mocked_context_ctor = mocker.patch(
        "adobe_vipm.flows.fulfillment.renewal.Context", return_value=mocked_context
    )
    mocked_client = mocker.MagicMock()
    mocked_order = mocker.MagicMock()

    fulfill_renewal_order(mocked_client, mocked_order)  # act

    expected_steps = [
        SetupContext,
        StartOrderProcessing,
        SetupDueDate,
        ValidateDuplicateLines,
        SetOrUpdateCotermDate,
        UpdateAgreementParamsVisibility,
        ValidateRenewalWindow,
        SetupRenewalPlan,
        CreateNetNewSubscriptions,
        UpdateRenewalSubscriptions,
        CreateNetNewMptSubscriptions,
        RecordFlexDiscounts,
        CompleteOrder,
        RecordDiscountRedemptions,
        SetSubscriptionTemplate,
        SyncAgreement,
    ]
    pipeline_args = mocked_pipeline_ctor.mock_calls[0].args
    assert len(pipeline_args) == len(expected_steps)
    actual_steps = [type(step) for step in pipeline_args]
    assert actual_steps == expected_steps
    assert pipeline_args[1].template_name == TEMPLATE_NAME_CHANGE
    assert pipeline_args[12].template_name == TEMPLATE_NAME_CHANGE
    mocked_context_ctor.assert_called_once_with(order=mocked_order)
    mocked_pipeline_instance.run.assert_called_once_with(mocked_client, mocked_context)
