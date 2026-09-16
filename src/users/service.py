from uuid import UUID
from sqlalchemy.orm import Session
from . import models
from src.entities.user import User
from src.entities.domain import Domain
from src.entities.user_domain_role import UserDomainRole
from src.exceptions import (
    UserNotFoundError, InvalidPasswordError, PasswordMismatchError, CannotModifyOwnPlatformAdminStatusError,
)
from src.auth.service import verify_password, get_password_hash
import logging


def get_user_by_id(db: Session, user_id: UUID) -> models.UserResponse:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logging.warning(f"User not found with ID: {user_id}")
        raise UserNotFoundError(user_id)
    logging.info(f"Successfully retrieved user with ID: {user_id}")
    return user


def change_password(db: Session, user_id: UUID, password_change: models.PasswordChange) -> None:
    try:
        user = get_user_by_id(db, user_id)
        
        # Verify current password
        if not verify_password(password_change.current_password, user.password_hash):
            logging.warning(f"Invalid current password provided for user ID: {user_id}")
            raise InvalidPasswordError()
        
        # Verify new passwords match
        if password_change.new_password != password_change.new_password_confirm:
            logging.warning(f"Password mismatch during change attempt for user ID: {user_id}")
            raise PasswordMismatchError()
        
        # Update password
        user.password_hash = get_password_hash(password_change.new_password)
        db.commit()
        logging.info(f"Successfully changed password for user ID: {user_id}")
    except Exception as e:
        logging.error(f"Error during password change for user ID: {user_id}. Error: {str(e)}")
        raise


def get_user_domains(db: Session, user_id: UUID) -> list[models.UserDomainMembership]:
    rows = (
        db.query(UserDomainRole, Domain)
        .join(Domain, Domain.id == UserDomainRole.domain_id)
        .filter(UserDomainRole.user_id == user_id)
        .all()
    )
    return [
        models.UserDomainMembership(
            domain_id=domain.id,
            domain_name=domain.name,
            role=role.role,
            granted_at=role.granted_at,
        )
        for role, domain in rows
    ]


def list_all_users(db: Session, limit: int = 50, offset: int = 0) -> list[User]:
    return db.query(User).order_by(User.email).offset(offset).limit(limit).all()


def search_users_by_email(db: Session, email_query: str, limit: int = 10) -> list[User]:
    return (
        db.query(User)
        .filter(User.email.ilike(f"%{email_query}%"))
        .order_by(User.email)
        .limit(limit)
        .all()
    )


def set_platform_admin(db: Session, target_user_id: UUID, is_platform_admin: bool, acting_user_id: UUID) -> User:
    if target_user_id == acting_user_id:
        raise CannotModifyOwnPlatformAdminStatusError()
    user = get_user_by_id(db, target_user_id)
    user.is_platform_admin = is_platform_admin
    db.commit()
    db.refresh(user)
    logging.info(f"Platform admin status for user {target_user_id} set to {is_platform_admin} by {acting_user_id}")
    # AUDIT HOOK: record platform-admin grant/revoke
    return user
