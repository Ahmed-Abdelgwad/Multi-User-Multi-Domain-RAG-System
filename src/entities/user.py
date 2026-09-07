from sqlalchemy import Column, String, Boolean, Enum
from sqlalchemy.dialects.postgresql import UUID
import uuid
from ..database.core import Base
from .enums import UserType, AuthProviderType

class User(Base):
    __tablename__ = 'users'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=True)
    user_type = Column(Enum(UserType), nullable=False, default=UserType.INTERNAL)
    auth_provider = Column(Enum(AuthProviderType), nullable=False, default=AuthProviderType.LOCAL)
    external_id = Column(String, nullable=True)
    is_platform_admin = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)

    def __repr__(self):
        return f"<User(email='{self.email}', first_name='{self.first_name}', last_name='{self.last_name}')>"
    
