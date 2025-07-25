import json
from hashlib import sha256
from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.errors import wrap_http_error
from adobe_vipm.adobe.utils import join_phone_number


class ResellerClientMixin:
    """Adobe Client Mixin to manage Resellers flows of Adobe VIPM."""

    @wrap_http_error
    def create_reseller_account(
        self,
        authorization_id: str,
        reseller_id: str,
        reseller_data: dict,
    ) -> str:
        """

        Create Reseller Account on Adobe.

        Args:
            authorization_id: Id of the authorization to use.
            reseller_id: Identifier of the customer to which the subscriptions belongs to.
            reseller_data: reseller data, including address, contact, companyName

        Returns:
            str: Reseller ID.
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
                "address": self._get_address(reseller_data["address"], reseller_data["contact"]),
                "contacts": [self._get_contact(reseller_data["contact"])],
            },
        }
        response = requests.post(
            urljoin(self._config.api_base_url, "/v3/resellers"),
            headers=self._get_headers(
                authorization,
                correlation_id=sha256(json.dumps(payload).encode()).hexdigest(),
            ),
            json=payload,
            timeout=self._TIMEOUT,
        )

        response.raise_for_status()

        created_reseller = response.json()
        adobe_reseller_id = created_reseller["resellerId"]
        self._logger.info(
            "Reseller %s - %s created successfully under authorization %s (%s): %s",
            reseller_id,
            reseller_data["companyName"],
            authorization.name,
            authorization.authorization_uk,
            adobe_reseller_id,
        )
        return adobe_reseller_id

    def _get_address(self, address: dict, contact: dict) -> dict:
        return {
            "country": address["country"],
            "region": address["state"],
            "city": address["city"],
            "addressLine1": address["addressLine1"],
            "addressLine2": address["addressLine2"],
            "postalCode": address["postCode"],
            "phoneNumber": join_phone_number(contact["phone"]),
        }

    def _get_contact(self, contact: dict) -> dict:
        return {
            "firstName": contact["firstName"],
            "lastName": contact["lastName"],
            "email": contact["email"],
            "phoneNumber": join_phone_number(contact["phone"]),
        }
