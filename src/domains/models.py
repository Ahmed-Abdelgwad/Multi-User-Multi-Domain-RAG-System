from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from src.entities.enums import DomainRole


class DomainCreate(BaseModel):
    name: str
    description: str | None = None


class DomainResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    is_archived: bool
    created_by: UUID
    created_at: datetime


class AssignRoleRequest(BaseModel):
    user_id: UUID
    role: DomainRole


class UserDomainRoleResponse(BaseModel):
    user_id: UUID
    domain_id: UUID
    role: DomainRole
    granted_at: datetime
