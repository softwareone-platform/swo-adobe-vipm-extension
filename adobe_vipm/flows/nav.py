import copy
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TOKEN_CACHE_FILE = os.path.join(
    os.path.expanduser("~"),
    ".nav-token-cache.json",
)


def get_token_from_disk():
    if not os.path.exists(TOKEN_CACHE_FILE):
        return

    token_data = json.load(open(TOKEN_CACHE_FILE))
    expires_at = datetime.fromisoformat(token_data["expires_at"])
    if expires_at < datetime.now(UTC):
        return

    return token_data["access_token"]


def save_token_to_disk(token_data):
    new_token_data = copy.copy(token_data)
    new_token_data["expires_at"] = (
        datetime.now(UTC) + timedelta(seconds=token_data["expires_in"] - 300)
    ).isoformat()
    with open(TOKEN_CACHE_FILE, "w") as f:
        f.write(json.dumps(new_token_data))


def get_token():
    cached_token = get_token_from_disk()
    if cached_token:
        return True, cached_token

    payload = {
        "client_id": settings.EXTENSION_CONFIG["NAV_AUTH_CLIENT_ID"],
        "client_secret": settings.EXTENSION_CONFIG["NAV_AUTH_CLIENT_SECRET"],
        "audience": settings.EXTENSION_CONFIG["NAV_AUTH_AUDIENCE"],
        "grant_type": "client_credentials",
    }

    resp = requests.post(
        settings.EXTENSION_CONFIG["NAV_AUTH_ENDPOINT_URL"],
        data=payload,
    )
    if resp.status_code == 200:
        token_data = resp.json()
        save_token_to_disk(token_data)
        return True, token_data["access_token"]

    return False, f"{resp.status_code} - {resp.content.decode()}"


def terminate_contract(cco):
    ok, response = get_token()
    if not ok:
        return ok, response

    base_url = settings.EXTENSION_CONFIG["NAV_API_BASE_URL"]

    resp = requests.post(
        urljoin(base_url, f"/v1.0/contracts/terminateNow/{cco}"),
        headers={
            "Authorization": f"Bearer {response}",
        },
    )
    if resp.status_code == 200:
        try:
            data = resp.json()
            if not data.get("contractInsert"):
                return False, f"{resp.status_code} - {resp.content.decode()}"
            contract_insert = data["contractInsert"]
            if contract_insert.get("contractNumber") and not contract_insert.get(
                "isPreferred", True
            ):
                return True, ""
        except requests.JSONDecodeError:
            pass

    return False, f"{resp.status_code} - {resp.content.decode()}"
