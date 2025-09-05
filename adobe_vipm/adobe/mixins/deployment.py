from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import wrap_http_error


class DeploymentClientMixin:
    """Adobe Client Mixin to manage Deployments flows of Adobe VIPM."""

    @wrap_http_error
    def get_customer_deployments(
        self,
        authorization_id: str,
        customer_id: str,
    ) -> dict:
        """
        Retrieve the customer deployment object.

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.

        Returns:
            dict: Deployments.

        """
        authorization = self._config.get_authorization(authorization_id)
        headers = self._get_headers(authorization)
        response = requests.get(
            urljoin(
                self._config.api_base_url,
                f"/v3/customers/{customer_id}/deployments?limit=100&offset=0",
            ),
            headers=headers,
            timeout=self._TIMEOUT,
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

        Args:
            authorization_id: Id of the authorization to use.
            customer_id: Identifier of the customer that place the RETURN order.

        Returns:
            list: Customer Deployments.
        """
        customer_deployments = self.get_customer_deployments(authorization_id, customer_id)

        return [
            deployment
            for deployment in customer_deployments.get("items", [])
            if deployment.get("status") == AdobeStatus.GC_DEPLOYMENT_ACTIVE
        ]
