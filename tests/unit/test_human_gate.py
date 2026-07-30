"""The security-critical invariant: a claim can only be SETTLED through a
recorded human APPROVE. These tests attack the gate from several angles."""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.db.base import SessionLocal
from app.db.models import Claim, ClaimStatus, HumanReview, ReviewDecision, Tenant
from app.review import ReviewError, _execute_settlement, can_settle, submit_review


def _claim(db, tenant_id, status=ClaimStatus.PENDING_REVIEW) -> Claim:
    c = Claim(
        tenant_id=tenant_id, policy_number="P-1", claim_type="auto", claim_amount=1000.0,
        incident_date=date(2026, 1, 1), reported_date=date(2026, 1, 2),
        status=status, recommendation={"decision": "recommend_pay",
                                        "recommended_amount": 800.0, "reasoning": "ok"},
    )
    db.add(c)
    db.flush()
    return c


def _tenant(db) -> str:
    t = Tenant(name=f"ins-{uuid.uuid4()}")
    db.add(t)
    db.flush()
    return t.id


def test_cannot_settle_without_any_review():
    db = SessionLocal()
    try:
        tid = _tenant(db)
        claim = _claim(db, tid)
        # Directly attempt the private settlement path with no approval.
        with pytest.raises(ReviewError):
            _execute_settlement(db, claim=claim, tenant_id=tid, review=None)
        assert claim.status == ClaimStatus.PENDING_REVIEW  # unchanged
        assert claim.settled_amount is None
    finally:
        db.rollback()
        db.close()


def test_cannot_settle_with_a_reject_review():
    db = SessionLocal()
    try:
        tid = _tenant(db)
        claim = _claim(db, tid)
        reject = HumanReview(tenant_id=tid, claim_id=claim.id, reviewer="alice",
                             decision=ReviewDecision.REJECT)
        db.add(reject)
        db.flush()
        with pytest.raises(ReviewError):
            _execute_settlement(db, claim=claim, tenant_id=tid, review=reject)
        assert claim.status != ClaimStatus.SETTLED
    finally:
        db.rollback()
        db.close()


def test_cannot_settle_with_another_claims_approval():
    db = SessionLocal()
    try:
        tid = _tenant(db)
        claim_a = _claim(db, tid)
        claim_b = _claim(db, tid)
        approval_b = HumanReview(tenant_id=tid, claim_id=claim_b.id, reviewer="bob",
                                 decision=ReviewDecision.APPROVE)
        db.add(approval_b)
        db.flush()
        # An approval for claim B must not settle claim A.
        with pytest.raises(ReviewError):
            _execute_settlement(db, claim=claim_a, tenant_id=tid, review=approval_b)
    finally:
        db.rollback()
        db.close()


def test_approve_settles_and_records_amount():
    db = SessionLocal()
    try:
        tid = _tenant(db)
        claim = _claim(db, tid)
        submit_review(db, claim=claim, tenant_id=tid, reviewer="carol",
                      decision=ReviewDecision.APPROVE, notes="looks good")
        assert claim.status == ClaimStatus.SETTLED
        assert claim.settled_amount == 800.0
    finally:
        db.rollback()
        db.close()


def test_reject_does_not_settle():
    db = SessionLocal()
    try:
        tid = _tenant(db)
        claim = _claim(db, tid)
        submit_review(db, claim=claim, tenant_id=tid, reviewer="dave",
                      decision=ReviewDecision.REJECT, notes="suspicious")
        assert claim.status == ClaimStatus.REJECTED
        assert claim.settled_amount is None
    finally:
        db.rollback()
        db.close()


def test_can_settle_predicate():
    db = SessionLocal()
    try:
        tid = _tenant(db)
        claim = _claim(db, tid)
        assert can_settle(claim, None) is False
        approve = HumanReview(tenant_id=tid, claim_id=claim.id, reviewer="x",
                              decision=ReviewDecision.APPROVE)
        assert can_settle(claim, approve) is True
        # A matching-claim approval from ANOTHER tenant must not authorize settle.
        cross = HumanReview(tenant_id="other-tenant", claim_id=claim.id, reviewer="x",
                            decision=ReviewDecision.APPROVE)
        assert can_settle(claim, cross) is False
    finally:
        db.rollback()
        db.close()
