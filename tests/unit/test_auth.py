"""Token hygiene: tokens expire, and a forged/expired token is rejected."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_expired_token_is_rejected():
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(hours=1)
    stale = jwt.encode(
        {"tenant_id": "t1", "sub": "u", "exp": past},
        settings.jwt_secret, algorithm=settings.jwt_algorithm,
    )
    with TestClient(app) as client:
        resp = client.get("/claims", headers={"Authorization": f"Bearer {stale}"})
    assert resp.status_code == 401


def test_token_signed_with_wrong_secret_is_rejected():
    forged = jwt.encode({"tenant_id": "t1", "sub": "u"}, "not-the-secret", algorithm="HS256")
    with TestClient(app) as client:
        resp = client.get("/claims", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401
