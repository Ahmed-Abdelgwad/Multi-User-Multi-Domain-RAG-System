from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import RedirectResponse
from src.config import get_settings
from src.exceptions import SSOProviderNotConfiguredError
from .base import AuthProvider, ExternalIdentity

oauth = OAuth()

_POOL_SETTINGS = {
    "internal": lambda s: (s.oidc_internal_discovery_url, s.oidc_internal_client_id, s.oidc_internal_client_secret),
    "external": lambda s: (s.oidc_external_discovery_url, s.oidc_external_client_id, s.oidc_external_client_secret),
}


def _register_pool_clients() -> None:
    """Registers one Authlib OAuth client per user pool (internal/external),
    each pointed at its own OIDC discovery URL/credentials. A pool with no
    discovery URL configured is simply left unregistered (disabled).
    """
    settings = get_settings()
    for pool, extract in _POOL_SETTINGS.items():
        discovery_url, client_id, client_secret = extract(settings)
        if not discovery_url or getattr(oauth, pool, None):
            continue
        oauth.register(
            name=pool,
            server_metadata_url=discovery_url,
            client_id=client_id,
            client_secret=client_secret,
            client_kwargs={"scope": "openid email profile"},
        )


class OIDCProvider(AuthProvider):
    def __init__(self, pool: str):
        self.pool = pool

    def _client(self):
        _register_pool_clients()
        client = getattr(oauth, self.pool, None)
        if client is None:
            raise SSOProviderNotConfiguredError(self.pool)
        return client

    async def get_authorization_url(self, request: Request, redirect_uri: str) -> RedirectResponse:
        return await self._client().authorize_redirect(request, redirect_uri)

    async def handle_callback(self, request: Request) -> ExternalIdentity:
        client = self._client()
        token = await client.authorize_access_token(request)
        userinfo = token.get("userinfo")
        if userinfo is None:
            userinfo = await client.userinfo(token=token)
        return ExternalIdentity(
            subject=userinfo["sub"],
            email=userinfo["email"],
            given_name=userinfo.get("given_name"),
            family_name=userinfo.get("family_name"),
            raw_claims=dict(userinfo),
        )
