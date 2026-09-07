"""SAML is optional per spec 1.1. This is a disabled-by-default stub behind
`settings.saml_enabled`. If a customer's IdP requires SAML (e.g. legacy ADFS),
implement this with `python3-saml` (OneLogin toolkit): mature/spec-compliant,
but needs hand-maintained SP/IdP XML metadata and a native `xmlsec1`
dependency -- heavier ops than OIDC's JSON discovery, hence why it's optional
and not built out until an actual customer needs it.
"""
from starlette.requests import Request
from starlette.responses import RedirectResponse
from src.exceptions import SSOProviderNotConfiguredError
from .base import AuthProvider, ExternalIdentity


class SAMLProvider(AuthProvider):
    def __init__(self, pool: str):
        self.pool = pool

    async def get_authorization_url(self, request: Request, redirect_uri: str) -> RedirectResponse:
        raise SSOProviderNotConfiguredError(f"saml:{self.pool}")

    async def handle_callback(self, request: Request) -> ExternalIdentity:
        raise SSOProviderNotConfiguredError(f"saml:{self.pool}")
