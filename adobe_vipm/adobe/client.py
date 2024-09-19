import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from hashlib import sha256
from typing import MutableMapping
from urllib.parse import urljoin
from uuid import uuid4

import requests

from adobe_vipm.adobe.config import Config, get_config
from adobe_vipm.adobe.constants import (
    CANCELLATION_WINDOW_DAYS,
    OFFER_TYPE_CONSUMABLES,
    OFFER_TYPE_LICENSE,
    ORDER_TYPE_NEW,
    ORDER_TYPE_PREVIEW,
    ORDER_TYPE_PREVIEW_RENEWAL,
    ORDER_TYPE_RENEWAL,
    ORDER_TYPE_RETURN,
    STATUS_PENDING,
    STATUS_PROCESSED,
)
from adobe_vipm.adobe.dataclasses import (
    AdobeProduct,
    APIToken,
    Authorization,
    Reseller,
    ReturnableOrderInfo,
)
from adobe_vipm.adobe.errors import wrap_http_error
from adobe_vipm.adobe.utils import (
    get_item_by_partial_sku,
    join_phone_number,
    to_adobe_line_id,
)
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


class AdobeClient:
    def __init__(self) -> None:
        self._config: Config = get_config()
        self._token_cache: MutableMapping[Authorization, APIToken] = {}

    @wrap_http_error
    def create_reseller_account(
        self,
        authorization_id: str,
        reseller_id: str,
        reseller_data: dict,
    ) -> str:
        """
        Creates a reseller account under the distributor identified by `authorization`.

        Args:
            authorization_id (str): Identifier of the Authorization to which the distributor account
            is bounded to and into which the reseller must be created.
            reseller_id (str): Identifier of the reseller in the Marketplace platform.
            reseller_data (dict): Data of the reseller to create.

        Returns:
            str: The identifier of the reseller in the Adobe VIP Markerplace.
        """
        authorization = self._config.get_authorization(authorization_id)
        payload = {
            "externalReferenceId": reseller_id,
            "distributorId": authorization.distributor_id,
            "companyProfile": {
                "companyName": reseller_data["companyName"],
                "preferredLanguage": self._config.get_preferred_language(
                    reseller_data["address"]["country"]
                ),
                "address": {
                    "country": reseller_data["address"]["country"],
                    "region": reseller_data["address"]["state"],
                    "city": reseller_data["address"]["city"],
                    "addressLine1": reseller_data["address"]["addressLine1"],
                    "addressLine2": reseller_data["address"]["addressLine2"],
                    "postalCode": reseller_data["address"]["postCode"],
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
        correlation_id = sha256(json.dumps(payload).encode()).hexdigest()
        headers = self._get_headers(authorization, correlation_id=correlation_id)
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
            "created successfully under authorization "
            f"{authorization.name} ({authorization.authorization_uk}): {adobe_reseller_id}",
        )
        return adobe_reseller_id

    @wrap_http_error
    def create_customer_account(
        self,
        authorization_id: str,
        seller_id: str,
        agreement_id: str,
        market_segment: str,
        customer_data: dict,
    ) -> dict:
        """
        Creates a customer account under the reseller identified by `seller_id`.

        Args:
            authorization_id (str): Id of the authorization to use.
            seller_id (str): Id of the seller to use.
            agreement_id (str): id of the Marketplace platform agreement for this customer.
            market_segment (str): COM, EDU, GOV.
            customer_data (dict): Data of the customer to create.

        Returns:
            dict: The customer object created in the Adobe VIP Markerplace.
        """
        authorization = self._config.get_authorization(authorization_id)
        reseller: Reseller = self._config.get_reseller(authorization, seller_id)
        company_name: str = f"{customer_data['companyName']} ({agreement_id})"
        country = self._config.get_country(customer_data["address"]["country"])
        state_or_province = customer_data["address"]["state"]
        state_code = (
            state_or_province
            if not country.provinces_to_code
            else country.provinces_to_code.get(state_or_province, state_or_province)
        )
        payload = {
            "resellerId": reseller.id,
            "externalReferenceId": agreement_id,
            "companyProfile": {
                "companyName": company_name,
                "preferredLanguage": self._config.get_preferred_language(
                    customer_data["address"]["country"],
                ),
                "marketSegment": market_segment,
                "address": {
                    "country": customer_data["address"]["country"],
                    "region": state_code,
                    "city": customer_data["address"]["city"],
                    "addressLine1": customer_data["address"]["addressLine1"],
                    "addressLine2": customer_data["address"]["addressLine2"],
                    "postalCode": customer_data["address"]["postCode"],
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
                    },
                ],
            },
        }
        if customer_data["3YC"] == ["Yes"]:
            quantities = []
            if customer_data["3YCLicenses"]:
                quantities.append(
                    {
                        "offerType": OFFER_TYPE_LICENSE,
                        "quantity": int(customer_data["3YCLicenses"]),
                    },
                )
            if customer_data["3YCConsumables"]:
                quantities.append(
                    {
                        "offerType": OFFER_TYPE_CONSUMABLES,
                        "quantity": int(customer_data["3YCConsumables"]),
                    },
                )
            payload["benefits"] = [
                {
                    "type": "THREE_YEAR_COMMIT",
                    "commitmentRequest": {
                        "minimumQuantities": quantities,
                    },
                },
            ]

        correlation_id = sha256(json.dumps(payload).encode()).hexdigest()
        headers = self._get_headers(authorization, correlation_id=correlation_id)
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
        return created_customer

    def get_returnable_orders_by_sku(
        self,
        authorization_id: str,
        customer_id: str,
        sku: str,
        customer_coterm_date: str,
        return_orders: list | None = None,
    ):
        start_date = date.today() - timedelta(days=CANCELLATION_WINDOW_DAYS)

        filters = {
            "order-type": [ORDER_TYPE_NEW, ORDER_TYPE_RENEWAL],
            "start-date": start_date.isoformat(),
            "end-date": (
                date.fromisoformat(customer_coterm_date) - timedelta(days=15)
            ).isoformat()

        }

        returning_order_ids = [
            order["referenceOrderId"] for order in (return_orders or [])
        ]

        orders = self.get_orders(
            authorization_id,
            customer_id,
            filters=filters,
        )

        result = []
        for order in orders:
            item = get_item_by_partial_sku(order["lineItems"], sku)
            if not item:
                continue
            if (
                order["orderId"] in returning_order_ids
                or (
                    order["status"] == STATUS_PROCESSED and
                    item["status"] == STATUS_PROCESSED
                )
            ):
                result.append(
                    ReturnableOrderInfo(
                        order=order,
                        line=item,
                        quantity=item["quantity"],
                    )
                )

        return result

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
    def create_return_order(
        self,
        authorization_id: str,
        customer_id: str,
        returning_order: dict,
        returning_item: dict,
        external_reference: str,
    ) -> dict:
        """
        Creates an order of type RETURN for a given `item` that was purchased in the
        order identified by `returning_order_id`.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer that place the RETURN order.
            returning_order (dict): The order that contains the item to return.
            returning_item (dict): The item that must be returned.

        Returns:
            dict: The RETURN order.
        """
        authorization = self._config.get_authorization(authorization_id)
        line_number = returning_item["extLineItemNumber"]
        quantity = returning_item["quantity"]
        sku = returning_item["offerId"]
        external_id = f"{external_reference}_{returning_order['externalReferenceId']}_{line_number}"
        payload = {
            "externalReferenceId": external_id,
            "referenceOrderId": returning_order["orderId"],
            "currencyCode": authorization.currency,
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
            authorization,
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
        authorization_id: str,
        customer_id: str,
        order_id: str,
        lines: list,
    ) -> dict:
        """
        Creates an order of type PREVIEW for a given Marketplace platform order.
        Creating a PREVIEW order allows to validate the order lines and eventually
        obtaining from Adobe replacement SKUs to get the best discount level
        the customer is elegible for.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer that place the PREVIEW order.
            order_id: The identifier of the Marketplace platform order for which the PREVIEW
            order must be created.
            lines (list): The list of order lines for which creating the preview order.

        Returns:
            dict: The PREVIEW order.
        """
        authorization = self._config.get_authorization(authorization_id)
        payload = {
            "externalReferenceId": order_id,
            "currencyCode": authorization.currency,
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

        headers = self._get_headers(authorization)
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
        authorization_id: str,
        customer_id: str,
        adobe_preview_order: dict,
    ) -> dict:
        """
        Creates an order of type NEW (the actual order) for a given Marketplace platform order.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer that place the NEW order.
            adobe_preview_order (dict): The Adobe PREVIEW order that must be created.

        Returns:
            dict: The NEW order.
        """
        authorization = self._config.get_authorization(authorization_id)
        payload = {
            "externalReferenceId": adobe_preview_order["externalReferenceId"],
            "currencyCode": authorization.currency,
            "orderType": ORDER_TYPE_NEW,
            "lineItems": adobe_preview_order["lineItems"],
        }

        headers = self._get_headers(
            authorization,
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
        authorization_id: str,
        customer_id: str,
    ) -> dict:
        """
        Creates a preview of the renewal for a given customer.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer account.

        Returns:
            dict: a preview of the renewal.
        """
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

    @wrap_http_error
    def get_order(
        self,
        authorization_id: str,
        customer_id: str,
        order_id: str,
    ) -> dict:
        """
        Retrieves an order of a given customer by its identifier.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer that placed the order.
            order_id (str): Identifier of the order that must be retrieved.

        Returns:
            dict: The retrieved order.
        """
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
    def get_subscription(
        self,
        authorization_id: str,
        customer_id: str,
        subscription_id: str,
    ) -> dict:
        """
        Retrieve a subscription by its identifier.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer to which the subscription belongs to.
            subscription_id (str): Identifier of the subscription that must be retrieved.

        Returns:
            str: The retrieved subscription.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
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
    def get_subscriptions(
        self,
        authorization_id: str,
        customer_id: str,
    ) -> dict:
        """
        Retrieve all the subscriptions of the given custome.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer to which the subscriptions belongs to.

        Returns:
            dict: The retrieved subscriptions.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/subscriptions",
            ),
            headers=headers,
        )

        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def update_subscription(
        self,
        authorization_id: str,
        customer_id: str,
        subscription_id: str,
        auto_renewal: bool = True,
        quantity: int | None = None,
    ) -> dict:
        """
        Update a subscription either to reduce the quantity on the anniversary date either
        to switch auto renewal off.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer to which the subscription belongs to.
            subscription_id (str): Identifier of the subscription that must be retrieved.
            auto_renewal (boolean): Set if the subscription must be auto renewed on the anniversary
            date or not. Default to True.
            quantity (int): The quantity of licenses that must be renewed on the anniversary date.
            Default to None mean to leave it unchanged.

        Returns:
            dict: The updated subscription.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        payload = {
            "autoRenewal": {
                "enabled": auto_renewal,
            },
        }
        if quantity:
            payload["autoRenewal"]["renewalQuantity"] = quantity

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
        authorization_id: str,
        membership_id: str,
    ):
        """
        Retrieves the subscriptions owned by a given membership identifier of the
        Adobe VIP program that will be transferred to the Adobe VIP Marketplace program.

        Args:
            authorization_id (str): Id of the authorization to use.
            membership_id (str): The membership identifier.

        Returns:
            dict: a transfer preview object.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/memberships/{membership_id}/offers",
            ),
            headers=headers,
            params={
                "ignore-order-return": "true",
                "expire-open-pas": "true",
            },
        )

        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_transfer(
        self,
        authorization_id: str,
        seller_id: str,
        order_id: str,
        membership_id: str,
    ) -> dict:
        """
        Creates a transfer order to move the subscriptions owned by a given
        membership identifier from the Adobe VIP program to the Adobe VIP Marketplace
        program.

        Args:
            authorization_id (str): Id of the authorization to use.
            seller_id (str): Id of the seller under which transfer the membership.
            order_id (str): Identifier of the MPT transfer order
            membership_id (str): The membership identifier.

        Returns:
            dict: a transfer object.
        """
        authorization = self._config.get_authorization(authorization_id)
        reseller: Reseller = self._config.get_reseller(authorization, seller_id)
        headers = self._get_headers(authorization, correlation_id=order_id)
        response = requests.post(
            urljoin(
                self._config.api_base_url,
                f"/v3/memberships/{membership_id}/transfers",
            ),
            headers=headers,
            params={
                "ignore-order-return": "true",
                "expire-open-pas": "true",
            },
            json={
                "resellerId": reseller.id,
            },
        )

        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def get_transfer(
        self,
        authorization_id: str,
        membership_id: str,
        transfer_id: str,
    ) -> dict:
        """
        Retrieve a transfer object by the membership and transfer identifiers.

        Args:
            authorization_id (str): Id of the authorization to use.
            membership_id (str): The membership identifier.
            transfer_id (str): The transfer identifier.

        Returns:
            dict: A transfer object.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/memberships/{membership_id}/transfers/{transfer_id}",
            ),
            headers=headers,
        )

        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def get_customer(
        self,
        authorization_id: str,
        customer_id: str,
    ) -> dict:
        """
        Retrieve a customer object by the customer identifier.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): The customer identifier.

        Returns:
            dict: A customer object.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}",
            ),
            headers=headers,
        )

        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_3yc_request(
        self,
        authorization_id: str,
        customer_id: str,
        commitment_request: dict,
        is_recommitment: bool = False,
    ) -> dict:
        """
        Creates a commitment or recommitment request for a given customer.

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str):Id of the customer for which submit the request.
            commitment_request (dict): data to fill the request object (minimum number or
            licenses and/or consumables)
            is_recommitment (bool, optional): if True creates a recommitment request. Default
            to False.

        Returns:
            dict: the customer object containting the request.
        """
        authorization = self._config.get_authorization(authorization_id)

        customer = self.get_customer(authorization_id, customer_id)

        request_type = (
            "commitmentRequest" if not is_recommitment else "recommitmentRequest"
        )

        quantities = []
        if commitment_request["3YCLicenses"]:
            quantities.append(
                {
                    "offerType": "LICENSE",
                    "quantity": int(commitment_request["3YCLicenses"]),
                },
            )
        if commitment_request["3YCConsumables"]:
            quantities.append(
                {
                    "offerType": "CONSUMABLES",
                    "quantity": int(commitment_request["3YCConsumables"]),
                },
            )
        payload = {
            "companyProfile": customer["companyProfile"],
            "benefits": [
                {
                    "type": "THREE_YEAR_COMMIT",
                    request_type: {
                        "minimumQuantities": quantities,
                    },
                },
            ],
        }

        correlation_id = sha256(json.dumps(payload).encode()).hexdigest()
        headers = self._get_headers(authorization, correlation_id=correlation_id)
        response = requests.patch(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}"),
            headers=headers,
            json=payload,
        )

        response.raise_for_status()

        updated_customer = response.json()
        return updated_customer

    def _get_headers(self, authorization: Authorization, correlation_id=None):
        return {
            "X-Api-Key": authorization.client_id,
            "Authorization": f"Bearer {self._get_auth_token(authorization).token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid4()),
            "x-correlation-id": correlation_id or str(uuid4()),
        }

    def _refresh_auth_token(self, authorization: Authorization):
        """
        Request an authentication token for the Adobe VIPM API
        using the credentials associated to a given the reseller.
        """

        data = {
            "grant_type": "client_credentials",
            "client_id": authorization.client_id,
            "client_secret": authorization.client_secret,
            "scope": self._config.api_scopes,
        }
        response = requests.post(
            url=self._config.auth_endpoint_url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=data,
        )
        if response.status_code == 200:
            token_info = response.json()
            self._token_cache[authorization] = APIToken(
                token=token_info["access_token"],
                expires=(
                    datetime.now() + timedelta(seconds=token_info["expires_in"] - 180)
                ),
            )
        response.raise_for_status()

    def _get_auth_token(self, authorization: Authorization):
        token: APIToken | None = self._token_cache.get(authorization)
        if not token or token.is_expired():
            self._refresh_auth_token(authorization)
        token = self._token_cache[authorization]
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
