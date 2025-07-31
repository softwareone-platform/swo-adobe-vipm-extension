from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.dataclasses import Reseller
from adobe_vipm.adobe.errors import wrap_http_error


class TransferClientMixin:
    """Adobe Client Mixin to manage Transfer flows of Adobe VIPM program."""

    @wrap_http_error
    def preview_transfer(
        self,
        authorization_id: str,
        membership_id: str,
    ) -> dict:
        """
        Retrieves the subscriptions owned by a given membership identifier of the Adobe VIP program.

        That will be transferred to the Adobe VIP Marketplace program.

        Args:
            authorization_id: Id of the authorization to use.
            membership_id: VIP membership ID

        Returns:
            dict: Preview transfer.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/memberships/{membership_id}/offers",
            ),
            headers=headers,
            params=self._do_not_make_return_params(),
            timeout=self._TIMEOUT,
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
        Creates a transfer order to move the subscriptions owned by a given membership.

        Identifier from the Adobe VIP program to the Adobe VIP Marketplace program.

        Args:
            authorization_id: Id of the authorization to use.
            seller_id: MPT Seller ID.
            order_id: MPT Order order ID
            membership_id: VIP Membership ID

        Returns:
            dict: The Transfer.
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
            params=self._do_not_make_return_params(),
            json={
                "resellerId": reseller.id,
            },
            timeout=self._TIMEOUT,
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
            authorization_id: Id of the authorization to use.
            membership_id: VIP Membership ID
            transfer_id: Adobe VIPM Transfer ID

        Returns:
            dict: The Transfer.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/memberships/{membership_id}/transfers/{transfer_id}",
            ),
            headers=headers,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def preview_reseller_change(
        self,
        authorization_id: str,
        seller_id: str,
        change_code: str,
        admin_email: str,
    ) -> dict:
        """
        Retrieves a transfer object by the membership and transfer identifiers.

        Args:
            authorization_id: Id of the authorization to use.
            seller_id: seller Id.
            change_code: Adobe Reseller change code.
            admin_email: Adobe admin email.

        Returns:
            dict: The Transfer.
        """
        authorization = self._config.get_authorization(authorization_id)
        reseller: Reseller = self._config.get_reseller(authorization, seller_id)
        headers = self._get_headers(authorization)
        response = requests.post(
            urljoin(
                self._config.api_base_url,
                "/v3/transfers",
            ),
            headers=headers,
            json={
                "type": "RESELLER_CHANGE",
                "action": "PREVIEW",
                "approvalCode": change_code,
                "resellerId": reseller.id,
                "requestedBy": admin_email,
            },
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def _do_not_make_return_params(self):
        return {
            "ignore-order-return": "true",
            "expire-open-pas": "true",
        }
