"""Deterministic policy verification rules."""
from __future__ import annotations

from datetime import date

from app.db.models import Claim, ClaimStatus, Policy
from app.policy.verifier import verify_policy


def _policy(**kw) -> Policy:
    base = dict(
        tenant_id="t", policy_number="P-1", holder_name="H", coverage_type="auto",
        coverage_limit=10000.0, deductible=500.0,
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), active=True,
    )
    base.update(kw)
    return Policy(**base)


def _claim(**kw) -> Claim:
    base = dict(
        tenant_id="t", policy_number="P-1", claim_type="auto", claim_amount=2000.0,
        incident_date=date(2026, 6, 1), reported_date=date(2026, 6, 3),
        status=ClaimStatus.SUBMITTED,
    )
    base.update(kw)
    return Claim(**base)


def test_valid_claim_verifies_and_computes_covered_amount():
    v = verify_policy(_claim(), _policy())
    assert v.verified is True
    assert v.covered_amount == 1500.0  # min(2000, 10000) - 500 deductible


def test_missing_policy_fails():
    v = verify_policy(_claim(), None)
    assert v.verified is False
    assert v.covered_amount == 0.0


def test_inactive_policy_fails():
    v = verify_policy(_claim(), _policy(active=False))
    assert v.verified is False
    assert any("not active" in r for r in v.reasons)


def test_wrong_coverage_type_fails():
    v = verify_policy(_claim(claim_type="home"), _policy(coverage_type="auto"))
    assert v.verified is False
    assert any("not covered" in r for r in v.reasons)


def test_incident_outside_period_fails():
    v = verify_policy(_claim(incident_date=date(2025, 12, 1)), _policy())
    assert v.verified is False
    assert any("outside coverage" in r for r in v.reasons)


def test_amount_over_limit_caps_but_still_verifies():
    v = verify_policy(_claim(claim_amount=50000.0), _policy(coverage_limit=10000.0))
    assert v.verified is True
    assert v.covered_amount == 9500.0  # capped at limit minus deductible
    assert any("exceeds limit" in r for r in v.reasons)
