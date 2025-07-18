from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import wrap_http_error


class DeploymentClientMixin:
    @wrap_http_error
    def get_customer_deployments(
        self,
        authorization_id: str,
        customer_id: str,
    ) -> dict:
        """
        Retrieve the customer deployment object.
        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/deployments?limit=100&offset=0",
            ),
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    def get_customer_deployments_active_status(
        self,
        authorization_id: str,
        customer_id: str,
    ) -> list[dict]:
        """
        Retrieve the active deployments for a given customer.
        """
        customer_deployments = self.get_customer_deployments(authorization_id, customer_id)

        active_deployments = []

        for customer_deployment in customer_deployments.get("items", []):
            if customer_deployment.get("status") == AdobeStatus.GC_DEPLOYMENT_ACTIVE:
                active_deployments.append(customer_deployment)

        return active_deployments
