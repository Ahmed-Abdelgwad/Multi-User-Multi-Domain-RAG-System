from uuid import uuid4
import pytest
from sqlalchemy.exc import IntegrityError
from src.entities.enums import UserType
from src.entities.session_policy import SessionPolicy
from src.auth import service, models


def test_get_or_create_session_policy_bootstraps_from_settings_default(db_session):
    policy = service.get_or_create_session_policy(db_session)

    assert policy.internal_token_ttl_minutes == service.ACCESS_TOKEN_EXPIRE_MINUTES
    assert policy.external_token_ttl_minutes == service.ACCESS_TOKEN_EXPIRE_MINUTES


def test_get_or_create_session_policy_is_idempotent(db_session):
    first = service.get_or_create_session_policy(db_session)
    second = service.get_or_create_session_policy(db_session)

    assert first.id == second.id


def test_update_session_policy_persists_new_values(db_session):
    updated_by = uuid4()

    policy = service.update_session_policy(
        db_session, models.SessionPolicyUpdate(internal_token_ttl_minutes=120, external_token_ttl_minutes=10), updated_by
    )

    assert policy.internal_token_ttl_minutes == 120
    assert policy.external_token_ttl_minutes == 10
    assert policy.updated_by == updated_by


def test_ttl_minutes_for_pool_returns_the_right_pools_value(db_session):
    service.update_session_policy(
        db_session, models.SessionPolicyUpdate(internal_token_ttl_minutes=120, external_token_ttl_minutes=10), uuid4()
    )

    assert service.ttl_minutes_for_pool(db_session, UserType.INTERNAL) == 120
    assert service.ttl_minutes_for_pool(db_session, UserType.EXTERNAL) == 10


def test_singleton_is_enforced_by_the_database_not_just_get_or_create(db_session):
    # Bypasses get_or_create entirely -- proves the UNIQUE constraint on
    # `singleton` itself rejects a second row, not just the app-level
    # query-then-insert check (which a race between two concurrent
    # first-ever calls could slip past).
    db_session.add(SessionPolicy(id=uuid4(), internal_token_ttl_minutes=30, external_token_ttl_minutes=30))
    db_session.commit()

    db_session.add(SessionPolicy(id=uuid4(), internal_token_ttl_minutes=99, external_token_ttl_minutes=99))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    assert db_session.query(SessionPolicy).count() == 1


def test_get_or_create_recovers_from_a_lost_race(db_session, monkeypatch):
    # Simulates two concurrent first-ever calls sharing the same
    # underlying (file-backed) sqlite DB but different sessions/
    # connections, the way two concurrent requests would: this session's
    # own SELECT finds nothing, but by the time it tries to INSERT, a
    # separate session has already committed the real winning row --
    # must recover by returning that row, not raise.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    other_engine = create_engine("sqlite:///./test.db", connect_args={"check_same_thread": False})
    other_db = sessionmaker(bind=other_engine)()
    winner_id = uuid4()

    real_add = db_session.add

    def add_after_a_concurrent_winner_commits(instance):
        # Fires right after get_or_create_session_policy's own SELECT
        # already returned None -- another session wins the race here.
        other_db.add(SessionPolicy(id=winner_id, internal_token_ttl_minutes=30, external_token_ttl_minutes=30))
        other_db.commit()
        real_add(instance)

    monkeypatch.setattr(db_session, "add", add_after_a_concurrent_winner_commits, raising=False)

    policy = service.get_or_create_session_policy(db_session)

    assert policy.id == winner_id
    assert db_session.query(SessionPolicy).count() == 1
    other_db.close()
    other_engine.dispose()
