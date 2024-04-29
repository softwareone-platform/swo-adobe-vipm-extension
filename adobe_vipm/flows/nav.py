import logging
from datetime import UTC, datetime
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def get_token():
    payload = {
        "client_id": settings.EXTENSION_CONFIG["NAV_AUTH_CLIENT_ID"],
        "client_secret": settings.EXTENSION_CONFIG["NAV_AUTH_CLIENT_SECRET"],
        "audience": settings.EXTENSION_CONFIG["NAV_AUTH_AUDIENCE"],
        "grant_type": "client_credentials"
    }

    resp = requests.post(
        settings.EXTENSION_CONFIG["NAV_AUTH_ENDPOINT_URL"],
        data=payload,
    )
    if resp.status_code == 200:
        return True, resp.json()["access_token"]

    return False, f"{resp.status_code} - {resp.content.decode()}"


def terminate_contract(cco):
    ok, response = get_token()
    if not ok:
        return ok, response

    base_url = settings.EXTENSION_CONFIG["NAV_API_BASE_URL"]

    resp = requests.patch(
        urljoin(
            base_url,
            f"/v1/contracts/terminate/{cco}"
        ),
        headers={
            "Authorization": f"Bearer {response}",
        },
        json={
            "terminationDate": datetime.now(UTC).isoformat(),
        },
    )

    return resp.status_code == 200, f"{resp.status_code} - {resp.content.decode()}"
