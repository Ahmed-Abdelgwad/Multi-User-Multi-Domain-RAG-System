import pytest
from uuid import uuid4
from src.authz import retrieval
from src.entities.domain import Domain
from src.entities.enums import DomainRole
from src.entities.user_domain_role import UserDomainRole
from src.auth.models import TokenData
from src.exceptions import InsufficientPermissionsError, DomainArchivedError


def _grant(db_session, user_id, domain_id, role: DomainRole):
    db_session.add(UserDomainRole(id=uuid4(), user_id=user_id, domain_id=domain_id, role=role))
    db_session.commit()


def _make_domain(db_session, is_archived: bool = False) -> Domain:
    domain = Domain(id=uuid4(), name=f"domain-{uuid4()}", created_by=uuid4(), is_archived=is_archived)
    db_session.add(domain)
    db_session.commit()
    return domain


class TestBuildRetrievalFilter:
    def test_all_domains_must_be_permitted_not_just_some(self, db_session):
        # Spec 1.3: cross-domain queries require permission in ALL target
        # domains -- one unpermitted domain rejects the whole request,
        # rather than silently dropping it and searching the rest.
        user_id = uuid4()
        permitted_domain = _make_domain(db_session)
        other_domain = _make_domain(db_session)
        _grant(db_session, user_id, permitted_domain.id, DomainRole.READER)
        current_user = TokenData(user_id=str(user_id))

        with pytest.raises(InsufficientPermissionsError):
            retrieval.build_retrieval_filter(
                db_session, current_user, [permitted_domain.id, other_domain.id]
            )

    def test_permitted_in_all_domains_succeeds(self, db_session):
        user_id = uuid4()
        domain_a, domain_b = _make_domain(db_session), _make_domain(db_session)
        _grant(db_session, user_id, domain_a.id, DomainRole.READER)
        _grant(db_session, user_id, domain_b.id, DomainRole.READER)
        current_user = TokenData(user_id=str(user_id))

        result = retrieval.build_retrieval_filter(db_session, current_user, [domain_a.id, domain_b.id])

        assert result.permitted_domain_ids == [domain_a.id, domain_b.id]
        assert result.user_id == user_id

    def test_raises_when_none_permitted(self, db_session):
        current_user = TokenData(user_id=str(uuid4()))
        with pytest.raises(InsufficientPermissionsError):
            retrieval.build_retrieval_filter(db_session, current_user, [uuid4(), uuid4()])

    def test_respects_minimum_role(self, db_session):
        user_id = uuid4()
        domain = _make_domain(db_session)
        _grant(db_session, user_id, domain.id, DomainRole.READER)
        current_user = TokenData(user_id=str(user_id))

        with pytest.raises(InsufficientPermissionsError):
            retrieval.build_retrieval_filter(
                db_session, current_user, [domain.id], minimum_role=DomainRole.CONTRIBUTOR
            )

    def test_rejects_archived_domain_even_when_permitted(self, db_session):
        user_id = uuid4()
        domain = _make_domain(db_session, is_archived=True)
        _grant(db_session, user_id, domain.id, DomainRole.READER)
        current_user = TokenData(user_id=str(user_id))

        with pytest.raises(DomainArchivedError):
            retrieval.build_retrieval_filter(db_session, current_user, [domain.id])

    def test_unpermitted_nonexistent_domain_is_permission_error_not_not_found(self, db_session):
        # Permission is checked before the archived/existence lookup, so a
        # caller with no access can't distinguish "doesn't exist" from
        # "exists but you can't see it" -- both are a plain 403.
        current_user = TokenData(user_id=str(uuid4()))
        with pytest.raises(InsufficientPermissionsError):
            retrieval.build_retrieval_filter(db_session, current_user, [uuid4()])


class TestAttachDomainProvenance:
    def test_returns_domain_name_when_found(self, db_session, test_domain):
        db_session.add(test_domain)
        db_session.commit()

        provenance = retrieval.attach_domain_provenance(test_domain.id, db_session)

        assert provenance.domain_id == test_domain.id
        assert provenance.domain_name == test_domain.name

    def test_falls_back_to_id_when_domain_missing(self, db_session):
        missing_id = uuid4()
        provenance = retrieval.attach_domain_provenance(missing_id, db_session)
        assert provenance.domain_name == str(missing_id)
