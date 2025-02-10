from django.conf import settings
from swo.mpt.client import MPTClient
from swo.mpt.extensions.core.utils import setup_client


def test_setup_client():
    client = setup_client()
    assert isinstance(client, MPTClient)
    assert client.base_url == f"{settings.MPT_API_BASE_URL}/v1/"
    assert client.api_token == settings.MPT_API_TOKEN
