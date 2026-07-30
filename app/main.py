"""FastAPI application entry point for the claims-triage agent."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import audit, claims, health, review
from app.auth.tenant import TenantContext, get_tenant_context, issue_token
from app.config import get_settings
from app.db.base import Base, engine, get_db
from app.db.models import Policy, Tenant
from app.observability.logging import configure_logging, get_logger
from app.schemas import PolicyIn


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log = get_logger("startup")
    settings = get_settings()
    # Fail closed: never run outside dev with the default JWT secret, since
    # tenant isolation (and thus the human gate) depends entirely on the token.
    if settings.environment != "dev" and settings.jwt_secret == "dev-only-change-me":
        raise RuntimeError("JWT_SECRET must be overridden outside the dev environment")
    Base.metadata.create_all(bind=engine)  # dev convenience; prod uses Alembic
    log.info("app.started", app=settings.app_name, env=settings.environment)
    yield


app = FastAPI(title=get_settings().app_name, version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(claims.router)
app.include_router(review.router)
app.include_router(audit.router)


class SignupIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class SignupOut(BaseModel):
    tenant_id: str
    name: str
    access_token: str


@app.post("/tenants/signup", response_model=SignupOut, tags=["tenants"])
def signup(body: SignupIn, db: Session = Depends(get_db)) -> SignupOut:
    tenant = Tenant(name=body.name)
    db.add(tenant)
    db.commit()
    token = issue_token(tenant_id=tenant.id, user_id="owner")
    return SignupOut(tenant_id=tenant.id, name=tenant.name, access_token=token)


@app.post("/policies", tags=["policies"])
def create_policy(
    body: PolicyIn,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> dict:
    policy = Policy(tenant_id=ctx.tenant_id, **body.model_dump())
    db.add(policy)
    db.commit()
    return {"policy_id": policy.id, "policy_number": policy.policy_number}


# --- Frontend: single-page console served by the same app (no separate deploy) ---
_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")
