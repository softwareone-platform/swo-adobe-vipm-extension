import json
from hashlib import sha256
from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.errors import wrap_http_error
from adobe_vipm.adobe.utils import join_phone_number


class ResellerClientMixin:
    @wrap_http_error
    def create_reseller_account(
        self,
        authorization_id: str,
        reseller_id: str,
        reseller_data: dict,
    ) -> str:
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
                        "phoneNumber": join_phone_number(reseller_data["contact"]["phone"]),
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
        self._logger.info(
            f"Reseller {reseller_id} - {reseller_data['companyName']} "
            "created successfully under authorization "
            f"{authorization.name} ({authorization.authorization_uk}): {adobe_reseller_id}",
        )
        return adobe_reseller_id
