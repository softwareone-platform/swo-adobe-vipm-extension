from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.dataclasses import Reseller
from adobe_vipm.adobe.errors import wrap_http_error


class TransferClientMixin:
    @wrap_http_error
    def preview_transfer(
        self,
        authorization_id: str,
        membership_id: str,
    ):
        """
        Retrieves the subscriptions owned by a given membership identifier of the
        Adobe VIP program that will be transferred to the Adobe VIP Marketplace program.
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
