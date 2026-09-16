import pytest
from uuid import uuid4
from src.users import service as users_service
from src.users.models import PasswordChange
from src.exceptions import (
    UserNotFoundError, InvalidPasswordError, PasswordMismatchError, CannotModifyOwnPlatformAdminStatusError,
)
from src.auth import service as auth_service
from src.entities.user import User


def _make_user(email: str, is_platform_admin: bool = False) -> User:
    return User(
        id=uuid4(), email=email, first_name="F", last_name="L",
        password_hash=auth_service.get_password_hash("password123"), is_platform_admin=is_platform_admin,
    )

def test_get_user_by_id(db_session, test_user):
    db_session.add(test_user)
    db_session.commit()
    
    user = users_service.get_user_by_id(db_session, test_user.id)
    assert user.id == test_user.id
    assert user.email == test_user.email
    
    with pytest.raises(UserNotFoundError):
        users_service.get_user_by_id(db_session, uuid4())

def test_change_password(db_session, test_user):
    # Add the user to the database
    db_session.add(test_user)
    db_session.commit()
    
    # Test successful password change
    password_change = PasswordChange(
        current_password="password123",  # This matches the password set in test_user fixture
        new_password="newpassword123",
        new_password_confirm="newpassword123"
    )
    
    users_service.change_password(db_session, test_user.id, password_change)
    
    # Verify new password works
    updated_user = db_session.query(User).filter_by(id=test_user.id).first()
    assert auth_service.verify_password("newpassword123", updated_user.password_hash)

def test_change_password_invalid_current(db_session, test_user):
    db_session.add(test_user)
    db_session.commit()

    # Test invalid current password
    with pytest.raises(InvalidPasswordError):
        password_change = PasswordChange(
            current_password="wrongpassword",
            new_password="newpassword123",
            new_password_confirm="newpassword123"
        )
        users_service.change_password(db_session, test_user.id, password_change)

def test_change_password_mismatch(db_session, test_user):
    db_session.add(test_user)
    db_session.commit()

    # Test password mismatch
    with pytest.raises(PasswordMismatchError):
        password_change = PasswordChange(
            current_password="password123",
            new_password="newpassword123",
            new_password_confirm="differentpassword"
        )
        users_service.change_password(db_session, test_user.id, password_change)


def test_list_all_users_orders_by_email_and_respects_limit(db_session):
    db_session.add_all([_make_user("charlie@example.com"), _make_user("alice@example.com"), _make_user("bob@example.com")])
    db_session.commit()

    users = users_service.list_all_users(db_session, limit=2)

    assert [u.email for u in users] == ["alice@example.com", "bob@example.com"]


def test_search_users_by_email_is_case_insensitive_partial_match(db_session):
    db_session.add_all([_make_user("alice@example.com"), _make_user("bob@example.com")])
    db_session.commit()

    results = users_service.search_users_by_email(db_session, "ALICE")

    assert [u.email for u in results] == ["alice@example.com"]


def test_search_users_by_email_respects_limit(db_session):
    db_session.add_all([_make_user(f"user{i}@example.com") for i in range(5)])
    db_session.commit()

    results = users_service.search_users_by_email(db_session, "user", limit=3)

    assert len(results) == 3


def test_set_platform_admin_grants_and_revokes(db_session):
    admin = _make_user("admin@example.com", is_platform_admin=True)
    target = _make_user("target@example.com")
    db_session.add_all([admin, target])
    db_session.commit()

    updated = users_service.set_platform_admin(db_session, target.id, True, admin.id)
    assert updated.is_platform_admin is True

    updated = users_service.set_platform_admin(db_session, target.id, False, admin.id)
    assert updated.is_platform_admin is False


def test_set_platform_admin_blocks_self_modification(db_session):
    admin = _make_user("admin@example.com", is_platform_admin=True)
    db_session.add(admin)
    db_session.commit()

    with pytest.raises(CannotModifyOwnPlatformAdminStatusError):
        users_service.set_platform_admin(db_session, admin.id, False, admin.id)
