import json
from hashlib import sha256
from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.constants import OfferType
from adobe_vipm.adobe.dataclasses import Reseller
from adobe_vipm.adobe.errors import wrap_http_error
from adobe_vipm.adobe.utils import join_phone_number
from adobe_vipm.flows.constants import Param


class CustomerClientMixin:
    """Adobe Client Mixin to manage Customers flows of Adobe VIPM."""

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
        Create customer account.

        Args:
            authorization_id: Id of the authorization to use.
            seller_id: MPT Seller ID.
            agreement_id: MPT Agreement ID what belongs to customer
            market_segment: Adobe Customer segment
            customer_data: Customer data including companyName, address, contact, 3YCLicensees

        Returns:
            dict: Customer.
        """
        authorization = self._config.get_authorization(authorization_id)
        reseller: Reseller = self._config.get_reseller(authorization, seller_id)
        company_name: str = f"{customer_data['companyName']} ({agreement_id})"
        payload = {
            "resellerId": reseller.id,
            "externalReferenceId": agreement_id,
            "companyProfile": {
                "companyName": company_name,
                "preferredLanguage": self._config.get_preferred_language(
                    customer_data["address"]["country"],
                ),
                "marketSegment": market_segment,
                "address": self._get_address(customer_data["address"], customer_data["contact"]),
                "contacts": [self._get_contact(customer_data["contact"])],
            },
        }
        agency_type = customer_data.get(Param.AGENCY_TYPE.value)
        if agency_type:
            payload["companyProfile"]["marketSubSegments"] = [
                customer_data[Param.AGENCY_TYPE.value]
            ]
            payload["benefits"] = [{"type": "LARGE_GOVERNMENT_AGENCY"}]

        if customer_data["3YC"] == ["Yes"]:
            quantities = []
            if customer_data["3YCLicenses"]:
                quantities.append(
                    {
                        "offerType": OfferType.LICENSE,
                        "quantity": int(customer_data["3YCLicenses"]),
                    },
                )
            if customer_data["3YCConsumables"]:
                quantities.append(
                    {
                        "offerType": OfferType.CONSUMABLES,
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

        response = requests.post(
            urljoin(self._config.api_base_url, "/v3/customers"),
            headers=self._get_headers(
                authorization,
                correlation_id=sha256(json.dumps(payload).encode()).hexdigest(),
            ),
            json=payload,
            timeout=self._TIMEOUT,
        )

        response.raise_for_status()

        created_customer = response.json()
        self._logger.info(
            "Customer %s created successfully for reseller %s: %s",
            company_name,
            reseller.id,
            created_customer["customerId"],
        )
        return created_customer

    @wrap_http_error
    def get_customer(
        self,
        authorization_id: str,
        customer_id: str,
    ) -> dict:
        """
        Retrieve customer account.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Adobe customer ID.

        Returns:
            dict: Customer.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}",
            ),
            headers=headers,
            timeout=self._TIMEOUT,
        )

        response.raise_for_status()
        return response.json()

    @wrap_http_error
    def create_3yc_request(
        self,
        authorization_id: str,
        customer_id: str,
        commitment_request: dict,
        is_recommitment: bool = False,  # noqa: FBT001, FBT002
    ) -> dict:
        """
        Create 3YC request for account.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Adobe customer ID.
            commitment_request: commitment request info
            is_recommitment: is it recommitment or not

        Returns:
            dict: Customer.
        """
        request_type = "recommitmentRequest" if is_recommitment else "commitmentRequest"
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
            "companyProfile": self.get_customer(authorization_id, customer_id)["companyProfile"],
            "benefits": [
                {
                    "type": "THREE_YEAR_COMMIT",
                    request_type: {
                        "minimumQuantities": quantities,
                    },
                },
            ],
        }

        response = requests.patch(
            urljoin(self._config.api_base_url, f"/v3/customers/{customer_id}"),
            headers=self._get_headers(
                self._config.get_authorization(authorization_id),
                correlation_id=sha256(json.dumps(payload).encode()).hexdigest(),
            ),
            json=payload,
            timeout=self._TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def _get_contact(self, contact: dict) -> dict:
        return {
            "firstName": contact["firstName"],
            "lastName": contact["lastName"],
            "email": contact["email"],
            "phoneNumber": join_phone_number(contact["phone"]),
        }

    def _get_address(self, address: dict, contact: dict) -> dict:
        state_or_province = address["state"]
        country = self._config.get_country(address["country"])
        state_code = (
            country.provinces_to_code.get(state_or_province, state_or_province)
            if country.provinces_to_code
            else state_or_province
        )

        return {
            "country": address["country"],
            "region": state_code,
            "city": address["city"],
            "addressLine1": address["addressLine1"],
            "addressLine2": address["addressLine2"],
            "postalCode": address["postCode"],
            "phoneNumber": join_phone_number(contact["phone"]),
        }
