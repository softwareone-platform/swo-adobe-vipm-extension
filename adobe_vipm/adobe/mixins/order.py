import datetime as dt
import json
import logging
import re
from collections import defaultdict
from hashlib import sha256
from operator import itemgetter
from typing import Any
from urllib.parse import urljoin

from adobe_vipm.adobe import constants as adobe_constants
from adobe_vipm.adobe.dataclasses import Authorization, FlexDiscountCascade, ReturnableOrderInfo
from adobe_vipm.adobe.errors import AdobeError, wrap_http_error
from adobe_vipm.adobe.mixins.errors import AdobeCreatePreviewError, ProcessingUpsizeLinesError
from adobe_vipm.adobe.utils import (  # noqa: WPS347
    find_first,
    get_item_by_subcription_id,
    is_flex_discount_applied,
    to_adobe_line_id,
)
from adobe_vipm.airtable.models import get_adobe_product_by_marketplace_sku
from adobe_vipm.flows.constants import FAKE_CUSTOMERS_IDS, Param
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.utils.deployment import get_deployment_id
from adobe_vipm.notifications import send_exception
from adobe_vipm.utils import get_partial_sku, map_by

logger = logging.getLogger(__name__)


def _get_rejected_codes(response_json: dict) -> dict[int, set[str]]:
    """Return, per line number, the codes the preview response did not apply successfully."""
    rejected = {}
    for line_item in response_json["lineItems"]:
        codes = {
            fd["code"]
            for fd in line_item.get("flexDiscounts", [])
            if not is_flex_discount_applied(fd)
        }
        if codes:
            rejected[line_item["extLineItemNumber"]] = codes
    return rejected


def _get_line_code(payload: dict, line_number: int) -> str | None:
    """Return the flex discount code the payload proposes for the line, if any."""
    line_item = _get_payload_line(payload, line_number)
    codes = (line_item or {}).get("flexDiscountCodes") or []
    return codes[0] if codes else None


def _set_line_code(payload: dict, line_number: int, code: str | None) -> None:
    """Replace the flex discount code the payload proposes for the line (None removes it)."""
    line_item = _get_payload_line(payload, line_number)
    if code:
        line_item["flexDiscountCodes"] = [code]
    else:
        line_item.pop("flexDiscountCodes", None)


def _get_payload_line(payload: dict, line_number: int) -> dict | None:
    return find_first(
        lambda line_item: line_item["extLineItemNumber"] == line_number,
        payload["lineItems"],
    )


def _get_proposed_code(codes_by_line: dict, line: dict) -> str | None:
    """Return the best-ranked candidate code of an MPT line, None without candidates."""
    codes = codes_by_line.get(line["id"]) or []
    return codes[0] if codes else None


def _get_max_previews(payload: dict, cascade: FlexDiscountCascade) -> int:
    """
    Bound the preview cascade: one call plus one per code that can still be rejected.

    Codes the payload carries outside the cascade (not ranked candidates) count
    once each: their rejection drops the line to undiscounted in one step.
    """
    untracked = sum(
        1
        for line_item in payload["lineItems"]
        if line_item.get("flexDiscountCodes")
        and line_item["extLineItemNumber"] not in cascade.candidates
    )
    return 1 + cascade.remaining_codes + untracked


