from datetime import timedelta
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Request
from starlette import status
from . import models
from . import service
from .providers.oidc import OIDCProvider
from fastapi.security import OAuth2PasswordRequestForm
from ..database.core import DbSession
from ..rate_limiter import limiter
from ..config import get_settings
from ..entities.enums import UserType
from ..entities.user import User
from ..authz.dependencies import require_platform_admin

router = APIRouter(
    prefix='/auth',
    tags=['auth']
)

UserPool = Literal["internal", "external"]


@router.post("/", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
async def register_user(request: Request, db: DbSession,
                    register_user_request: models.RegisterUserRequest):
    service.register_user(db, register_user_request)


@router.post("/token", response_model=models.Token)
async def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
                                db: DbSession):
    return service.login_for_access_token(form_data, db)


@router.get("/sso/{pool}/login")
async def sso_login(pool: UserPool, request: Request):
    settings = get_settings()
    redirect_uri = f"{settings.sso_redirect_base_url}/auth/sso/{pool}/callback"
    return await OIDCProvider(pool).get_authorization_url(request, redirect_uri)


@router.get("/sso/{pool}/callback", response_model=models.Token)
async def sso_callback(pool: UserPool, request: Request, db: DbSession):
    identity = await OIDCProvider(pool).handle_callback(request)
    user_type = UserType.INTERNAL if pool == "internal" else UserType.EXTERNAL
    user = service.find_or_create_sso_user(db, user_type, identity)
    ttl = service.ttl_minutes_for_pool(db, user.user_type)
    token = service.create_access_token(user.email, user.id, timedelta(minutes=ttl))
    return models.Token(access_token=token, token_type='bearer')


@router.get("/session-policy/", response_model=models.SessionPolicyResponse)
def get_session_policy(db: DbSession, _admin: User = Depends(require_platform_admin)):
    return service.get_or_create_session_policy(db)


@router.put("/session-policy/", response_model=models.SessionPolicyResponse)
def update_session_policy(
    db: DbSession, update: models.SessionPolicyUpdate, admin: User = Depends(require_platform_admin)
):
    return service.update_session_policy(db, update, admin.id)



