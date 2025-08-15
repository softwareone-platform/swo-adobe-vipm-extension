import datetime as dt
import json
from collections import defaultdict
from hashlib import sha256
from operator import itemgetter
from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.constants import (
    CANCELLATION_WINDOW_DAYS,
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_PREVIEW_RENEWAL,
    ORDER_TYPE_RENEWAL,
    ORDER_TYPE_RETURN,
    AdobeStatus,
)
from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.adobe.errors import AdobeProductNotFoundError, wrap_http_error
from adobe_vipm.adobe.utils import (  # noqa: WPS347
    find_first,
    get_item_by_subcription_id,
    to_adobe_line_id,
)
from adobe_vipm.airtable.models import get_adobe_product_by_marketplace_sku
from adobe_vipm.flows.constants import Param
from adobe_vipm.utils import get_partial_sku, map_by


class OrderClientMixin:
    """Adobe Client Mixin to manage Orders flows of Adobe VIPM."""

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
            "orderType": ORDER_TYPE_NEW,
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
    def create_preview_order(  # noqa: C901 WPS231
        self,
        authorization_id: str,
        customer_id: str,
        order_id: str,
        upsize_lines: list,
        new_lines: list,
        deployment_id: str | None = None,
    ) -> dict | None:
        """
        Create Preview orders.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            order_id: MPT Order id to refer to.
            upsize_lines: lines to be upsized.
            new_lines: lines eto be created.
            deployment_id: Adobe Deployment ID.

        Returns:
            dict: The Preview order.
        """
        authorization = self._config.get_authorization(authorization_id)
        payload = {
            "externalReferenceId": order_id,
            "orderType": ORDER_TYPE_PREVIEW,
            "lineItems": [],
        }

        for line in new_lines:
            line_item = self._get_preview_order_line_item(line, line["quantity"])
            payload["lineItems"].append(line_item)

        if upsize_lines:
            offer_ids = [line_item["item"]["externalIds"]["vendor"] for line_item in upsize_lines]
            upsize_subscriptions = self.get_subscriptions_for_offers(
                authorization_id,
                customer_id,
                offer_ids,
            )
            offer_subscriptions = map_by("offerId", upsize_subscriptions)
            map_by_base_offer_subscriptions = {
                get_partial_sku(offer_id): subs for offer_id, subs in offer_subscriptions.items()
            }

        for line in upsize_lines:
            adobe_base_sku = line["item"]["externalIds"]["vendor"]

            if adobe_base_sku not in map_by_base_offer_subscriptions:
                raise AdobeProductNotFoundError(
                    f"Product {adobe_base_sku} not found in Adobe to make the upsize."
                    f"This could be because the product is not available for this customer "
                    f"or the subscription has been terminated."
                )

            adobe_subscription = map_by_base_offer_subscriptions[adobe_base_sku]
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

            line_item = self._get_preview_order_line_item(line, quantity)
            payload["lineItems"].append(line_item)

        if deployment_id:
            for line_item in payload["lineItems"]:
                line_item["deploymentId"] = deployment_id
                line_item["currencyCode"] = authorization.currency
        else:
            payload["currencyCode"] = authorization.currency

        if not payload["lineItems"]:
            self._logger.info(
                "Preview Order for %s was not created: line items are empty.",
                order_id,
            )
            return None

        headers = self._get_headers(authorization)
        response = requests.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

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
        payload = {"orderType": ORDER_TYPE_PREVIEW_RENEWAL}
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
            sku: item sku
            customer_coterm_date: customer coterm date
            external_reference: External Reference ID.
            return_orders: orders to return

        Returns:
            list(dict): The RETURN order.
        """
        current_date = dt.datetime.now(tz=dt.UTC).date()
        start_date = current_date - dt.timedelta(days=CANCELLATION_WINDOW_DAYS)

        returning_order_ids = [order["referenceOrderId"] for order in (return_orders or [])]

        orders = self.get_orders(
            authorization_id,
            customer_id,
            filters={
                "order-type": [ORDER_TYPE_NEW, ORDER_TYPE_RENEWAL],
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
            lambda order_item: order_item[0]["orderType"] == ORDER_TYPE_RENEWAL,
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
    ) -> list[dict]:
        """
        Retrieve RETURN orders filter by external reference.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.
            external_reference: External Reference ID.

        Returns:
            list(dict): The RETURN order.
        """
        orders = self.get_orders(
            authorization_id,
            customer_id,
            filters={
                "order-type": ORDER_TYPE_RETURN,
                "status": [AdobeStatus.PROCESSED, AdobeStatus.PENDING],
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
            "orderType": ORDER_TYPE_RETURN,
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
            "orderType": ORDER_TYPE_RETURN,
            "currencyCode": currency_code,
            "lineItems": adobe_line_items,
        }
        return self._create_return_order_base(authorization_id, customer_id, payload)

    def _build_line_item(self, adobe_line_item: dict) -> dict:
        line_item = {
            "extLineItemNumber": adobe_line_item["extLineItemNumber"],
            "offerId": adobe_line_item["offerId"],
            "quantity": adobe_line_item["quantity"],
        }
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

    def _get_preview_order_line_item(self, line: dict, quantity: int) -> dict:
        adobe_base_sku = line["item"]["externalIds"]["vendor"]
        product_sku = get_adobe_product_by_marketplace_sku(adobe_base_sku).sku

        return {
            "extLineItemNumber": to_adobe_line_id(line["id"]),
            "offerId": product_sku,
            "quantity": quantity,
        }

    def _is_processed(self, order_item: tuple[dict, dict]) -> bool:
        order, mpt_item = order_item

        return (
            order["status"] == AdobeStatus.PROCESSED and mpt_item["status"] == AdobeStatus.PROCESSED
        )
