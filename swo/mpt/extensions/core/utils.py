from django.conf import settings

from swo.mpt.client import MPTClient

def setup_client():
    return MPTClient(
        f"{settings.MPT_API_BASE_URL}/v1/",
        settings.MPT_API_TOKEN,
    )
