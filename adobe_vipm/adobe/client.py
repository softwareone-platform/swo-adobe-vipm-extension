import json
import logging
from datetime import datetime, timedelta
from hashlib import sha256
from typing import List, MutableMapping, Tuple
from urllib.parse import urlencode, urljoin
from uuid import uuid4

import requests

from adobe_vipm.adobe.config import Config, get_config
from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_PREVIEW_RENEWAL,
    ORDER_TYPE_RETURN,
    STATUS_ORDER_CANCELLED,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.adobe.dataclasses import (
    AdobeProduct,
    APIToken,
    Credentials,
    Distributor,
    Reseller,
)
from adobe_vipm.adobe.errors import wrap_http_error
from adobe_vipm.adobe.utils import (
    get_actual_sku,
    get_item_to_return,
    join_phone_number,
    to_adobe_line_id,
)

logger = logging.getLogger(__name__)


class AdobeClient:
    def __init__(self) -> None:
        self._config: Config = get_config()
        self._token_cache: MutableMapping[Credentials, APIToken] = {}

    @wrap_http_error
    def create_reseller_account(
        self,
        country: str,
        reseller_id: str,
        reseller_data: dict,
    ) -> str:
        """
        Creates a reseller account under the distributor account identified by `country`.

        Args:
            region (str): Region to which the distributor account is bounded to and into which
            the reseller must be created.
            reseller_id (str): Identifier of the reseller in the Marketplace platform.
            reseller_data (dict): Data of the reseller to create.

        Returns:
            str: The identifier of the reseller in the Adobe VIP Markerplace.
        """
        distributor: Distributor = self._config.get_distributor(country)
        payload = {
            "externalReferenceId": reseller_id,
            "distributorId": distributor.id,
            "companyProfile": {
                "companyName": reseller_data["companyName"],
                "preferredLanguage": reseller_data["preferredLanguage"],
                "address": {
                    "country": reseller_data["address"]["country"],
                    "region": reseller_data["address"]["state"],
                    "city": reseller_data["address"]["city"],
                    "addressLine1": reseller_data["address"]["addressLine1"],
                    "addressLine2": reseller_data["address"]["addressLine2"],
                    "postalCode": reseller_data["address"]["postalCode"],
                    "phoneNumber": join_phone_number(reseller_data["contact"]["phone"]),
                },
                "contacts": [
                    {
                        "firstName": reseller_data["contact"]["firstName"],
                        "lastName": reseller_data["contact"]["lastName"],
                        "email": reseller_data["contact"]["email"],
                        "phoneNumber": join_phone_number(
                            reseller_data["contact"]["phone"]
                        ),
                    }
                ],
            },
        }
        headers = self._get_headers(distributor.credentials, correlation_id=reseller_id)
        response = requests.post(
            urljoin(self._config.api_base_url, "/v3/resellers"),
            headers=headers,
            json=payload,
        )

        response.raise_for_status()

        created_reseller = response.json()
        adobe_reseller_id = created_reseller["resellerId"]
        logger.info(
            f"Reseller {reseller_id} - {reseller_data['companyName']} "
            "created successfully in distributor account "
            f"{distributor.id} ({country}): {adobe_reseller_id}",
        )
        return adobe_reseller_id

    @wrap_http_error
    def create_customer_account(
        self,
        reseller_country: str,
        agreement_id: str,
        customer_data: dict,
    ) -> str:
        """
        Creates a customer account under the reseller of the country `reseller_country`.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller under which the account
            should be created.
            agreement_id (str): id of the Marketplace platform agreement for this customer.
            customer_data (dict): Data of the customer to create.

        Returns:
            str: The identifier of the customer in the Adobe VIP Markerplace.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        company_name: str = f"{customer_data['companyName']} ({agreement_id})"
        payload = {
            "resellerId": reseller.id,
            "externalReferenceId": agreement_id,
            "companyProfile": {
                "companyName": company_name,
                "preferredLanguage": customer_data["preferredLanguage"],
                "address": {
                    "country": customer_data["address"]["country"],
                    "region": customer_data["address"]["state"],
                    "city": customer_data["address"]["city"],
                    "addressLine1": customer_data["address"]["addressLine1"],
                    "addressLine2": customer_data["address"]["addressLine2"],
                    "postalCode": customer_data["address"]["postalCode"],
                    "phoneNumber": join_phone_number(customer_data["contact"]["phone"]),
                },
                "contacts": [
                    {
                        "firstName": customer_data["contact"]["firstName"],
                        "lastName": customer_data["contact"]["lastName"],
                        "email": customer_data["contact"]["email"],
                        "phoneNumber": join_phone_number(
                            customer_data["contact"]["phone"]
                        ),
                    }
                ],
            },
        }
        correlation_id = sha256(json.dumps(payload).encode()).hexdigest()
        headers = self._get_headers(
            reseller.distributor.credentials, correlation_id=correlation_id
        )
        response = requests.post(
            urljoin(self._config.api_base_url, "/v3/customers"),
            headers=headers,
            json=payload,
        )

        response.raise_for_status()

        created_customer = response.json()
        adobe_customer_id = created_customer["customerId"]
        logger.info(
            f"Customer {company_name} "
            f"created successfully for reseller {reseller.id}: {adobe_customer_id}",
        )
        return adobe_customer_id

    @wrap_http_error
    def search_new_and_returned_orders_by_sku_line_number(
        self,
        reseller_country: str,
        customer_id: str,
        sku: str,
        mpt_line_id: str,
    ) -> List[Tuple[dict, dict, dict | None]]:
        """
        Search all the NEW orders placed by the customer identified by `customer_id`
        for a a given `sku` and `line_number` and the corresponding RETURN order
        if it exists.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer that placed the order.
            sku (str): The SKU to search for.
            line_number (int): the line number to search for.

        Returns:
            list: Return a list of three values tuple with the NEW order the item identified
            by the pair sku, line_number and the RETURN order if it exists or None.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        headers = self._get_headers(reseller.distributor.credentials)

        line_number = to_adobe_line_id(mpt_line_id)

        orders = []
        orders_base_url = f"/v3/customers/{customer_id}/orders"

        new_orders_params = {
            "order-type": ORDER_TYPE_NEW,
            "limit": 100,
            "offset": 0,
        }

        new_orders_next_url = f"{orders_base_url}?{urlencode(new_orders_params)}"

        while new_orders_next_url:
            new_orders_response = requests.get(
                urljoin(self._config.api_base_url, new_orders_next_url),
                headers=headers,
            )
            new_orders_response.raise_for_status()
            new_orders_page = new_orders_response.json()
            for order in new_orders_page["items"]:
                if order["status"] not in [STATUS_PROCESSED, STATUS_ORDER_CANCELLED]:
                    continue
                actual_sku = get_actual_sku(order["lineItems"], sku)
                if not actual_sku:
                    continue

                logger.debug(
                    f"Found order to return for sku {actual_sku}: {order['orderId']}"
                )

                item_to_return = get_item_to_return(order["lineItems"], line_number)
                external_id = f"{order['externalReferenceId']}-{line_number}"

                returned_orders_response = requests.get(
                    urljoin(self._config.api_base_url, orders_base_url),
                    headers=headers,
                    params={
                        "reference-order-id": order["orderId"],
                        "offer-id": actual_sku,
                        "order-type": ORDER_TYPE_RETURN,
                        "status": [STATUS_PROCESSED, STATUS_PENDING],
                        "limit": 1,
                        "offset": 0,
                    },
                )
                returned_orders_response.raise_for_status()
                returned_orders_page = returned_orders_response.json()
                if returned_orders_page["totalCount"] == 0:
                    logger.debug(
                        f"No return order found for order {order['orderId']} "
                        f"and external_id {external_id}",
                    )
                    orders.append((order, item_to_return, None))
                    continue

                return_order = returned_orders_page["items"][0]

                if return_order["externalReferenceId"] != external_id:
                    logger.debug(
                        f"No return order found for order {order['orderId']} "
                        f"and external_id {external_id}",
                    )
                    orders.append((order, item_to_return, None))
                    continue

                logger.debug(
                    f"Return order found for order {order['orderId']} "
                    f"and external_id {external_id}",
                )

                orders.append((order, item_to_return, return_order))

            new_orders_next_url = new_orders_page["links"].get("next", {}).get("uri")

        return orders

    @wrap_http_error
    def create_return_order(
        self,
        reseller_country: str,
        customer_id: str,
        returning_order: dict,
        returning_item: dict,
    ) -> dict:
        """
        Creates an order of type RETURN for a given `item` that was purchased in the
        order identified by `returning_order_id`.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer that place the RETURN order.
            returning_order (dict): The order that contains the item to return.
            returning_item (dict): The item that must be returned.

        Returns:
            dict: The RETURN order.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        line_number = returning_item["extLineItemNumber"]
        quantity = returning_item["quantity"]
        sku = returning_item["offerId"]
        external_id = f"{returning_order['externalReferenceId']}-{line_number}"
        payload = {
            "externalReferenceId": external_id,
            "referenceOrderId": returning_order["orderId"],
            "currencyCode": reseller.distributor.currency,
            "orderType": ORDER_TYPE_RETURN,
            "lineItems": [],
        }

        payload["lineItems"].append(
            {
                "extLineItemNumber": line_number,
                "offerId": sku,
                "quantity": quantity,
            },
        )

        headers = self._get_headers(
            reseller.distributor.credentials,
            correlation_id=external_id,
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
        reseller_country: str,
        customer_id: str,
        order_id: str,
        lines: list,
    ) -> dict:
        """
        Creates an order of type PREVIEW for a given Marketplace platform order.
        Creating a PREVIEW order allows to validate the order lines and eventually
        obtaining from Adobe replacement SKUs to get the best discount level
        the customer is elegible for.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer that place the PREVIEW order.
            order_id: The identifier of the Marketplace platform order for which the PREVIEW
            order must be created.
            items: The list of order items for which creating the preview order.

        Returns:
            dict: The PREVIEW order.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        payload = {
            "externalReferenceId": order_id,
            "currencyCode": reseller.distributor.currency,
            "orderType": ORDER_TYPE_PREVIEW,
            "lineItems": [],
        }

        for line in lines:
            product: AdobeProduct = self._config.get_adobe_product(
                line["item"]["externalIds"]["vendor"]
            )
            quantity = line["quantity"]
            old_quantity = line["oldQuantity"]

            if quantity > old_quantity:
                # For purchasing new lines (oldQuantity = 0) or upsizing lines
                # quantity it must send the delta (quantity - oldQuantity) since
                # it is placing a new order.
                # For downsizing lines quantity it must send the actual quantity
                # since the previous purchased quantity has been returned back
                # through one or more RETURN orders.
                quantity = quantity - old_quantity
            payload["lineItems"].append(
                {
                    "extLineItemNumber": to_adobe_line_id(line["id"]),
                    "offerId": product.sku,
                    "quantity": quantity,
                }
            )

        headers = self._get_headers(reseller.distributor.credentials)
        response = requests.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_new_order(
        self,
        reseller_country: str,
        customer_id: str,
        adobe_preview_order: dict,
    ) -> dict:
        """
        Creates an order of type NEW (the actual order) for a given Marketplace platform order.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer that place the NEW order.
            adobe_preview_order (dict): The Adobe PREVIEW order that must be created.

        Returns:
            dict: The NEW order.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        payload = {
            "externalReferenceId": adobe_preview_order["externalReferenceId"],
            "currencyCode": reseller.distributor.currency,
            "orderType": ORDER_TYPE_NEW,
            "lineItems": adobe_preview_order["lineItems"],
        }

        headers = self._get_headers(
            reseller.distributor.credentials,
            correlation_id=adobe_preview_order["externalReferenceId"],
        )
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
        reseller_country: str,
        customer_id: str,
    ) -> dict:
        """
        Creates a preview of the renewal for a given customer.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer account.

        Returns:
            dict: a preview of the renewal.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        payload = {"orderType": ORDER_TYPE_PREVIEW_RENEWAL}
        headers = self._get_headers(reseller.distributor.credentials)
        response = requests.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def get_order(
        self,
        reseller_country: str,
        customer_id: str,
        order_id: str,
    ) -> dict:
        """
        Retrieves an order of a given customer by its identifier.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer that placed the order.
            order_id (str): Identifier of the order that must be retrieved.

        Returns:
            dict: The retrieved order.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        headers = self._get_headers(reseller.distributor.credentials)
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
    def get_subscription(
        self,
        reseller_country: str,
        customer_id: str,
        subscription_id: str,
    ) -> dict:
        """
        Retrieve a subscription by its identifier.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer to which the subscription belongs to.
            subscription_id (str): Identifier of the subscription that must be retrieved.

        Returns:
            str: The retrieved subscription.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        headers = self._get_headers(reseller.distributor.credentials)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/subscriptions/{subscription_id}",
            ),
            headers=headers,
        )

        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def update_subscription(
        self,
        reseller_country: str,
        customer_id: str,
        subscription_id: str,
        auto_renewal: bool = True,
        quantity: int | None = None,
    ) -> dict:
        """
        Update a subscription either to reduce the quantity on the anniversary date either
        to switch auto renewal off.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer to which the subscription belongs to.
            subscription_id (str): Identifier of the subscription that must be retrieved.
            auto_renewal (boolean): Set if the subscription must be auto renewed on the anniversary
            date or not. Default to True.
            quantity: The quantity of licenses that must be renewed on the anniversary date. Default
            to None mean to leave it unchanged.

        Returns:
            str: The retrieved subscription.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        headers = self._get_headers(reseller.distributor.credentials)
        payload = {
            "autoRenewal": {
                "enabled": auto_renewal,
            },
        }
        if quantity:
            payload["autoRenewal"]["quantity"] = quantity

        response = requests.patch(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/subscriptions/{subscription_id}",
            ),
            headers=headers,
            json=payload,
        )

        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def preview_transfer(
        self,
        reseller_country: str,
        membership_id: str,
    ):
        """
        Retrieves the subscriptions owned by a given membership identifier of the
        Adobe VIP program that will be transferred to the Adobe VIP Marketplace program.

        Args:
            reseller_country (str): The country of the reseller to select the credentials
            to access the Adobe VIP Marketplace API.
            membership_id (str): The membership identifier.

        Returns:
            dict: a transfer preview object.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        headers = self._get_headers(reseller.distributor.credentials)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/memberships/{membership_id}/offers",
            ),
            headers=headers,
        )

        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_transfer(
        self,
        reseller_country: str,
        order_id: str,
        membership_id: str,
    ):
        """
        Creates a transfer order to move the subscriptions owned by a given
        membership identifier from the Adobe VIP program to the Adobe VIP Marketplace
        program.

        Args:
            reseller_country (str): The country of the reseller under which such customer
            and its subscriptions will be transferred.
            order_id (str): Identifier of the MPT transfer order
            membership_id (str): The membership identifier.

        Returns:
            dict: a transfer object.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        headers = self._get_headers(
            reseller.distributor.credentials, correlation_id=order_id
        )
        response = requests.post(
            urljoin(
                self._config.api_base_url,
                f"/v3/memberships/{membership_id}/transfers",
            ),
            headers=headers,
            json={
                "resellerId": reseller.id,
            },
        )

        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def get_transfer(
        self,
        reseller_country: str,
        membership_id: str,
        transfer_id: str,
    ):
        """
        Retrieve a transfer object by the membership and transfer identifiers.

        Args:
            reseller_country (str): The country of the reseller to select the credentials
            to access the Adobe VIP Marketplace API.
            membership_id (str): The membership identifier.
            transfer_id (str): The transfer identifier.

        Returns:
            _type_: A transfer object.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        headers = self._get_headers(reseller.distributor.credentials)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/memberships/{membership_id}/transfers/{transfer_id}",
            ),
            headers=headers,
        )

        response.raise_for_status()
        return response.json()

    def _get_headers(self, credentials: Credentials, correlation_id=None):
        return {
            "X-Api-Key": credentials.client_id,
            "Authorization": f"Bearer {self._get_auth_token(credentials).token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid4()),
            "x-correlation-id": correlation_id or str(uuid4()),
        }

    def _refresh_auth_token(self, credentials: Credentials):
        """
        Request an authentication token for the Adobe VIPM API
        using the credentials associated to a given the reseller.
        """

        data = {
            "grant_type": "client_credentials",
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scope": self._config.api_scopes,
        }
        response = requests.post(
            url=self._config.auth_endpoint_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
        )
        if response.status_code == 200:
            token_info = response.json()
            self._token_cache[credentials] = APIToken(
                token=token_info["access_token"],
                expires=(
                    datetime.now() + timedelta(seconds=token_info["expires_in"] - 180)
                ),
            )
        response.raise_for_status()

    def _get_auth_token(self, credentials: Credentials):
        token: APIToken | None = self._token_cache.get(credentials)
        if not token or token.is_expired():
            self._refresh_auth_token(credentials)
        token = self._token_cache[credentials]
        return token


_ADOBE_CLIENT = None


def get_adobe_client() -> AdobeClient:
    """
    Returns an instance of the `AdobeClient`.

    Returns:
        AdobeClient: An instance of the `AdobeClient`.
    """
    global _ADOBE_CLIENT
    if not _ADOBE_CLIENT:
        _ADOBE_CLIENT = AdobeClient()
    return _ADOBE_CLIENT
