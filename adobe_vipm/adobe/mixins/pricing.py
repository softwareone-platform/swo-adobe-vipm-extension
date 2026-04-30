from urllib.parse import urljoin

import requests

from adobe_vipm.adobe.dataclasses import Authorization, PriceListPayload
from adobe_vipm.adobe.errors import wrap_http_error


class PricingClientMixin:
    """Adobe Client Mixin to manage Pricing flows of Adobe VIPM."""

    @wrap_http_error
    def get_price_list(
        self,
        authorization: Authorization,
        payload: PriceListPayload,
        page_size: int = 100,
    ) -> dict:
        """Retrieve all offers from the price list, fetching all pages automatically."""
        all_offers = []
        total_count = None
        result = {}

        while total_count is None or len(all_offers) < total_count:
            response = requests.post(
                urljoin(self._config.api_base_url, "/v3/pricelist"),
                headers=self._get_headers(authorization),
                json=payload.to_dict(),
                params={"offset": len(all_offers), "limit": page_size},
                timeout=self._TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()
            all_offers.extend(result.get("offers", []))
            total_count = result["totalCount"]
            if result["count"] == 0:
                break

        result["offers"] = all_offers
        result.pop("count")
        result.pop("limit")
        result.pop("offset")

        return result
