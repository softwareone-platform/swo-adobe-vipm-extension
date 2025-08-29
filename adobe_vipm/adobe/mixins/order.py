import json
from collections import defaultdict
from datetime import date, datetime, timedelta
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
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.adobe.dataclasses import ReturnableOrderInfo
from adobe_vipm.adobe.errors import AdobeProductNotFoundError, wrap_http_error
from adobe_vipm.adobe.utils import (
    find_first,
    get_item_by_subcription_id,
    to_adobe_line_id,
)
from adobe_vipm.airtable.models import get_adobe_product_by_marketplace_sku
from adobe_vipm.utils import get_partial_sku, map_by


class OrderClientMixin:

    def _is_processed(self, order_item):
        order, item = order_item
        return order["status"] == STATUS_PROCESSED and item["status"] == STATUS_PROCESSED

    @wrap_http_error
    def get_orders(self, authorization_id, customer_id, filters=None):
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
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/orders/{order_id}",
            ),
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_new_order(
        self,
        authorization_id: str,
        customer_id: str,
        adobe_preview_order: dict,
        deployment_id: str = None,
    ) -> dict:
        authorization = self._config.get_authorization(authorization_id)

        def build_line_item(item):
            line_item = {
                "extLineItemNumber": item["extLineItemNumber"],
                "offerId": item["offerId"],
                "quantity": item["quantity"],
            }
            if "deploymentId" in item:
                line_item["deploymentId"] = item["deploymentId"]
                line_item["currencyCode"] = item["currencyCode"]
            return line_item

        lineItems = [
            build_line_item(item) for item in adobe_preview_order["lineItems"]
        ]

        payload = {
            "externalReferenceId": adobe_preview_order["externalReferenceId"],
            "orderType": ORDER_TYPE_NEW,
            "lineItems": lineItems,
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
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_preview_order(
        self,
        authorization_id: str,
        customer_id: str,
        order_id: str,
        upsize_lines: list,
        new_lines: list,
        deployment_id: str = None,
    ) -> dict | None:
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
            offer_ids = [line["item"]["externalIds"]["vendor"] for line in upsize_lines]
            upsize_subscriptions = self.get_subscriptions_for_offers(
                authorization_id,
                customer_id,
                offer_ids,
            )
            map_by_offer_subscriptions = map_by("offerId", upsize_subscriptions)
            map_by_base_offer_subscriptions = {
                get_partial_sku(k): v for k, v in map_by_offer_subscriptions.items()
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
            renewal_quantity = adobe_subscription["autoRenewal"]["renewalQuantity"]
            current_quantity = adobe_subscription["currentQuantity"]
            if renewal_quantity < current_quantity:
                diff = current_quantity - renewal_quantity
            else:
                diff = 0

            quantity = line["quantity"] - line["oldQuantity"] - diff
            if quantity <= 0:
                self._logger.info(
                    f"Upsizing item {line['id']}({adobe_base_sku}) is skipped. "
                    f"Because overall quantity is equal or below 0. "
                    f"line quantity = {line['quantity']}, "
                    f"line old quantity = {line['oldQuantity']}, "
                    f"adobe renewal quantity = {renewal_quantity}, "
                    f"adobe current quantity = {current_quantity}."
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
                f"Preview Order for {order_id} was not created: line items are empty."
            )
            return

        headers = self._get_headers(authorization)
        response = requests.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_preview_renewal(
        self,
        authorization_id: str,
        customer_id: str,
    ) -> dict:
        authorization = self._config.get_authorization(authorization_id)
        payload = {"orderType": ORDER_TYPE_PREVIEW_RENEWAL}
        headers = self._get_headers(authorization)
        response = requests.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
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
            external_reference: External Reference ID.
            return_orders: orders to return

        Returns:
            list(dict): The RETURN order.
        """
        start_date = date.today() - timedelta(days=CANCELLATION_WINDOW_DAYS)

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
            renewal_order_date = datetime.fromisoformat(renewal_order_item[0]["creationDate"])
            order_items = filter(
                lambda order_item: datetime.fromisoformat(order_item[0]["creationDate"])
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
    ):
        orders = self.get_orders(
            authorization_id,
            customer_id,
            filters={
                "order-type": ORDER_TYPE_RETURN,
                "status": [STATUS_PROCESSED, STATUS_PENDING],
            },
        )
        results = defaultdict(list)
        for order in orders:
            if not order["externalReferenceId"].startswith(external_reference):
                continue
            for item in order["lineItems"]:
                results[get_partial_sku(item["offerId"])].append(order)
        return results


    @wrap_http_error
    def _create_return_order_base(
        self,
        authorization_id: str,
        customer_id: str,
        payload: dict,
        correlation_id: str = None,
    ) -> dict:
        """
        Base method to create a return order with the given payload.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer that place the RETURN order.
            payload (dict): The payload for the return order.
            correlation_id (str, optional): Correlation ID for the request.

        Returns:
            dict: The RETURN order.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization, correlation_id=correlation_id)
        response = requests.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_return_order(
        self,
        authorization_id: str,
        customer_id: str,
        returning_order: dict,
        returning_item: dict,
        external_reference: str,
        deployment_id: str = None,
    ) -> dict:
        """
        Creates an order of type RETURN for a given `item` that was purchased in the
        order identified by `returning_order_id`.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer that place the RETURN order.
            returning_order (dict): The order that contains the item to return.
            returning_item (dict): The item that must be returned.
            external_reference (str): External reference for the return order.
            deployment_id (str, optional): Deployment ID if the return is for a deployment.

        Returns:
            dict: The RETURN order.
        """
        line_number = returning_item["extLineItemNumber"]
        quantity = returning_item["quantity"]
        sku = returning_item["offerId"]
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
            "offerId": sku,
            "quantity": quantity,
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
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer that place the RETURN order.
            order_created (dict): The Adobe order to return.

        Returns:
            dict: The RETURN order.
        """
        external_reference_id = f"{order_created["externalReferenceId"]}_{order_created["orderId"]}"
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
