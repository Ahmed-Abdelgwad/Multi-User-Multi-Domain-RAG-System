from datetime import timedelta, datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4
from fastapi import Depends
from passlib.context import CryptContext
import jwt
from jwt import PyJWTError
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from src.entities.user import User
from src.entities.session_policy import SessionPolicy
from src.entities.enums import UserType, AuthProviderType
from . import models
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from ..exceptions import AuthenticationError, SSOPoolMismatchError, UserAlreadyExistsError
from ..config import get_settings
from .providers.base import ExternalIdentity
import logging

settings = get_settings()
SECRET_KEY = settings.secret_key
ALGORITHM = settings.algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes

oauth2_bearer = OAuth2PasswordBearer(tokenUrl='auth/token')
bcrypt_context = CryptContext(schemes=['bcrypt'], deprecated='auto')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return bcrypt_context.hash(password)


def authenticate_user(email: str, password: str, db: Session) -> User | bool:
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        logging.warning(f"Failed authentication attempt for email: {email}")
        return False
    return user


def create_access_token(email: str, user_id: UUID, expires_delta: timedelta) -> str:
    encode = {
        'sub': email,
        'id': str(user_id),
        'exp': datetime.now(timezone.utc) + expires_delta
    }
    return jwt.encode(encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> models.TokenData:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get('id')
        return models.TokenData(user_id=user_id)
    except PyJWTError as e:
        logging.warning(f"Token verification failed: {str(e)}")
        raise AuthenticationError()


def register_user(db: Session, register_user_request: models.RegisterUserRequest) -> None:
    if db.query(User).filter(User.email == register_user_request.email).first():
        raise UserAlreadyExistsError(register_user_request.email)

    create_user_model = User(
        id=uuid4(),
        email=register_user_request.email,
        first_name=register_user_request.first_name,
        last_name=register_user_request.last_name,
        password_hash=get_password_hash(register_user_request.password),
        is_platform_admin=settings.is_platform_admin_email(register_user_request.email),
    )
    db.add(create_user_model)
    db.commit()
    logging.info(f"Registered new user: {register_user_request.email}")

    
def get_current_user(token: Annotated[str, Depends(oauth2_bearer)]) -> models.TokenData:
    return verify_token(token)

CurrentUser = Annotated[models.TokenData, Depends(get_current_user)]


def get_or_create_session_policy(db: Session) -> SessionPolicy:
    """Spec 1.1's "configurable session token TTL", one global singleton
    row (no domain_id, sessions aren't domain-scoped). Bootstrapped from
    ACCESS_TOKEN_EXPIRE_MINUTES for both pools the first time it's read,
    so nothing changes until a platform admin actually edits it.

    The query-then-insert below is still racy on its own (two concurrent
    first-ever calls can both see no row) -- SessionPolicy's `singleton`
    UNIQUE constraint is what actually prevents a second row; a lost race
    surfaces here as IntegrityError, and the loser just reads the row the
    winner committed instead of erroring out.
    """
    policy = db.query(SessionPolicy).first()
    if policy:
        return policy

    policy = SessionPolicy(
        id=uuid4(),
        internal_token_ttl_minutes=ACCESS_TOKEN_EXPIRE_MINUTES,
        external_token_ttl_minutes=ACCESS_TOKEN_EXPIRE_MINUTES,
    )
    db.add(policy)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.query(SessionPolicy).first()
    db.refresh(policy)
    return policy


def update_session_policy(db: Session, update: models.SessionPolicyUpdate, updated_by: UUID) -> SessionPolicy:
    policy = get_or_create_session_policy(db)
    policy.internal_token_ttl_minutes = update.internal_token_ttl_minutes
    policy.external_token_ttl_minutes = update.external_token_ttl_minutes
    policy.updated_by = updated_by
    policy.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(policy)
    logging.info(f"Session policy updated by {updated_by}: internal={policy.internal_token_ttl_minutes}m, external={policy.external_token_ttl_minutes}m")
    return policy


def ttl_minutes_for_pool(db: Session, user_type: UserType) -> int:
    policy = get_or_create_session_policy(db)
    return policy.internal_token_ttl_minutes if user_type == UserType.INTERNAL else policy.external_token_ttl_minutes


def login_for_access_token(form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
                                db: Session) -> models.Token:
    user = authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise AuthenticationError()
    ttl = ttl_minutes_for_pool(db, user.user_type)
    token = create_access_token(user.email, user.id, timedelta(minutes=ttl))
    return models.Token(access_token=token, token_type='bearer')


def find_or_create_sso_user(db: Session, pool: UserType, identity: ExternalIdentity) -> User:
    """JIT-provisions or matches an SSO-authenticated user by email. New SSO
    users get zero domain roles by default (least privilege) -- a Domain
    Admin must explicitly grant access. Raises SSOPoolMismatchError if an
    existing account with this email belongs to the other user pool.
    """
    user = db.query(User).filter(User.email == identity.email).first()
    if user is not None:
        if user.user_type != pool:
            logging.warning(f"SSO pool mismatch for email {identity.email}: expected {pool}, found {user.user_type}")
            raise SSOPoolMismatchError()
        if not user.external_id:
            user.external_id = identity.subject
            user.auth_provider = AuthProviderType.OIDC
            db.commit()
            db.refresh(user)
        return user

    user = User(
        id=uuid4(),
        email=identity.email,
        first_name=identity.given_name or "",
        last_name=identity.family_name or "",
        password_hash=None,
        user_type=pool,
        auth_provider=AuthProviderType.OIDC,
        external_id=identity.subject,
        is_platform_admin=settings.is_platform_admin_email(identity.email),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logging.info(f"JIT-provisioned SSO user {identity.email} in pool {pool}")
    return user
