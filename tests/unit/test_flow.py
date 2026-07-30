"""End-to-end through the API: policy -> claim submit (auto-triage) -> review
queue -> human approve/reject -> audit trail."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import app


def _signup(client: TestClient) -> dict:
    r = client.post("/tenants/signup", json={"name": f"ins-{uuid.uuid4()}"}).json()
    return {"Authorization": f"Bearer {r['access_token']}"}


def _make_policy(client, auth, number="POL-100"):
    client.post("/policies", headers=auth, json={
        "policy_number": number, "holder_name": "Mario Rossi", "coverage_type": "auto",
        "coverage_limit": 20000.0, "deductible": 500.0,
        "start_date": "2026-01-01", "end_date": "2026-12-31", "active": True,
    })


def _submit(client, auth, **kw):
    body = {
        "policy_number": "POL-100", "claim_type": "auto", "claim_amount": 5000.0,
        "incident_date": "2026-06-01", "reported_date": "2026-06-03",
        "prior_claims_count": 0, "has_documentation": True,
    }
    body.update(kw)
    return client.post("/claims", headers=auth, json=body).json()


def test_submitted_claim_is_triaged_and_pending_review():
    with TestClient(app) as client:
        auth = _signup(client)
        _make_policy(client, auth)
        claim = _submit(client, auth)
        assert claim["status"] == "pending_review"        # NOT auto-settled
        assert claim["policy_verification"]["verified"] is True
        assert claim["fraud_assessment"]["model_version"] == "fraud-logreg-v1"
        assert claim["recommendation"]["recommended_amount"] > 0
        assert claim["settled_amount"] is None


def test_claim_appears_in_review_queue():
    with TestClient(app) as client:
        auth = _signup(client)
        _make_policy(client, auth)
        claim = _submit(client, auth)
        queue = client.get("/reviews/queue", headers=auth).json()
        assert any(c["id"] == claim["id"] for c in queue)


def test_human_approve_settles():
    with TestClient(app) as client:
        auth = _signup(client)
        _make_policy(client, auth)
        claim = _submit(client, auth)
        out = client.post(f"/claims/{claim['id']}/review", headers=auth,
                          json={"decision": "approve", "reviewer": "adjuster-1"}).json()
        assert out["status"] == "settled"
        assert out["settled_amount"] == claim["recommendation"]["recommended_amount"]


def test_human_reject_does_not_settle():
    with TestClient(app) as client:
        auth = _signup(client)
        _make_policy(client, auth)
        claim = _submit(client, auth)
        out = client.post(f"/claims/{claim['id']}/review", headers=auth,
                          json={"decision": "reject", "reviewer": "adjuster-2"}).json()
        assert out["status"] == "rejected"
        assert out["settled_amount"] is None


def test_double_review_is_rejected():
    with TestClient(app) as client:
        auth = _signup(client)
        _make_policy(client, auth)
        claim = _submit(client, auth)
        client.post(f"/claims/{claim['id']}/review", headers=auth,
                    json={"decision": "approve", "reviewer": "a"})
        # A settled claim can't be reviewed again.
        second = client.post(f"/claims/{claim['id']}/review", headers=auth,
                             json={"decision": "approve", "reviewer": "b"})
        assert second.status_code == 409


def test_audit_trail_reconstructs_reasoning_chain():
    with TestClient(app) as client:
        auth = _signup(client)
        _make_policy(client, auth)
        claim = _submit(client, auth)
        client.post(f"/claims/{claim['id']}/review", headers=auth,
                    json={"decision": "approve", "reviewer": "adjuster-1", "notes": "ok"})
        chain = client.get(f"/claims/{claim['id']}/audit", headers=auth).json()
        steps = [e["step"] for e in chain]
        # Full ordered chain, ending with the human decision + settlement.
        assert steps[0] == "policy_verification"
        assert "fraud_scoring" in steps
        assert "recommendation" in steps
        assert "human_review" in steps
        assert steps[-1] == "settlement"
        # The human step is attributed to a human, the fraud step to the model.
        by = {e["step"]: e["decided_by"] for e in chain}
        assert by["human_review"] == "human"
        assert by["fraud_scoring"] == "model"


def test_tenant_isolation_on_claims():
    with TestClient(app) as client:
        a = _signup(client)
        b = _signup(client)
        _make_policy(client, a)
        claim = _submit(client, a)
        # Tenant B cannot see or review tenant A's claim.
        assert client.get(f"/claims/{claim['id']}", headers=b).status_code == 404
        assert client.post(f"/claims/{claim['id']}/review", headers=b,
                           json={"decision": "approve", "reviewer": "x"}).status_code == 404
