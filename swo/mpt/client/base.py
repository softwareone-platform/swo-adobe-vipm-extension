from urllib.parse import urljoin, urlparse

from requests import Session
from requests.adapters import HTTPAdapter, Retry


class MPTClient(Session):
    def __init__(self, base_url, api_token):
        super().__init__()
        retries = Retry(
            total=5,
            backoff_factor=0.1,
            status_forcelist=[500, 502, 503, 504],
        )
        self.mount("http://", HTTPAdapter(max_retries=retries))
        self.headers.update(
            {
                "User-Agent": "swo-extensions/1.0",
                "Authorization": f"Bearer {api_token}",
            },
        )
        self.base_url = f"{base_url}/" if base_url[-1] != "/" else base_url
        self.api_token = api_token

    def request(self, method, url, *args, **kwargs):
        url = self.join_url(url)
        return super().request(method, url, *args, **kwargs)

    def prepare_request(self, request, *args, **kwargs):
        request.url = self.join_url(request.url)
        return super().prepare_request(request, *args, **kwargs)

    def join_url(self, url):
        url = url[1:] if url[0] == "/" else url
        return urljoin(self.base_url, url)
