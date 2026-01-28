import datetime as dt
import json
import logging
import re
from collections import defaultdict
from hashlib import sha256
from operator import itemgetter
from typing import Any
from urllib.parse import urljoin

import requests

from adobe_vipm.adobe import constants as adobe_constants
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.dataclasses import Authorization, ReturnableOrderInfo
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError, wrap_http_error
from adobe_vipm.adobe.mixins.errors import AdobeCreatePreviewError, ProcessingUpsizeLinesError
from adobe_vipm.adobe.utils import (  # noqa: WPS347
    find_first,
    get_item_by_subcription_id,
    to_adobe_line_id,
)
from adobe_vipm.airtable.models import get_adobe_product_by_marketplace_sku
from adobe_vipm.flows.constants import FAKE_CUSTOMERS_IDS, MARKET_SEGMENTS, Param
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.utils.deployment import get_deployment_id
from adobe_vipm.notifications import send_exception
from adobe_vipm.utils import get_partial_sku, map_by

logger = logging.getLogger(__name__)


def _get_failed_discount_codes(response_json) -> set:
    failed_discount_codes = set()
    for line_item in response_json["lineItems"]:
        failed_discounts = (
            fd for fd in line_item.get("flexDiscounts", []) if fd["result"] != "SUCCESS"
        )
        failed_discount_codes.update(fd["code"] for fd in failed_discounts)
    return failed_discount_codes


def _remove_failed_discount_codes(failed_discount_codes: set, payload: dict):
    for line_item in payload["lineItems"]:
        flex_discount_codes = set(line_item.get("flexDiscountCodes", ()))
        if flex_discount_codes:
            flex_discount_codes -= failed_discount_codes
            line_item["flexDiscountCodes"] = list(flex_discount_codes)


