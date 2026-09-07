import pytest
from uuid import uuid4
from src.authz import retrieval
from src.entities.enums import DomainRole
from src.entities.user_domain_role import UserDomainRole
from src.auth.models import TokenData
from src.exceptions import InsufficientPermissionsError


def _grant(db_session, user_id, domain_id, role: DomainRole):
    db_session.add(UserDomainRole(id=uuid4(), user_id=user_id, domain_id=domain_id, role=role))
    db_session.commit()


class TestBuildRetrievalFilter:
    def test_filters_out_unpermitted_domains(self, db_session):
        user_id = uuid4()
        permitted_domain, other_domain = uuid4(), uuid4()
        _grant(db_session, user_id, permitted_domain, DomainRole.READER)
        current_user = TokenData(user_id=str(user_id))

        result = retrieval.build_retrieval_filter(
            db_session, current_user, [permitted_domain, other_domain]
        )

        assert result.permitted_domain_ids == [permitted_domain]
        assert result.user_id == user_id

    def test_raises_when_none_permitted(self, db_session):
        current_user = TokenData(user_id=str(uuid4()))
        with pytest.raises(InsufficientPermissionsError):
            retrieval.build_retrieval_filter(db_session, current_user, [uuid4(), uuid4()])

    def test_respects_minimum_role(self, db_session):
        user_id = uuid4()
        domain_id = uuid4()
        _grant(db_session, user_id, domain_id, DomainRole.READER)
        current_user = TokenData(user_id=str(user_id))

        with pytest.raises(InsufficientPermissionsError):
            retrieval.build_retrieval_filter(
                db_session, current_user, [domain_id], minimum_role=DomainRole.CONTRIBUTOR
            )


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
