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


class LLMRoute(str, enum.Enum):
    """Spec 3.5's hybrid LLM routing: sensitive/internal content stays on
    a self-hosted model, general queries go to an external API model.
    """
    LOCAL = "local"
    API = "api"


class JudgeProvider(str, enum.Enum):
    """Spec 4.1's judge backend -- a distinct concept from LLMRoute
    (LLMRoute answers "which model generated this answer"; this answers
    "which model judged it"), named by the actual provider rather than
    an abstract local/api tier so a third backend later doesn't force a
    tier-naming stretch. MERCURY (Inception Labs API) is the default for
    all traffic in this MVP; OLLAMA (self-hosted) is implemented but not
    wired into the default flow yet -- see evaluation/judge.py.
    """
    MERCURY = "mercury"
    OLLAMA = "ollama"


class EvaluationStatus(str, enum.Enum):
    """Spec 4.1/4.3's async judge evaluation lifecycle. Every
    `EvaluationResult` row lands in an explicit terminal state
    (COMPLETED/FAILED/SKIPPED) once the judge task actually runs --
    never left ambiguously at PENDING forever.
    """
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class HumanVerdict(str, enum.Enum):
    """Spec 4.6's "accept or reject flagged answers" -- a moderation
    verdict on the ANSWER's overall usability, orthogonal to (and
    combinable with) a numeric score correction via override_evaluation.
    An admin might reject an answer for reasons the four judge
    dimensions don't fully capture, or accept one as-is to confirm the
    judge scored it correctly.
    """
    ACCEPTED = "accepted"
    REJECTED = "rejected"
