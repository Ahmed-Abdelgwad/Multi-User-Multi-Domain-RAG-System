from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from .routes import register_routes
from .config import get_settings
from .logging_config import configure_logging, LogLevels


configure_logging(LogLevels.info)

app = FastAPI()

# Required by Authlib's starlette client to stash OIDC state/nonce across the
# SSO redirect round-trip.
app.add_middleware(SessionMiddleware, secret_key=get_settings().secret_key)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_routes(app)