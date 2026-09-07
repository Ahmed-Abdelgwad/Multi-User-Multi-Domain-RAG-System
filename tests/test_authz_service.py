import pytest
from uuid import uuid4
from src.authz import service as authz_service
from src.entities.enums import DomainRole
from src.entities.user_domain_role import UserDomainRole
from src.exceptions import InsufficientPermissionsError


def _grant(db_session, user_id, domain_id, role: DomainRole):
    db_session.add(UserDomainRole(id=uuid4(), user_id=user_id, domain_id=domain_id, role=role))
    db_session.commit()


class TestGetEffectiveRole:
    def test_returns_none_when_no_role_assigned(self, db_session):
        assert authz_service.get_effective_role(db_session, uuid4(), uuid4()) is None

    def test_returns_assigned_role(self, db_session):
        user_id, domain_id = uuid4(), uuid4()
        _grant(db_session, user_id, domain_id, DomainRole.CONTRIBUTOR)
        assert authz_service.get_effective_role(db_session, user_id, domain_id) == DomainRole.CONTRIBUTOR


class TestHasMinimumRole:
    @pytest.mark.parametrize(
        "granted,minimum,expected",
        [
            (DomainRole.READER, DomainRole.READER, True),
            (DomainRole.CONTRIBUTOR, DomainRole.READER, True),
            (DomainRole.ADMIN, DomainRole.CONTRIBUTOR, True),
            (DomainRole.READER, DomainRole.CONTRIBUTOR, False),
            (DomainRole.CONTRIBUTOR, DomainRole.ADMIN, False),
        ],
    )
    def test_rank_comparison(self, db_session, granted, minimum, expected):
        user_id, domain_id = uuid4(), uuid4()
        _grant(db_session, user_id, domain_id, granted)
        assert authz_service.has_minimum_role(db_session, user_id, domain_id, minimum) is expected

    def test_no_role_is_false(self, db_session):
        assert authz_service.has_minimum_role(db_session, uuid4(), uuid4(), DomainRole.READER) is False


class TestGetDomainsMissingRole:
    def test_reports_only_missing_domains(self, db_session):
        user_id = uuid4()
        ok_domain, missing_domain = uuid4(), uuid4()
        _grant(db_session, user_id, ok_domain, DomainRole.READER)

        missing = authz_service.get_domains_missing_role(
            db_session, user_id, [ok_domain, missing_domain], DomainRole.READER
        )
        assert missing == [missing_domain]

    def test_insufficient_rank_counts_as_missing(self, db_session):
        user_id, domain_id = uuid4(), uuid4()
        _grant(db_session, user_id, domain_id, DomainRole.READER)

        missing = authz_service.get_domains_missing_role(
            db_session, user_id, [domain_id], DomainRole.ADMIN
        )
        assert missing == [domain_id]


class TestCheckCrossDomainAccess:
    def test_passes_when_all_domains_permitted(self, db_session):
        user_id = uuid4()
        domain_a, domain_b = uuid4(), uuid4()
        _grant(db_session, user_id, domain_a, DomainRole.READER)
        _grant(db_session, user_id, domain_b, DomainRole.CONTRIBUTOR)

        authz_service.check_cross_domain_access(db_session, user_id, [domain_a, domain_b])

    def test_raises_when_any_domain_missing(self, db_session):
        user_id = uuid4()
        domain_a, domain_b = uuid4(), uuid4()
        _grant(db_session, user_id, domain_a, DomainRole.READER)
        # no role granted on domain_b

        with pytest.raises(InsufficientPermissionsError):
            authz_service.check_cross_domain_access(db_session, user_id, [domain_a, domain_b])


class TestListUserDomainRoles:
    def test_lists_all_roles_for_user(self, db_session):
        user_id = uuid4()
        _grant(db_session, user_id, uuid4(), DomainRole.READER)
        _grant(db_session, user_id, uuid4(), DomainRole.ADMIN)
        _grant(db_session, uuid4(), uuid4(), DomainRole.READER)  # different user

        roles = authz_service.list_user_domain_roles(db_session, user_id)
        assert len(roles) == 2