class OrderClientMixin:
    """Adobe Client Mixin to manage Orders flows of Adobe VIPM."""

    flex_discount_not_qualify_re = re.compile(r"Line Item: ?(\d+)", re.IGNORECASE)

    @wrap_http_error
    def get_orders(self, authorization_id: str, customer_id: str, filters: dict | None = None):
        """
        Retrieve Adobe orders.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            filters: key-value dictionary to filter orders.

        Returns:
            dict: The Preview order.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        orders = []
        orders_base_url = f"/v3/customers/{customer_id}/orders"
        next_url = f"{orders_base_url}?limit=100&offset=0"
        while next_url:
            response = self._session.get(
                urljoin(self._config.api_base_url, next_url),
                headers=headers,
                params=filters,
                timeout=self._TIMEOUT,
            )
            response.raise_for_status()
            page = response.json()
            orders.extend(page["items"])
            next_url = page["links"].get("next", {}).get("uri")
        return orders

    @wrap_http_error
    def get_order(
        self,
        authorization_id: str,
        customer_id: str,
        order_id: str,
    ) -> dict:
        """
        Retrieve order by ID.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            order_id: MPT Order id to refer to.

        Returns:
            dict: Adobe order.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = self._session.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/orders/{order_id}",
            ),
            headers=headers,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_new_order(
        self,
        authorization_id: str,
        customer_id: str,
        adobe_preview_order: dict,
        deployment_id: str | None = None,
        requested_codes: dict[int, str] | None = None,
    ) -> dict:
        """
        Create Adobe Order based on Preview order.

        Only the flex discount code the order requested on a line, and the
        preview confirmed, is committed (see _build_line_item).

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            adobe_preview_order: Adobe Preview order.
            deployment_id: Adobe Deployment ID.
            requested_codes: Flex discount code requested per Adobe line number
                (context.flex_discount_selection); None or empty commits no code.

        Returns:
            dict: Adobe order.
        """
        authorization = self._config.get_authorization(authorization_id)
        line_items = [
            self._build_line_item(line_item, requested_codes or {})
            for line_item in adobe_preview_order["lineItems"]
        ]

        payload = {
            "externalReferenceId": adobe_preview_order["externalReferenceId"],
            "orderType": adobe_constants.ORDER_TYPE_NEW,
            "lineItems": line_items,
        }
        if not deployment_id:
            payload["currencyCode"] = authorization.currency

        correlation_id = sha256(json.dumps(payload).encode()).hexdigest()
        headers = self._get_headers(
            authorization,
            correlation_id=correlation_id,
        )
        response = self._session.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_preview_order(self, context: Context) -> dict | None:
        """
        Create Preview orders.

        Each new/upsize line proposes the best-ranked flexible discount code
        the SelectFlexDiscounts step left on context.flex_discount_candidates;
        a code Adobe rejects is replaced by the line's next candidate (see
        get_preview_order). The codes finally accepted per Adobe line number
        land on context.flex_discount_selection and the rejected ones on
        context.flex_discount_rejections.

        Args:
            context: Order context.

        Returns:
            dict: The Preview order.

        Raises:
            AdobeCreatePreviewError
        """
        authorization = self._config.get_authorization(context.authorization_id)
        codes_by_line = {
            line_id: [candidate.code for candidate in candidates]
            for line_id, candidates in context.flex_discount_candidates.items()
            if candidates
        }
        if codes_by_line:
            logger.info("Flex discounts: ranked candidates per line: %s", codes_by_line)
        payload = {
            "externalReferenceId": context.order_id,
            "orderType": adobe_constants.ORDER_TYPE_PREVIEW,
            "lineItems": [],
        }
        deployment_id = get_deployment_id(context.order)
        self._process_new_lines(context, codes_by_line, payload)
        if context.upsize_lines:
            try:
                self._process_upsize_lines(
                    context.authorization_id,
                    context.adobe_customer_id,
                    context.upsize_lines,
                    codes_by_line,
                    payload,
                    context.market_segment,
                    deployment_id,
                )
            except ProcessingUpsizeLinesError as error:
                raise AdobeCreatePreviewError(error) from error

        self._update_payload_by_deployment(authorization, deployment_id, payload)
        if not payload["lineItems"]:
            self._logger.info(
                "Preview Order for %s was not created: line items are empty.",
                context.order_id,
            )
            return None

        customer_id = context.adobe_customer_id or FAKE_CUSTOMERS_IDS[context.market_segment]
        cascade = FlexDiscountCascade(
            candidates={
                to_adobe_line_id(line_id): list(codes) for line_id, codes in codes_by_line.items()
            }
        )
        preview_order = self.get_preview_order(authorization, customer_id, payload, cascade)
        context.flex_discount_selection = cascade.selection
        context.flex_discount_rejections = cascade.rejections
        logger.info(
            "Created preview order %s (flex discounts selected=%s rejected=%s)",
            preview_order["externalReferenceId"],
            cascade.selection,
            cascade.rejections,
        )
        return preview_order

    @wrap_http_error
    def create_preview_renewal(
        self,
        authorization_id: str,
        customer_id: str,
    ) -> dict:
        """
        Create preview order for Renewal.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.

        Returns:
            dict: The Preview Renewal order.
        """
        authorization = self._config.get_authorization(authorization_id)
        payload = {"orderType": adobe_constants.ORDER_TYPE_PREVIEW_RENEWAL}
        headers = self._get_headers(authorization)
        response = self._session.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_renewal_order(
        self,
        authorization_id: str,
        customer_id: str,
        external_reference_id: str,
        line_items: list[dict],
        order_type: str = adobe_constants.ORDER_TYPE_RENEWAL,
        recommendation_tracker_id: str | None = None,
    ) -> dict:
        """
        Create a RENEWAL order for specific subscriptions.

        Used for manually renewing expired subscriptions (allowedActions: ["MANUAL_RENEWAL"]).

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer.
            external_reference_id: External reference ID for the order.
            line_items: List of line items with offerId, quantity, and subscriptionId.
            order_type: Type of the order.
            recommendation_tracker_id: The tracker id captured from the Adobe
            recommendations call, replayed so Adobe can attribute the outcome.

        Returns:
            dict: The Renewal order.
        """
        authorization = self._config.get_authorization(authorization_id)
        payload = {
            "externalReferenceId": external_reference_id,
            "orderType": order_type,
            "lineItems": line_items,
        }
        if not any(line_item.get("deploymentId") for line_item in line_items):
            payload["currencyCode"] = authorization.currency

        correlation_id = sha256(json.dumps(payload).encode()).hexdigest()
        headers = self._get_headers(
            authorization,
            correlation_id=correlation_id,
            recommendation_tracker_id=recommendation_tracker_id,
        )
        response = self._session.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_switch_preview_order(
        self,
        authorization_id: str,
        customer_id: str,
        external_reference_id: str,
        switch_payload: dict,
    ) -> dict:
        """
        Create a PREVIEW_SWITCH order for a mid-term upgrade.

        Used to validate that a SWITCH order can be processed and to retrieve
        its pricing before placing the actual order.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that places the SWITCH order.
            external_reference_id: External reference ID for the order.
            switch_payload: Switch payload containing the lineItems to purchase
            and the cancellingItems of the subscriptions to switch from.

        Returns:
            dict: The Preview Switch order.
        """
        authorization = self._config.get_authorization(authorization_id)
        payload = self._build_switch_order_payload(
            authorization,
            external_reference_id,
            switch_payload,
            adobe_constants.ORDER_TYPE_PREVIEW_SWITCH,
        )
        headers = self._get_headers(
            authorization,
            recommendation_tracker_id=switch_payload.get("recommendationTrackerId"),
        )
        response = self._session.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            params={"fetch-price": "true"},
            headers=headers,
            json=payload,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_switch_order(
        self,
        authorization_id: str,
        customer_id: str,
        external_reference_id: str,
        switch_payload: dict,
    ) -> dict:
        """
        Create a SWITCH order for a mid-term upgrade.

        It purchases the lineItems and cancels the quantities of the
        cancellingItems subscriptions in a single Adobe order.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that places the SWITCH order.
            external_reference_id: External reference ID for the order.
            switch_payload: Switch payload containing the lineItems to purchase
            and the cancellingItems of the subscriptions to switch from.

        Returns:
            dict: The Switch order.
        """
        authorization = self._config.get_authorization(authorization_id)
        payload = self._build_switch_order_payload(
            authorization,
            external_reference_id,
            switch_payload,
            adobe_constants.ORDER_TYPE_SWITCH,
        )
        correlation_id = sha256(json.dumps(payload).encode()).hexdigest()
        headers = self._get_headers(
            authorization,
            correlation_id=correlation_id,
            recommendation_tracker_id=switch_payload.get("recommendationTrackerId"),
        )
        response = self._session.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def get_returnable_orders_by_subscription_id(
        self,
        authorization_id: str,
        customer_id: str,
        subscription_id: str,
        customer_coterm_date: str,
        return_orders: list | None = None,
    ) -> list[dict]:
        """
        Retrieve RETURN orders filter by sku.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            subscription_id: Adobe Subscription ID
            customer_coterm_date: customer coterm date
            return_orders: orders to return

        Returns:
            list(dict): The RETURN order.
        """
        current_date = dt.datetime.now(tz=dt.UTC).date()
        start_date = current_date - dt.timedelta(days=adobe_constants.CANCELLATION_WINDOW_DAYS)

        returning_order_ids = [order["referenceOrderId"] for order in (return_orders or [])]

        orders = self.get_orders(
            authorization_id,
            customer_id,
            filters={
                "order-type": [adobe_constants.ORDER_TYPE_NEW, adobe_constants.ORDER_TYPE_RENEWAL],
                "start-date": start_date.isoformat(),
                "end-date": customer_coterm_date,
            },
        )
        order_items = (
            (
                order,
                get_item_by_subcription_id(order["lineItems"], subscription_id),
            )
            for order in orders
        )

        order_items = filter(itemgetter(1), order_items)
        order_items = list(
            filter(
                lambda order_item: (
                    order_item[0]["orderId"] in returning_order_ids
                    or self._is_processed(order_item)
                ),
                order_items,
            )
        )
        renewal_order_item = find_first(
            lambda order_item: order_item[0]["orderType"] == adobe_constants.ORDER_TYPE_RENEWAL,
            order_items,
        )
        if renewal_order_item:
            renewal_order_date = dt.datetime.fromisoformat(renewal_order_item[0]["creationDate"])
            order_items = filter(
                lambda order_item: (
                    dt.datetime.fromisoformat(order_item[0]["creationDate"]) >= renewal_order_date
                ),
                order_items,
            )

        return_orders = []
        for order, line_item in order_items:
            return_orders.append(
                ReturnableOrderInfo(
                    order=order,
                    line=line_item,
                    quantity=line_item["quantity"],
                )
            )
        return return_orders

    def get_return_orders_by_external_reference(
        self,
        authorization_id: str,
        customer_id: str,
        external_reference: str,
    ) -> dict:
        """
        Retrieve RETURN orders filter by external reference.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            external_reference: External Reference ID.

        Returns:
            The RETURN orders.
        """
        orders = self.get_orders(
            authorization_id,
            customer_id,
            filters={
                "order-type": adobe_constants.ORDER_TYPE_RETURN,
                "status": [
                    adobe_constants.AdobeOrderStatus.COMPLETE,
                    adobe_constants.AdobeOrderStatus.OPEN,
                ],
            },
        )
        return_orders = defaultdict(list)
        for order in orders:
            if not order["externalReferenceId"].startswith(external_reference):
                continue
            for line_item in order["lineItems"]:
                return_orders[get_partial_sku(line_item["offerId"])].append(order)
        return return_orders

    @wrap_http_error
    def create_return_order(
        self,
        authorization_id: str,
        customer_id: str,
        returning_order: dict,
        returning_item: dict,
        external_reference: str,
        deployment_id: str | None = None,
    ) -> dict:
        """
        Creates an order of type RETURN for a given `item` that was purchased.

        In the order identified by `returning_order_id`.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            returning_order: The order that contains the item to return.
            returning_item: The item that must be returned.
            external_reference: External reference for the return order.
            deployment_id: Deployment ID if the return is for a deployment.

        Returns:
            dict: The RETURN order.
        """
        line_number = returning_item["extLineItemNumber"]
        external_id = f"{external_reference}_{returning_order['externalReferenceId']}_{line_number}"

        payload = {
            "externalReferenceId": external_id,
            "referenceOrderId": returning_order["orderId"],
            "orderType": adobe_constants.ORDER_TYPE_RETURN,
            "lineItems": [],
        }

        if not deployment_id:
            payload["currencyCode"] = self._config.get_authorization(authorization_id).currency

        line_item = {
            "extLineItemNumber": line_number,
            "offerId": returning_item["offerId"],
            "quantity": returning_item["quantity"],
        }
        if deployment_id:
            line_item["deploymentId"] = deployment_id
            line_item["currencyCode"] = self._config.get_authorization(authorization_id).currency
        payload["lineItems"].append(line_item)

        return self._create_return_order_base(authorization_id, customer_id, payload, external_id)

    @wrap_http_error
    def create_return_order_by_adobe_order(
        self,
        authorization_id: str,
        customer_id: str,
        order_created: dict,
    ) -> dict:
        """
        Creates a return order for a given Adobe order.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            order_created: The Adobe order to return.

        Returns:
            dict: The RETURN order.
        """
        external_reference_id = f"{order_created['externalReferenceId']}_{order_created['orderId']}"
        adobe_order_id = order_created["orderId"]
        adobe_line_items = order_created["lineItems"]

        payload = {
            "externalReferenceId": external_reference_id,
            "referenceOrderId": adobe_order_id,
            "orderType": adobe_constants.ORDER_TYPE_RETURN,
            "lineItems": adobe_line_items,
        }
        if not any(line_item.get("deploymentId") for line_item in adobe_line_items):
            payload["currencyCode"] = self._config.get_authorization(authorization_id).currency

        return self._create_return_order_base(authorization_id, customer_id, payload)

    def get_preview_order(
        self,
        authorization: Authorization,
        adobe_customer_id: str,
        payload: dict,
        cascade: FlexDiscountCascade | None = None,
    ) -> dict | None:
        """
        Gets a preview of an order, cascading through the flex discount candidates on rejection.

        Adobe's preview is the authority on a code: a code it rejects (result
        other than SUCCESS, or error 2141 naming the line) is replaced by the
        next-best candidate of that line and the preview is repeated; the line
        continues undiscounted once its candidates are exhausted. Rejections
        Adobe reports for codes the payload did not propose (discounts Adobe
        auto-applied itself) are ignored. The cascade is bounded by one call per
        code that can still be rejected, plus a final undiscounted preview.

        Args:
            authorization: Authorization object containing authentication credentials.
            adobe_customer_id: Unique identifier of the Adobe customer.
            payload: Dictionary containing order details required for preview.
            cascade: Ranked candidate codes per line number; updated in place with
                the selected and rejected codes.

        Returns:
            A dictionary containing the response with order details, including computed
            pricing for the codes finally accepted.

        Raises:
            AdobeError: If the cascade ceiling is hit with codes still rejected, or on
            any other Adobe error.
        """
        cascade = FlexDiscountCascade() if cascade is None else cascade
        max_previews = _get_max_previews(payload, cascade)
        response_json = None
        for _ in range(max_previews):
            response_json, retry = self._attempt_preview(
                authorization, adobe_customer_id, payload, cascade
            )
            if not retry:
                break
        else:
            msg = (
                f"After {max_previews} preview attempts Adobe still rejects flex discount "
                f"codes: {cascade.rejections}."
            )
            send_exception("Failed applying discount codes", msg)
            raise AdobeError(msg)

        cascade.selection = {
            line_item["extLineItemNumber"]: line_item["flexDiscountCodes"][0]
            for line_item in payload["lineItems"]
            if line_item.get("flexDiscountCodes")
        }
        return response_json

    def get_flex_discounts_by_code(
        self,
        authorization_id: str,
        market_segment: str,
        country: str,
        flex_discount_code: str,
    ) -> list:
        """
        Fetches the flex discounts matching a single discount code from Adobe.

        Args:
            authorization_id: Id of the authorization to use.
            market_segment: Adobe market segment (COM, GOV, EDU).
            country: Customer country code.
            flex_discount_code: The flexible discount code to look up.

        Returns:
            list: The flex discounts Adobe reports for the code.
        """
        authorization = self._config.get_authorization(authorization_id)
        return self._fetch_flex_discounts(
            authorization,
            {
                "market-segment": market_segment,
                "country": country,
                "flex-discount-code": flex_discount_code,
            },
        )

    def _attempt_preview(
        self,
        authorization: Authorization,
        adobe_customer_id: str,
        payload: dict,
        cascade: FlexDiscountCascade,
    ) -> tuple[dict | None, bool]:
        """
        Run one PREVIEW call and cascade the codes it rejected.

        Returns:
            tuple: The response (None when Adobe rejected the call) and whether the
            payload changed, i.e. the preview must be repeated.
        """
        try:
            response_json = self._get_preview_order(authorization, adobe_customer_id, payload)
        except AdobeError as ex:
            rejected = self._get_rejected_codes_for_not_qualified(ex, payload)
            if not self._cascade_rejected_codes(payload, cascade, rejected):
                raise
            return None, True
        rejected = _get_rejected_codes(response_json)
        return response_json, self._cascade_rejected_codes(payload, cascade, rejected)

    def _cascade_rejected_codes(
        self, payload: dict, cascade: FlexDiscountCascade, rejected: dict[int, set[str]]
    ) -> bool:
        """
        Replace the rejected codes of the payload by the next candidates of their lines.

        Returns:
            bool: Whether the payload changed, i.e. the preview must be repeated.
        """
        changed = False
        for line_number, codes in rejected.items():
            current_code = _get_line_code(payload, line_number)
            if current_code is None or current_code not in codes:
                logger.info(
                    "Flex discounts: Adobe reported rejected code(s) %s on line %s that the "
                    "order did not propose, ignoring them",
                    sorted(codes),
                    line_number,
                )
                continue
            next_code = cascade.reject(line_number, current_code)
            logger.warning(
                "Flex discounts: Adobe rejected code %s on line %s, %s",
                current_code,
                line_number,
                f"trying {next_code} next" if next_code else "no candidate left, line undiscounted",
            )
            _set_line_code(payload, line_number, next_code)
            changed = True
        return changed

    def _get_rejected_codes_for_not_qualified(
        self, ex: AdobeError, payload: dict
    ) -> dict[int, set[str]]:
        """Map Adobe's 2141 rejection to the code the payload proposes on the line it names."""
        error_code = getattr(ex, "code", None)
        if error_code != adobe_constants.AdobeErrorCode.CUSTOMER_NOT_QUALIFIED_FOR_FLEX_DISCOUNT:
            raise ex
        logger.warning("%s", ex)
        matched = self.flex_discount_not_qualify_re.match(ex.details[0])
        if not matched:
            raise AdobeError(
                f"Can't parse Adobe error message: '{ex.details}'. Expected format example:"
                f" 'Line Item: 2, Reason: Invalid Flexible Discount'"
            )
        line_number = int(matched.group(1))
        code = _get_line_code(payload, line_number)
        return {line_number: {code}} if code else {}

    def _process_new_lines(self, context: Context, codes_by_line: dict, payload: dict):
        for line in context.new_lines:
            line_item = self._get_preview_order_line_item(
                line,
                line["item"]["externalIds"]["vendor"],
                line["quantity"],
                _get_proposed_code(codes_by_line, line),
                context.market_segment,
            )
            payload["lineItems"].append(line_item)

    def _process_upsize_lines(
        self,
        authorization_id: str,
        adobe_customer_id: str,
        upsize_lines: list[dict],
        codes_by_line: dict,
        payload: dict,
        market_segment: str,
        deployment_id: str | None,
    ):
        offer_ids = [line_item["item"]["externalIds"]["vendor"] for line_item in upsize_lines]
        # ???: This method belongs to SubscriptionClientMixin
        upsize_subscriptions = self.get_subscriptions_for_offers(
            authorization_id, adobe_customer_id, offer_ids, deployment_id
        )
        offer_subscriptions = map_by("offerId", upsize_subscriptions)
        map_by_base_offer_subscriptions = {
            get_partial_sku(offer_id): subs for offer_id, subs in offer_subscriptions.items()
        }

        for line in upsize_lines:
            adobe_base_sku = line["item"]["externalIds"]["vendor"]
            try:
                adobe_subscription = map_by_base_offer_subscriptions[adobe_base_sku]
            except KeyError:
                raise ProcessingUpsizeLinesError(
                    "Subscription has not been found in Adobe for sku %s.", adobe_base_sku
                )

            renewal_quantity = adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
            current_quantity = adobe_subscription[Param.CURRENT_QUANTITY.value]
            diff = current_quantity - renewal_quantity if renewal_quantity < current_quantity else 0

            quantity = line["quantity"] - line["oldQuantity"] - diff
            if quantity <= 0:
                self._logger.info(
                    "Upsizing item %s(%s) is skipped. "
                    "Because overall quantity is equal or below 0. "
                    "line quantity = %s, "
                    "line old quantity = %s, "
                    "adobe renewal quantity = %s, "
                    "adobe current quantity = %s.",
                    line["id"],
                    adobe_base_sku,
                    line["quantity"],
                    line["oldQuantity"],
                    renewal_quantity,
                    current_quantity,
                )
                continue

            line_item = self._get_preview_order_line_item(
                line,
                adobe_base_sku,
                quantity,
                _get_proposed_code(codes_by_line, line),
                market_segment,
            )
            payload["lineItems"].append(line_item)

    def _build_switch_order_payload(
        self,
        authorization: Authorization,
        external_reference_id: str,
        switch_payload: dict,
        order_type: str,
    ) -> dict:
        payload = {
            **switch_payload,
            "externalReferenceId": external_reference_id,
            "orderType": order_type,
        }
        # Adobe expects the tracker id of the originating recommendation as the
        # x-recommendation-tracker-id header, not as an order body field.
        payload.pop("recommendationTrackerId", None)
        if not payload.get("currencyCode"):
            payload["currencyCode"] = authorization.currency
        return payload

    def _build_line_item(self, adobe_line_item: dict, requested_codes: dict[int, str]) -> dict:
        """
        Turn a preview line into a NEW order line, committing only the requested confirmed code.

        A code the preview reports that the order did not request (a reusable
        discount Adobe auto-applied) is not echoed back: Adobe applies it itself
        and echoing it could put two codes on the line (error 2147). A requested
        code the preview did not confirm with result SUCCESS is dropped.
        """
        line_item = {
            "extLineItemNumber": adobe_line_item["extLineItemNumber"],
            "offerId": adobe_line_item["offerId"],
            "quantity": adobe_line_item["quantity"],
        }
        committed_code = self._get_committed_code(adobe_line_item, requested_codes)
        if committed_code:
            line_item["flexDiscountCodes"] = [committed_code]
        if adobe_line_item.get("deploymentId"):
            line_item["deploymentId"] = adobe_line_item["deploymentId"]
            line_item["currencyCode"] = adobe_line_item["currencyCode"]
        return line_item

    def _get_committed_code(
        self, adobe_line_item: dict, requested_codes: dict[int, str]
    ) -> str | None:
        line_number = adobe_line_item["extLineItemNumber"]
        requested_code = requested_codes.get(line_number)
        confirmed_codes = {
            fd["code"]
            for fd in adobe_line_item.get("flexDiscounts") or []
            if is_flex_discount_applied(fd)
        }
        auto_applied = confirmed_codes - {requested_code}
        if auto_applied:
            logger.info(
                "Flex discounts: leaving discount(s) %s auto-applied by Adobe on line %s out of "
                "the order, Adobe applies them itself",
                sorted(auto_applied),
                line_number,
            )
        if requested_code is None:
            return None
        if requested_code not in confirmed_codes:
            logger.warning(
                "Flex discounts: requested code %s on line %s was not confirmed by the preview, "
                "committing the line without it",
                requested_code,
                line_number,
            )
            return None
        return requested_code

    @wrap_http_error
    def _create_return_order_base(
        self,
        authorization_id: str,
        customer_id: str,
        payload: dict,
        correlation_id: str | None = None,
    ) -> dict:
        """
        Base method to create a return order with the given payload.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            payload: The payload for the return order.
            correlation_id: Correlation ID for the request.

        Returns:
            dict: The RETURN order.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization, correlation_id=correlation_id)
        response = self._session.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def _get_preview_order(
        self, authorization: Authorization, adobe_customer_id: str, payload: dict
    ) -> dict:
        headers = self._get_headers(authorization)
        response = self._session.post(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{adobe_customer_id}/orders",
            ),
            params={"fetch-price": "true"},
            headers=headers,
            json=payload,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def _get_preview_order_line_item(
        self, line: dict, adobe_base_sku, quantity: int, discount_code, market_segment: str
    ) -> dict:
        line_item = {
            "extLineItemNumber": to_adobe_line_id(line["id"]),
            "offerId": get_adobe_product_by_marketplace_sku(adobe_base_sku, market_segment).sku,
            "quantity": quantity,
        }
        if discount_code:
            line_item["flexDiscountCodes"] = [discount_code]

        return line_item

    def _is_processed(self, order_item: tuple[dict, dict]) -> bool:
        order, mpt_item = order_item

        return (
            order["status"] == adobe_constants.AdobeOrderStatus.COMPLETE
            and mpt_item["status"] == adobe_constants.AdobeOrderStatus.COMPLETE
        )

    @wrap_http_error
    def _fetch_flex_discounts(self, authorization: Authorization, query_params: dict) -> list:
        headers = self._get_headers(authorization)
        next_url = "v3/flex-discounts"
        flex_discounts = []
        while next_url:
            response = self._session.get(
                urljoin(self._config.api_base_url, next_url),
                headers=headers,
                params=query_params,
                timeout=self._TIMEOUT,
            )
            response.raise_for_status()
            page = response.json()
            flex_discounts.extend(page["flexDiscounts"])
            next_url = page.get("links", {}).get("next", {}).get("uri")
            query_params = None
        return flex_discounts

    def _update_payload_by_deployment(
        self, authorization: Authorization, deployment_id: str | None, payload: dict[str, Any]
    ) -> None:
        if not deployment_id:
            payload["currencyCode"] = authorization.currency
            return

        for line_item in payload["lineItems"]:
            line_item["deploymentId"] = deployment_id
            line_item["currencyCode"] = authorization.currency
