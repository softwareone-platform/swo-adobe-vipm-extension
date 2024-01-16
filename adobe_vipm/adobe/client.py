import logging
from datetime import datetime, timedelta
from typing import MutableMapping
from urllib.parse import urljoin
from uuid import uuid4

import requests

from adobe_vipm.adobe.config import Config
from adobe_vipm.adobe.constants import (
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_RETURN,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.adobe.dataclasses import AdobeProduct, APIToken, Credentials, Reseller
from adobe_vipm.adobe.errors import wrap_http_error

logger = logging.getLogger(__name__)


class AdobeClient:
    def __init__(self) -> None:
        self._config: Config = Config()
        self._token_cache: MutableMapping[Credentials, APIToken] = {}

    @wrap_http_error
    def create_reseller_account(
        self,
        region: str,
        reseller_id: str,
        reseller_data: dict,
    ) -> str:
        """
        Creates a reseller account under the regional account identified by `region`.

        Args:
            region (str): Region to which the account is bounded to and into which
            the reseller must be created.
            reseller_id (str): Identifier of the reseller in the Marketplace platform.
            reseller_data (dict): Data of the reseller to create.

        Returns:
            str: The identifier of the reseller in the Adobe VIP Markerplace.
        """
        credentials: Credentials = self._config.get_credentials(region)
        payload = {
            "externalReferenceId": reseller_id,
            "distributorId": credentials.distributor_id,
            "companyProfile": {
                "companyName": reseller_data["CompanyName"],
                "preferredLanguage": reseller_data["PreferredLanguage"],
                "address": {
                    "country": reseller_data["Address"]["country"],
                    "region": reseller_data["Address"]["state"],
                    "city": reseller_data["Address"]["city"],
                    "addressLine1": reseller_data["Address"]["addressLine1"],
                    "addressLine2": reseller_data["Address"]["addressLine2"],
                    "postalCode": reseller_data["Address"]["postCode"],
                    "phoneNumber": reseller_data["Contact"]["phone"],
                },
                "contacts": [
                    {
                        "firstName": reseller_data["Contact"]["firstName"],
                        "lastName": reseller_data["Contact"]["lastName"],
                        "email": reseller_data["Contact"]["email"],
                        "phoneNumber": reseller_data["Contact"]["phone"],
                    }
                ],
            },
        }
        headers = self._get_headers(credentials, correlation_id=reseller_id)
        response = requests.post(
            urljoin(self._config.api_base_url, "/v3/resellers"),
            headers=headers,
            json=payload,
        )

        response.raise_for_status()

        created_reseller = response.json()
        adobe_reseller_id = created_reseller["resellerId"]
        logger.info(
            f"Reseller {reseller_id} - {reseller_data['CompanyName']} "
            f"created successfully in regional account {region}: {adobe_reseller_id}",
        )
        return adobe_reseller_id

    @wrap_http_error
    def create_customer_account(
        self,
        reseller_country: str,
        customer_id: str,
        customer_data: dict,
    ) -> str:
        """
        Creates a customer account under the reseller of the country `reseller_country`.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller under which the account
            should be created.
            customer_id (str): Identifier of the customer in the Marketplace platform.
            customer_data (dict): Data of the customer to create.

        Returns:
            str: The identifier of the customer in the Adobe VIP Markerplace.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        payload = {
            "resellerId": reseller.id,
            "externalReferenceId": customer_id,
            "companyProfile": {
                "companyName": customer_data["CompanyName"],
                "preferredLanguage": customer_data["PreferredLanguage"],
                "address": {
                    "country": customer_data["Address"]["country"],
                    "region": customer_data["Address"]["state"],
                    "city": customer_data["Address"]["city"],
                    "addressLine1": customer_data["Address"]["addressLine1"],
                    "addressLine2": customer_data["Address"]["addressLine2"],
                    "postalCode": customer_data["Address"]["postCode"],
                    "phoneNumber": customer_data["Contact"]["phone"],
                },
                "contacts": [
                    {
                        "firstName": customer_data["Contact"]["firstName"],
                        "lastName": customer_data["Contact"]["lastName"],
                        "email": customer_data["Contact"]["email"],
                        "phoneNumber": customer_data["Contact"]["phone"],
                    }
                ],
            },
        }
        headers = self._get_headers(reseller.credentials, correlation_id=customer_id)
        response = requests.post(
            urljoin(self._config.api_base_url, "/v3/customers"),
            headers=headers,
            json=payload,
        )

        response.raise_for_status()

        created_customer = response.json()
        adobe_customer_id = created_customer["customerId"]
        logger.info(
            f"Customer {customer_id} - {customer_data['CompanyName']} "
            f"created successfully for reseller {reseller.id}: {adobe_customer_id}",
        )
        return adobe_customer_id

    @wrap_http_error
    def search_last_order_by_sku(
        self,
        reseller_country: str,
        customer_id: str,
        sku: str,
    ) -> dict | None:
        """
        Search for the last order placed by the customer identified by `customer_id`
        for a given adobe product `sku`.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer that placed the order.
            sku (str): The SKU of the product to search for.

        Returns:
            dict: The last order found for the given SKU or `None` if not found.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        product: AdobeProduct = self._config.get_adobe_product(sku)
        headers = self._get_headers(reseller.credentials)
        response = requests.get(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            params={
                "offer-id": product.sku,
                "order-type": "NEW",
                "status": STATUS_PROCESSED,
            },
        )

        response.raise_for_status()
        data = response.json()

        if data["count"] > 0:
            return data["items"][0]

    @wrap_http_error
    def search_last_return_order_by_order(
        self,
        reseller_country: str,
        customer_id: str,
        adobe_order_id: str,
    ) -> dict | None:
        """
        Search for an order of type RETURN by the identified of the returned order.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer that placed the order.
            adobe_order_id (str): Identifier of the order that should have been returned.

        Returns:
            dict: The RETURN order or `None` if not found.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        headers = self._get_headers(reseller.credentials)
        response = requests.get(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            params={
                "reference-order-id": adobe_order_id,
                "order-type": "RETURN",
                "status": (STATUS_PROCESSED, STATUS_PENDING),
            },
        )

        response.raise_for_status()
        data = response.json()

        if data["count"] > 0:
            return data["items"][0]

    @wrap_http_error
    def create_return_order(
        self,
        reseller_country: str,
        customer_id: str,
        returning_order_id: str,
        order: dict,
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
            returning_order_id (str): Identifier of the purchase order that must be
            returned.
            order (dict): The change order of the Marketplace platform that contains
            the item that must be returned.
            returning_item (dict): The item of the order of the Marketplace platform
            that must be returned.

        Returns:
            dict: The RETURN order.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        product: AdobeProduct = self._config.get_adobe_product(returning_item["productItemId"])
        payload = {
            "externalReferenceId": order["id"],
            "referenceOrderId": returning_order_id,
            "currencyCode": "USD",  # TODO get the currency from the line item
            "orderType": ORDER_TYPE_RETURN,
            "lineItems": [],
        }

        payload["lineItems"].append(
            {
                "extLineItemNumber": returning_item["lineNumber"],
                "offerId": product.sku,
                "quantity": returning_item["oldQuantity"],
            },
        )

        headers = self._get_headers(reseller.credentials, correlation_id=f"{order['id']}-ret")
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
        order: dict,
    ) -> dict:
        """
        Creates an order of type PREVIEW for a given Marketplace platform order.
        Creating a PREVIEW order allows to validate the order items and eventually
        obtaining from Adobe replacement SKUs to get the best discount level
        the customer is elegible for.
        The `reseller_country` is used to select the reseller and the Adobe credentials
        of the account to which the reseller belong to.

        Args:
            reseller_country (str): The country of the reseller to which the customer account
            belongs to.
            customer_id (str): Identifier of the customer that place the PREVIEW order.
            order (dict): The order of the Marketplace platform for which the PREVIEW
            order must be created.

        Returns:
            dict: The PREVIEW order.
        """
        reseller: Reseller = self._config.get_reseller(reseller_country)
        payload = {
            "externalReferenceId": order["id"],
            "currencyCode": "USD",  # TODO get the currency from the line item
            "orderType": ORDER_TYPE_PREVIEW,
            "lineItems": [],
        }

        for item in order["items"]:
            product: AdobeProduct = self._config.get_adobe_product(item["productItemId"])
            payload["lineItems"].append(
                {
                    "extLineItemNumber": item["lineNumber"],
                    "offerId": product.sku,
                    "quantity": item["quantity"],
                }
            )

        headers = self._get_headers(reseller.credentials)
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
            "currencyCode": "USD",  # TODO get the currency from the line item
            "orderType": ORDER_TYPE_NEW,
            "lineItems": adobe_preview_order["lineItems"],
        }

        headers = self._get_headers(
            reseller.credentials,
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
        headers = self._get_headers(reseller.credentials)
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
        headers = self._get_headers(reseller.credentials)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/subscriptions/{subscription_id}",
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
                expires=(datetime.now() + timedelta(seconds=token_info["expires_in"] - 180)),
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
