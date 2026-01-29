from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import wrap_http_error
from adobe_vipm.flows.constants import Param
from adobe_vipm.utils import get_partial_sku


class SubscriptionClientMixin:
    """Adobe Client Mixin to manage Subscription flows of Adobe VIPM."""

    @wrap_http_error
    def get_subscription(
        self, authorization_id: str, customer_id: str, subscription_id: str
    ) -> dict:
        """
        Retrieve a subscription by its identifier.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer to which the subscriptions belong to.
            subscription_id: List of base parts of whole Adobe Offer Ids

        Returns:
           The retrieved subscriptions.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/subscriptions/{subscription_id}",
            ),
            headers=headers,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def get_subscriptions(self, authorization_id: str, customer_id: str) -> dict:
        """
        Retrieve all the subscriptions of the given customer.

        Args:
            authorization_id: ID of the authorization to use.
            customer_id: Identifier of the customer to which the subscriptions belong to.

        Returns:
            The retrieved subscriptions.
        """
        authorization = self._config.get_authorization(authorization_id)
        response = requests.get(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}/subscriptions"),
            headers=self._get_headers(authorization),
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    # TODO: Merge this method with get_subscriptions in a separate PR. Created to prevent
    # breaking existing code.
    @wrap_http_error
    def get_subscriptions_by_deployment(
        self, authorization_id: str, customer_id: str, deployment_id: str | None = None
    ):
        """Retrieve all the subscriptions of the given customer and deployment ID.

        Args:
            authorization_id: ID of the authorization to use.
            customer_id: Identifier of the customer to which the subscriptions belong to.
            deployment_id: Identifier of the deployment to which the subscriptions belong to.

        Returns:
            The retrieved subscriptions.
        """
        subscriptions = self.get_subscriptions(
            authorization_id=authorization_id, customer_id=customer_id
        )
        filtered_items = [
            sub for sub in subscriptions["items"] if sub.get(Param.DEPLOYMENT_ID) == deployment_id
        ]
        return {
            "items": filtered_items,
            "links": subscriptions["links"],
            "totalCount": len(filtered_items),
        }

    @wrap_http_error
    def get_subscriptions_for_offers(
        self,
        authorization_id: str,
        customer_id: str,
        base_offer_ids: list[str],
        deployment_id: str | None = None,
    ) -> list[dict]:
        """
        Retrieve all the subscriptions of the given offer ids.

        !!! Returns only active subscriptions

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer to which the subscriptions belongs to.
            base_offer_ids: List of base parts of whole Adobe Offer Ids
            deployment_id: Identifier of the deployment to which the subscriptions belong to.

        Returns:
            The retrieved subscriptions.
        """
        subscriptions = self.get_subscriptions_by_deployment(
            authorization_id, customer_id, deployment_id
        )["items"]
        active_subscriptions = filter(
            lambda sub: sub["status"] == AdobeStatus.PROCESSED,
            subscriptions,
        )

        return list(
            filter(
                lambda sub: get_partial_sku(sub["offerId"]) in base_offer_ids,
                active_subscriptions,
            )
        )

    @wrap_http_error
    def update_subscription(
        self,
        authorization_id: str,
        customer_id: str,
        subscription_id: str,
        auto_renewal: bool = True,  # noqa: FBT001 FBT002
        quantity: int | None = None,
    ) -> dict:
        """
        Update a subscription.

        Either to reduce the quantity on the anniversary date either to switch auto renewal off.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer to which the subscription belongs to.
            subscription_id: Identifier of the subscription that must be retrieved.
            auto_renewal: Set if the subscription must be auto renewed on the anniversary
            date or not. Default to True.
            quantity: The quantity of licenses that must be renewed on the anniversary date.
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
            payload["autoRenewal"][Param.RENEWAL_QUANTITY.value] = quantity

        response = requests.patch(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/subscriptions/{subscription_id}",
            ),
            headers=headers,
            json=payload,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        # patch doesn't return half of the fields in subscriptions representation
        # missed fields are offerId, usedQuantity
        return self.get_subscription(authorization_id, customer_id, subscription_id)
