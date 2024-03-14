from django.conf import settings
from swo.mpt.client import MPTClient

_CLIENT = None


class MPTClientMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        global _CLIENT
        if not _CLIENT:
            _CLIENT = MPTClient(
                f"{settings.MPT_API_BASE_URL}/v1/",
                settings.MPT_LOGIN_URL,
                settings.MPT_AUTH0_CLIENT_ID,
                settings.MPT_USERNAME,
                settings.MPT_API_TOKEN,  # w/a replace with MPT_PASSWORD later
            )
        request.client = _CLIENT
        response = self.get_response(request)
        return response
