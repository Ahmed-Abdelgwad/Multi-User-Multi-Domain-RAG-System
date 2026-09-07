import pytest
from uuid import uuid4, UUID
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.core import Base
from src.entities.user import User
from src.entities.domain import Domain
from src.entities.user_domain_role import UserDomainRole
from src.entities.enums import DomainRole
from src.auth.models import TokenData
from src.auth.service import get_password_hash
from src.rate_limiter import limiter


@pytest.fixture(scope="function")
def db_session():
    # Use a unique database URL for testing
    SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def test_user():
    # Create a user with a known password hash
    password_hash = get_password_hash("password123")
    return User(
        id=uuid4(),
        email="test@example.com",
        first_name="Test",
        last_name="User",
        password_hash=password_hash
    )

@pytest.fixture(scope="function")
def test_token_data():
    return TokenData(user_id=str(uuid4()))

@pytest.fixture(scope="function")
def test_domain():
    return Domain(
        id=uuid4(),
        name=f"domain-{uuid4()}",
        description="Test domain",
        created_by=uuid4(),
    )


@pytest.fixture(scope="function")
def client(db_session):
    from src.main import app
    from src.database.core import get_db
    
    # Disable rate limiting for tests
    limiter.reset()
    
    def override_get_db():
        try:
            yield db_session
        finally:
            db_session.close()
            
    app.dependency_overrides[get_db] = override_get_db
    
    from fastapi.testclient import TestClient
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

@pytest.fixture(scope="function")
def auth_headers(client, db_session):
    # Register a test user
    response = client.post(
        "/auth/",
        json={
            "email": "test.user@example.com",
            "password": "testpassword123",
            "first_name": "Test",
            "last_name": "User"
        }
    )
    assert response.status_code == 201
    
    # Login to get access token
    response = client.post(
        "/auth/token",
        data={
            "username": "test.user@example.com",
            "password": "testpassword123",
            "grant_type": "password"
        }
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}

@pytest.fixture(scope="function")
def make_user_with_role(client, db_session):
    """Factory fixture: registers+logs in a fresh user, then grants them
    `role` on `domain_id` by inserting a UserDomainRole row directly.
    Returns (headers, user_id).
    """
    def _make(domain_id, role: DomainRole):
        domain_id = UUID(str(domain_id))
        email = f"user-{uuid4()}@example.com"
        password = "testpassword123"

        response = client.post(
            "/auth/",
            json={
                "email": email,
                "password": password,
                "first_name": "Test",
                "last_name": "User"
            }
        )
        assert response.status_code == 201

        response = client.post(
            "/auth/token",
            data={
                "username": email,
                "password": password,
                "grant_type": "password"
            }
        )
        assert response.status_code == 200
        token = response.json()["access_token"]

        user = db_session.query(User).filter(User.email == email).first()
        db_session.add(UserDomainRole(id=uuid4(), user_id=user.id, domain_id=domain_id, role=role))
        db_session.commit()

        return {"Authorization": f"Bearer {token}"}, user.id

    return _make

@pytest.fixture(scope="function")
def platform_admin_headers(client, db_session):
    email = f"admin-{uuid4()}@example.com"
    password = "testpassword123"

    response = client.post(
        "/auth/",
        json={
            "email": email,
            "password": password,
            "first_name": "Admin",
            "last_name": "User"
        }
    )
    assert response.status_code == 201

    response = client.post(
        "/auth/token",
        data={
            "username": email,
            "password": password,
            "grant_type": "password"
        }
    )
    assert response.status_code == 200
    token = response.json()["access_token"]

    user = db_session.query(User).filter(User.email == email).first()
    user.is_platform_admin = True
    db_session.commit()

    return {"Authorization": f"Bearer {token}"}