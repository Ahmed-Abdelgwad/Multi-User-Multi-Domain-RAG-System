import enum


class UserType(str, enum.Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class AuthProviderType(str, enum.Enum):
    LOCAL = "local"
    OIDC = "oidc"
    SAML = "saml"


class DomainRole(str, enum.Enum):
    READER = "reader"
    CONTRIBUTOR = "contributor"
    ADMIN = "domain_admin"


DOMAIN_ROLE_RANK: dict[DomainRole, int] = {
    DomainRole.READER: 0,
    DomainRole.CONTRIBUTOR: 1,
    DomainRole.ADMIN: 2,
}


class DocumentSourceType(str, enum.Enum):
    """Spec 2.1/2.2/2.3: which ingestion path produced this Document."""
    PDF = "pdf"
    DOCX = "docx"
    CSV = "csv"
    XLSX = "xlsx"
    WEB = "web"
    DB = "db"


class DocumentStatus(str, enum.Enum):
    
    PENDING = "pending"
    PROCESSING = "processing"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class ChunkContentType(str, enum.Enum):
    TEXT = "text"
    TABLE = "table"
