from fastapi import HTTPException

class UserError(HTTPException):
    """Base exception for user-related errors"""
    pass

class UserNotFoundError(UserError):
    def __init__(self, user_id=None):
        message = "User not found" if user_id is None else f"User with id {user_id} not found"
        super().__init__(status_code=404, detail=message)

class PasswordMismatchError(UserError):
    def __init__(self):
        super().__init__(status_code=400, detail="New passwords do not match")

class InvalidPasswordError(UserError):
    def __init__(self):
        super().__init__(status_code=401, detail="Current password is incorrect")

class UserAlreadyExistsError(UserError):
    def __init__(self, email: str):
        super().__init__(status_code=409, detail=f"A user with email '{email}' already exists")

class CannotModifyOwnPlatformAdminStatusError(UserError):
    def __init__(self):
        super().__init__(status_code=400, detail="You cannot change your own platform admin status")

class AuthenticationError(HTTPException):
    def __init__(self, message: str = "Could not validate user"):
        super().__init__(status_code=401, detail=message)

class InsufficientPermissionsError(HTTPException):
    def __init__(self, domain_ids=None, required_role=None):
        detail = "Insufficient permissions for this domain"
        if domain_ids:
            detail = f"Insufficient permissions for domain(s): {', '.join(str(d) for d in domain_ids)}"
        if required_role:
            detail += f" (requires at least '{required_role.value}')"
        super().__init__(status_code=403, detail=detail)

class DomainError(HTTPException):
    """Base exception for domain-related errors"""
    pass

class DomainNotFoundError(DomainError):
    def __init__(self, domain_id=None):
        message = "Domain not found" if domain_id is None else f"Domain with id {domain_id} not found"
        super().__init__(status_code=404, detail=message)

class DomainArchivedError(DomainError):
    def __init__(self, domain_id=None):
        message = "Domain is archived" if domain_id is None else f"Domain with id {domain_id} is archived"
        super().__init__(status_code=400, detail=message)

class DuplicateDomainNameError(DomainError):
    def __init__(self, name: str):
        super().__init__(status_code=409, detail=f"A domain named '{name}' already exists")

class DomainNotArchivedError(DomainError):
    def __init__(self, domain_id=None):
        message = (
            "Domain must be archived before it can be deleted" if domain_id is None
            else f"Domain with id {domain_id} must be archived before it can be deleted"
        )
        super().__init__(status_code=400, detail=message)

class SSOPoolMismatchError(AuthenticationError):
    def __init__(self, message: str = "This account belongs to a different user pool"):
        super().__init__(message)

class SSOProviderNotConfiguredError(HTTPException):
    def __init__(self, pool: str):
        super().__init__(status_code=501, detail=f"SSO is not configured for the '{pool}' user pool")

class DocumentError(HTTPException):
    """Base exception for document ingestion errors"""
    pass

class DocumentNotFoundError(DocumentError):
    def __init__(self, document_id=None):
        message = "Document not found" if document_id is None else f"Document with id {document_id} not found"
        super().__init__(status_code=404, detail=message)

class UnsupportedDocumentTypeError(DocumentError):
    def __init__(self, filename: str):
        super().__init__(status_code=415, detail=f"Unsupported file type for '{filename}' (supported: pdf, docx, csv, xlsx)")

class ChunkingError(HTTPException):
    """Base exception for chunking/embedding errors"""
    pass

class InvalidIngestionConfigError(ChunkingError):
    def __init__(self, message: str):
        super().__init__(status_code=400, detail=message)

class RetrievalError(HTTPException):
    """Base exception for retrieval/ranking/generation errors (spec section 3)"""
    pass

class InvalidRetrievalConfigError(RetrievalError):
    def __init__(self, message: str):
        super().__init__(status_code=400, detail=message)

class GenerationUnavailableError(RetrievalError):
    def __init__(self, message: str = "Generation model is unavailable"):
        super().__init__(status_code=502, detail=message)

class EvaluationError(HTTPException):
    """Base exception for judge evaluation errors (spec section 4)"""
    pass

class JudgeUnavailableError(EvaluationError):
    def __init__(self, message: str = "Judge model is unavailable"):
        super().__init__(status_code=502, detail=message)

class QueryLogNotFoundError(EvaluationError):
    def __init__(self, query_log_id=None):
        message = "Query log not found" if query_log_id is None else f"Query log with id {query_log_id} not found"
        super().__init__(status_code=404, detail=message)

class InvalidDashboardWindowError(EvaluationError):
    def __init__(self, message: str):
        super().__init__(status_code=400, detail=message)

class GoldenQAItemNotFoundError(EvaluationError):
    def __init__(self, item_id=None):
        message = "Golden QA item not found" if item_id is None else f"Golden QA item with id {item_id} not found"
        super().__init__(status_code=404, detail=message)

class OntologyError(HTTPException):
    """Base exception for graph ontology schema errors"""
    pass

class OntologySchemaNotFoundError(OntologyError):
    def __init__(self, domain_id=None):
        message = "No active ontology schema for this domain" if domain_id is None else f"No active ontology schema for domain {domain_id}"
        super().__init__(status_code=404, detail=message)

class InvalidOntologySchemaError(OntologyError):
    def __init__(self, message: str):
        super().__init__(status_code=400, detail=message)
