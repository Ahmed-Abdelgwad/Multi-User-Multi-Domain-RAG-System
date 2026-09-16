from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, Query, status

from ..database.core import DbSession
from ..entities.user import User
from ..authz.dependencies import require_platform_admin
from . import models
from . import service
from ..auth.service import CurrentUser

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


@router.get("/me", response_model=models.UserResponse)
def get_current_user(current_user: CurrentUser, db: DbSession):
    return service.get_user_by_id(db, current_user.get_uuid())


@router.get("/me/domains", response_model=List[models.UserDomainMembership])
def get_current_user_domains(current_user: CurrentUser, db: DbSession):
    return service.get_user_domains(db, current_user.get_uuid())


@router.get("/", response_model=List[models.UserResponse])
def list_users(
    db: DbSession,
    _admin: User = Depends(require_platform_admin),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return service.list_all_users(db, limit, offset)


@router.put("/{user_id}/platform-admin", response_model=models.UserResponse)
def set_platform_admin(
    db: DbSession,
    user_id: UUID,
    update: models.PlatformAdminUpdate,
    admin: User = Depends(require_platform_admin),
):
    return service.set_platform_admin(db, user_id, update.is_platform_admin, admin.id)


@router.put("/change-password", status_code=status.HTTP_200_OK)
def change_password(
    password_change: models.PasswordChange,
    db: DbSession,
    current_user: CurrentUser
):
    service.change_password(db, current_user.get_uuid(), password_change)
