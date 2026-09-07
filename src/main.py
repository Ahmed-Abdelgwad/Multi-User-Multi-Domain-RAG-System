from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from .routes import register_routes
from .config import get_settings
from .logging_config import configure_logging, LogLevels


configure_logging(LogLevels.info)

app = FastAPI()

# Required by Authlib's starlette client to stash OIDC state/nonce across the
# SSO redirect round-trip.
app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

register_routes(app)