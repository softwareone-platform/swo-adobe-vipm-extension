import json
from hashlib import sha256
from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.constants import OfferType
from adobe_vipm.adobe.dataclasses import Reseller
from adobe_vipm.adobe.errors import wrap_http_error
from adobe_vipm.adobe.utils import join_phone_number


class CustomerClientMixin:
    @wrap_http_error
    def create_customer_account(
        self,
        authorization_id: str,
        seller_id: str,
        agreement_id: str,
        market_segment: str,
        customer_data: dict,
    ) -> dict:
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
                        "phoneNumber": join_phone_number(customer_data["contact"]["phone"]),
                    },
                ],
            },
        }
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
        self._logger.info(
            f"Customer {company_name} "
            f"created successfully for reseller {reseller.id}: {adobe_customer_id}",
        )
        return created_customer

    @wrap_http_error
    def get_customer(
        self,
        authorization_id: str,
        customer_id: str,
    ) -> dict:
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
        authorization = self._config.get_authorization(authorization_id)
        customer = self.get_customer(authorization_id, customer_id)
        request_type = "commitmentRequest" if not is_recommitment else "recommitmentRequest"
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