class OrderClientMixin:
    """Adobe Client Mixin to manage Orders flows of Adobe VIPM."""

    flex_discount_not_qualify_re = re.compile(r"Line Item: ?(\d+)", re.IGNORECASE)
    deployment_country_pattern = "{} ?- ?([A-Z]{{2,}})"

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
            response = requests.get(
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
        response = requests.get(
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
    ) -> dict:
        """
        Create Adobe Order based on Preview order.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            adobe_preview_order: Adobe Preview order.
            deployment_id: Adobe Deployment ID.

        Returns:
            dict: Adobe order.
        """
        authorization = self._config.get_authorization(authorization_id)
        line_items = [
            self._build_line_item(line_item) for line_item in adobe_preview_order["lineItems"]
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
        response = requests.post(
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

        Args:
            context: Order context.

        Returns:
            dict: The Preview order.

        Raises:
            AdobeCreatePreviewError
        """
        authorization = self._config.get_authorization(context.authorization_id)
        offer_ids = tuple(
            get_adobe_product_by_marketplace_sku(
                line["item"]["externalIds"]["vendor"], context.market_segment
            ).sku
            for line in context.upsize_lines + context.new_lines
        )
        flex_discounts = self.get_flex_discounts_per_base_offer(authorization, context, offer_ids)
        if flex_discounts:
            logger.info("Found flex discounts for base SKUs: %s", flex_discounts)
        payload = {
            "externalReferenceId": context.order_id,
            "orderType": adobe_constants.ORDER_TYPE_PREVIEW,
            "lineItems": [],
        }
        self._process_new_lines(context, flex_discounts, payload)
        if context.upsize_lines:
            try:
                self._process_upsize_lines(
                    context.authorization_id,
                    context.adobe_customer_id,
                    context.upsize_lines,
                    flex_discounts,
                    payload,
                    context.market_segment,
                )
            except ProcessingUpsizeLinesError as error:
                raise AdobeCreatePreviewError(error) from error

        deployment_id = get_deployment_id(context.order)
        self._update_payload_by_deployment(authorization, deployment_id, payload)
        if not payload["lineItems"]:
            self._logger.info(
                "Preview Order for %s was not created: line items are empty.",
                context.order_id,
            )
            return None

        customer_id = context.adobe_customer_id or FAKE_CUSTOMERS_IDS[context.market_segment]
        preview_order = self.get_preview_order(authorization, customer_id, payload)
        logger.info("Created preview order %s", preview_order["externalReferenceId"])
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
        response = requests.post(
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
                lambda order_item: dt.datetime.fromisoformat(order_item[0]["creationDate"])
                >= renewal_order_date,
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
                    adobe_constants.AdobeStatus.PROCESSED,
                    adobe_constants.AdobeStatus.PENDING,
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
        currency_code = self._config.get_authorization(authorization_id).currency
        adobe_line_items = order_created["lineItems"]

        payload = {
            "externalReferenceId": external_reference_id,
            "referenceOrderId": adobe_order_id,
            "orderType": adobe_constants.ORDER_TYPE_RETURN,
            "currencyCode": currency_code,
            "lineItems": adobe_line_items,
        }
        return self._create_return_order_base(authorization_id, customer_id, payload)

    def get_preview_order(  # noqa: WPS231
        self, authorization: Authorization, adobe_customer_id, payload: dict
    ) -> dict | None:
        """
        Gets a preview of an order based on the provided payload.

        Args:
            authorization: Authorization object containing authentication credentials.
            adobe_customer_id: Unique identifier of the Adobe customer.
            payload: Dictionary containing order details required for preview.

        Returns:
            A dictionary containing the response with order details, including computed
            pricing, after eliminating any failed discount codes.

        Raises:
            AdobeError: If all retries fail to handle the failed discount codes
            successfully.
        """
        response_json = None
        for _ in range(1, 6):
            try:
                response_json = self._get_preview_order(authorization, adobe_customer_id, payload)
            except AdobeError as ex:
                failed_discount_codes = self._get_fail_discounts_for_cust_not_qualified(ex, payload)
            else:
                failed_discount_codes = _get_failed_discount_codes(response_json)
            if not failed_discount_codes:
                break
            logger.warning("Found failed flex discounts: %s", failed_discount_codes)
            _remove_failed_discount_codes(failed_discount_codes, payload)
        else:
            msg = f"After 5 attempts still finding failed discount codes: {failed_discount_codes}."
            send_exception("Failed applying discount codes", msg)
            raise AdobeError(msg)

        return response_json

    def get_flex_discounts_per_base_offer(
        self,
        authorization: Authorization,
        context: Context,
        offer_ids: tuple,
    ) -> dict:
        """Fetches active flex discounts for the provided base offer IDs."""
        # TODO: Change this when Adobe starts supporting multiple codes per single baseOfferId
        country = context.customer_data["address"]["country"]
        if context.customer_data[Param.DEPLOYMENT_ID]:
            match = re.match(
                self.deployment_country_pattern.format(context.customer_data[Param.DEPLOYMENT_ID]),
                context.customer_data[Param.DEPLOYMENTS],
                re.IGNORECASE,
            )
            if match:
                country = match.group(1)
        try:
            flex_discounts = self._get_flex_discounts(
                authorization,
                MARKET_SEGMENTS[context.market_segment],
                country,
                offer_ids,
            )
        except AdobeAPIError as error:
            if error.code == AdobeStatus.INVALID_COUNTRY_FOR_PARTNER:
                logger.warning(
                    "Invalid country %s for partner when getting flex discounts.", country
                )
                flex_discounts = ()
            else:
                raise
        base_offers_with_discounts = {}
        for flex_discount in filter(lambda fd: fd["status"] == "ACTIVE", flex_discounts):
            base_offers_with_discounts.update(
                dict.fromkeys(flex_discount["qualification"]["baseOfferIds"], flex_discount["code"])
            )
        return base_offers_with_discounts

    def _get_fail_discounts_for_cust_not_qualified(self, ex: AdobeError, payload: dict) -> set:
        if ex.code == adobe_constants.AdobeStatus.CUSTOMER_NOT_QUALIFIED_FOR_FLEX_DISCOUNT:
            logger.warning("%s", ex)
            matched = self.flex_discount_not_qualify_re.match(ex.details[0])
            if not matched:
                raise AdobeError(
                    f"Can't parse Adobe error message: '{ex.details}'. Expected format example:"
                    f" 'Line Item: 2, Reason: Invalid Flexible Discount'"
                )
            item_no = int(matched.group(1))
            return set(
                find_first(lambda line: line["extLineItemNumber"] == item_no, payload["lineItems"])[
                    "flexDiscountCodes"
                ]
            )
        raise ex

    def _process_new_lines(self, context: Context, flex_discounts: dict, payload: dict):
        for line in context.new_lines:
            adobe_base_sku = line["item"]["externalIds"]["vendor"]
            line_item = self._get_preview_order_line_item(
                line,
                adobe_base_sku,
                line["quantity"],
                flex_discounts.get(
                    get_adobe_product_by_marketplace_sku(adobe_base_sku, context.market_segment).sku
                ),
                context.market_segment,
            )
            payload["lineItems"].append(line_item)

    def _process_upsize_lines(
        self,
        authorization_id: str,
        adobe_customer_id: str,
        upsize_lines: list[dict],
        discounts: dict,
        payload: dict,
        market_segment: str,
    ):
        offer_ids = [line_item["item"]["externalIds"]["vendor"] for line_item in upsize_lines]
        # ???: This method belongs to SubscriptionClientMixin
        upsize_subscriptions = self.get_subscriptions_for_offers(
            authorization_id, adobe_customer_id, offer_ids
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
                discounts.get(
                    get_adobe_product_by_marketplace_sku(adobe_base_sku, market_segment).sku
                ),
                market_segment,
            )
            payload["lineItems"].append(line_item)

    def _build_line_item(self, adobe_line_item: dict) -> dict:
        line_item = {
            "extLineItemNumber": adobe_line_item["extLineItemNumber"],
            "offerId": adobe_line_item["offerId"],
            "quantity": adobe_line_item["quantity"],
        }
        if adobe_line_item.get("flexDiscounts"):
            line_item["flexDiscountCodes"] = [adobe_line_item["flexDiscounts"][0]["code"]]
        if adobe_line_item.get("deploymentId"):
            line_item["deploymentId"] = adobe_line_item["deploymentId"]
            line_item["currencyCode"] = adobe_line_item["currencyCode"]
        return line_item

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
        response = requests.post(
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
        response = requests.post(
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
            order["status"] == adobe_constants.AdobeStatus.PROCESSED
            and mpt_item["status"] == adobe_constants.AdobeStatus.PROCESSED
        )

    @wrap_http_error
    def _get_flex_discounts(
        self, authorization: Authorization, segment: str, country: str, offer_ids: tuple[str, ...]
    ) -> dict:
        headers = self._get_headers(authorization)
        offer_ids = ",".join(offer_ids)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                "v3/flex-discounts",
            ),
            headers=headers,
            params={"market-segment": {segment}, "country": {country}, "offer-ids": {offer_ids}},
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["flexDiscounts"]

    def _update_payload_by_deployment(
        self, authorization: Authorization, deployment_id: str | None, payload: dict[str, Any]
    ) -> None:
        if not deployment_id:
            payload["currencyCode"] = authorization.currency
            return

        for line_item in payload["lineItems"]:
            line_item["deploymentId"] = deployment_id
            line_item["currencyCode"] = authorization.currency
