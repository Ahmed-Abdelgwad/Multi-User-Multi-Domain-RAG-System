from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from starlette.requests import Request
from starlette.responses import RedirectResponse


@dataclass(frozen=True)
class ExternalIdentity:
    subject: str
    email: str
    given_name: str | None = None
    family_name: str | None = None
    raw_claims: dict[str, Any] = field(default_factory=dict)


class AuthProvider(ABC):
    """Common interface for external identity providers (OIDC, SAML, ...).
    Each concrete provider is registered per user pool (internal/external) so
    'separate user pools' (spec 1.1) has a concrete mechanism at the SSO layer.
    """

    @abstractmethod
    async def get_authorization_url(self, request: Request, redirect_uri: str) -> RedirectResponse:
        ...

    @abstractmethod
    async def handle_callback(self, request: Request) -> ExternalIdentity:
        ...
