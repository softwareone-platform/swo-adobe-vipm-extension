from urllib.parse import urljoin
from auth0.authentication import GetToken

from requests import Session
from requests.adapters import HTTPAdapter, Retry


class MPTClient(Session):
    def __init__(self, base_url, login_domain, auth0_client_id, username, passwd):
        super().__init__()
        retries = Retry(
            total=5,
            backoff_factor=0.1,
            status_forcelist=[500, 502, 503, 504],
        )
        self.mount("http://", HTTPAdapter(max_retries=retries))
        self.headers.update(
            {"User-Agent": "swo-extensions/1.0"}
        )
        self.base_url = f"{base_url}/" if base_url[-1] != "/" else base_url
        self.token = GetToken(login_domain, auth0_client_id)
        self.username = username
        self.passwd = passwd
        self._api_token = None

    def authorize(self):
        token_response = self.token.login(
            username=self.username, password=self.passwd, realm='Username-Password-Authentication', grant_type='password'
        )

        self._api_token = f"{token_response['token_type']} {token_response['access_token']}"
        self.headers.update({
            "Authorization": self._api_token,
        })

    def request(self, method, url, *args, **kwargs):
        if self._api_token is None:
            self.authorize()

        url = self.join_url(url)
        response = super().request(method, url, *args, **kwargs)

        if response.status_code == 401:
            self.authorize()
            response = super().request(method, url, *args, **kwargs)

        return response

    def prepare_request(self, request, *args, **kwargs):
        request.url = self.join_url(request.url)
        return super().prepare_request(request, *args, **kwargs)

    def join_url(self, url):
        url = url[1:] if url[0] == "/" else url
        return urljoin(self.base_url, url)
