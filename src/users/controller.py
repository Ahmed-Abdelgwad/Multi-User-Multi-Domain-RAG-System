from typing import List
from fastapi import APIRouter, status

from ..database.core import DbSession
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


@router.put("/change-password", status_code=status.HTTP_200_OK)
def change_password(
    password_change: models.PasswordChange,
    db: DbSession,
    current_user: CurrentUser
):
    service.change_password(db, current_user.get_uuid(), password_change)
