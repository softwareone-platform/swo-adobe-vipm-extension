import logging
from datetime import datetime, timedelta
from typing import Mapping
from urllib.parse import urljoin
from uuid import uuid4

import requests

from adobe_vipm.adobe.config import Config
from adobe_vipm.adobe.dataclasses import APIToken, Credentials, Reseller
from adobe_vipm.adobe.errors import AdobeError

logger = logging.getLogger(__name__)


class AdobeClient:
    def __init__(self):
        self._config: Config = Config()
        self._token_cache: Mapping[Credentials, APIToken] = {}

    def create_customer_account(self, reseller_country, external_id, customer_data):
        reseller: Reseller = self._config.get_reseller(reseller_country)
        payload = {
            "resellerId": reseller.id,
            "externalReferenceId": external_id,
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
        headers = self._get_headers(reseller.credentials)
        response = requests.post(
            urljoin(self._config.api_base_url, "/v3/customers"),
            headers=headers,
            json=payload,
        )

        if response.status_code == 201:
            created_customer = response.json()
            customer_id = created_customer["customerId"]
            logger.info(
                f"Customer {external_id} - {customer_data['CompanyName']} "
                f"created successfully for reseller {reseller.id}: {customer_id}",
            )
            return customer_id

        raise AdobeError(response.json())

    def create_preview_order(self, reseller_country, customer_id, order):
        reseller: Reseller = self._config.get_reseller(reseller_country)
        payload = {
            "externalReferenceId": order["id"],
            "currencyCode": "USD",
            "orderType": "PREVIEW",
            "lineItems": [],
        }
        for item in order["items"]:
            payload["lineItems"].append(
                {
                    "extLineItemNumber": item["lineNumber"],
                    "offerId": self._config.get_default_sku(item["productItemId"]),
                    "quantity": item["quantity"],
                }
            )
        headers = self._get_headers(reseller.credentials)
        response = requests.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
        )
        if response.status_code == 200:
            return response.json()

        raise AdobeError(response.json())

    def create_new_order(self, reseller_country, customer_id, payload):
        reseller: Reseller = self._config.get_reseller(reseller_country)
        payload["orderType"] = "NEW"
        headers = self._get_headers(reseller.credentials)
        response = requests.post(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/orders"),
            headers=headers,
            json=payload,
        )

        if response.status_code == 202:
            return response.json()

        raise AdobeError(response.json())

    def get_order(self, reseller_country, customer_id, order_id):
        reseller: Reseller = self._config.get_reseller(reseller_country)
        headers = self._get_headers(reseller.credentials)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/orders/{order_id}",
            ),
            headers=headers,
        )
        if response.status_code == 200:
            return response.json()

        raise AdobeError(response.json())

    def get_subscription(self, reseller_country, customer_id, subscription_id):
        reseller: Reseller = self._config.get_reseller(reseller_country)
        headers = self._get_headers(reseller.credentials)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/subscriptions/{subscription_id}",
            ),
            headers=headers,
        )
        if response.status_code == 200:
            return response.json()

        raise AdobeError(response.json())

    def _get_headers(self, credentials: Credentials):
        return {
            "X-Api-Key": credentials.client_id,
            "Authorization": f"Bearer {self._get_auth_token(credentials).token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid4()),
            "x-correlation-id": str(uuid4()),
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
        token: APIToken = self._token_cache.get(credentials)
        if not token or token.is_expired():
            self._refresh_auth_token(credentials)
        token = self._token_cache[credentials]
        return token


_ADOBE_CLIENT = None


def get_adobe_client():
    global _ADOBE_CLIENT
    if not _ADOBE_CLIENT:
        _ADOBE_CLIENT = AdobeClient()
    return _ADOBE_CLIENT
