import copy
import datetime as dt
import json
import logging
from pathlib import Path
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TOKEN_CACHE_FILE = Path.home() / ".nav-token-cache.json"


def get_token_from_disk() -> str | None:
    """Retrieves navision token from file."""
    token_file_path = Path(TOKEN_CACHE_FILE)
    if not token_file_path.is_file():
        return None

    token_data = json.load(token_file_path.open(encoding="utf-8"))
    expires_at = dt.datetime.fromisoformat(token_data["expires_at"]).replace(tzinfo=dt.UTC)
    if expires_at < dt.datetime.now(tz=dt.UTC):
        return None

    return token_data["access_token"]


def save_token_to_disk(token_data: dict) -> None:
    """
    Saves token to file cache.

    Args:
        token_data: Navision token data.
    """
    new_token_data = copy.copy(token_data)
    new_token_data["expires_at"] = (
        dt.datetime.now(tz=dt.UTC) + dt.timedelta(seconds=token_data["expires_in"] - 300)
    ).isoformat()

    with Path(TOKEN_CACHE_FILE).open("w", encoding="utf-8") as token_file:
        token_file.write(json.dumps(new_token_data))


def get_token() -> tuple[bool, str]:
    """
    Retrieves token from the API.

    Returns:
        Tuple with if token is cached and token itself
    """
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
        timeout=60,
    )
    if resp.status_code == 200:
        token_data = resp.json()
        save_token_to_disk(token_data)
        return True, token_data["access_token"]

    return False, f"{resp.status_code} - {resp.content.decode()}"


def terminate_contract(cco: str) -> tuple[bool, str]:
    """
    Terminates Navision contract with provided cco.

    Args:
        cco: CCO number.

    Returns:
        Tuple with was request succeed and response.
    """
    ok, response = get_token()
    if not ok:
        return ok, response

    base_url = settings.EXTENSION_CONFIG["NAV_API_BASE_URL"]

    resp = requests.post(
        urljoin(base_url, f"/v1.0/contracts/terminateNow/{cco}"),
        headers={
            "Authorization": f"Bearer {response}",
        },
        timeout=60,
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
