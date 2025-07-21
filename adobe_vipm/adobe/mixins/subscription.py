from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import wrap_http_error
from adobe_vipm.utils import get_partial_sku


class SubscriptionClientMixin:
    @wrap_http_error
    def get_subscription(
        self,
        authorization_id: str,
        customer_id: str,
        subscription_id: str,
    ) -> dict:
        """
        Retrieve a subscription by its identifier.
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
        Retrieve all the subscriptions of the given customer.
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
    def get_subscriptions_for_offers(
        self,
        authorization_id: str,
        customer_id: str,
        base_offer_ids: list[str],
    ) -> list[dict]:
        """
        Retrieve all the subscriptions of the given offer ids.
        !!! Returns only active subscriptions

        Args:
            authorization_id (str): Id of the authorization to use.
            customer_id (str): Identifier of the customer to which the subscriptions belongs to.
            base_offer_ids: (list[str]): List of base parts of whole Adobe Offer Ids

        Returns:
            dict: The retrieved subscriptions.
        """
        subscriptions = self.get_subscriptions(authorization_id, customer_id)["items"]
        active_subscriptions = filter(lambda s: s["status"] == AdobeStatus.PROCESSED, subscriptions)

        return list(
            filter(
                lambda s: get_partial_sku(s["offerId"]) in base_offer_ids,
                active_subscriptions,
            )
        )

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
        # patch doesn't return half of the fields in subscriptions representaion
        # missed fields are offerId, usedQuantity
        return self.get_subscription(authorization_id, customer_id, subscription_id)
