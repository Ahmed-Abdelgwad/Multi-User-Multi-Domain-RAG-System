from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime
from src.entities.enums import DomainRole


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    first_name: str
    last_name: str
    is_platform_admin: bool


class PasswordChange(BaseModel):
    current_password: str
    new_password: str
    new_password_confirm: str


class UserDomainMembership(BaseModel):
    domain_id: UUID
    domain_name: str
    role: DomainRole
    granted_at: datetime
