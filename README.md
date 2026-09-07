# Identity, Roles & Domain Isolation Service

Authentication and authorization backend for a multi-user, multi-domain RAG system (FastAPI + PostgreSQL), covering:

- Authentication: password/JWT login, plus OIDC SSO with optional SAML, separate internal/external user pools
- RBAC: Domain Admin / Contributor / Reader roles scoped per domain, enforced server-side on every request
- Domain management: create/archive isolated domains, assign/revoke per-domain roles, cross-domain access checks
- A retrieval-enforcement contract (`src/authz/retrieval.py`) for future vector/graph retrieval modules to filter results by domain permission
- SQLAlchemy, PostgreSQL, Alembic migrations, rate limiting, pytest unit + e2e tests

# Install all dependencies.
- Run `pip install -r requirements-dev.txt`

# Configuration
- Copy `.env.example` to `.env` and fill in real values (secret key, database URL, OIDC discovery URLs/credentials per user pool, token TTL). Nothing is hardcoded anymore -- see `src/config.py`.

# How to run app. Using Docker with PostgreSQL.
- Install Docker Desktop
- Run `docker compose up --build` (runs `alembic upgrade head` automatically before starting the API)
- Run `docker compose down` to stop all services

# How to run locally without postgres or docker.
- set `DATABASE_URL=sqlite:///./app.db` in `.env`
- run `alembic upgrade head` to create the schema
- run `uvicorn src.main:app --reload`

# Database migrations (Alembic)
- Run `alembic upgrade head` to apply all migrations
- Run `alembic revision --autogenerate -m "message"` to create a new migration after changing an entity
- Run `alembic downgrade -1` to roll back one migration

# How to run tests.
- Run `pytest` to run all tests