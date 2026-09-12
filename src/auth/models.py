from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

class RegisterUserRequest(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    
class TokenData(BaseModel):
    user_id: str | None = None

    def get_uuid(self) -> UUID | None:
        if self.user_id:
            return UUID(self.user_id)
        return None


class SessionPolicyResponse(BaseModel):
    internal_token_ttl_minutes: int
    external_token_ttl_minutes: int
    updated_at: datetime


class SessionPolicyUpdate(BaseModel):
    internal_token_ttl_minutes: int = Field(gt=0)
    external_token_ttl_minutes: int = Field(gt=0)

