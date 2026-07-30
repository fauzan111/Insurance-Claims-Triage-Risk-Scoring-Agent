"""The mandatory human-review gate — the security-critical core of this project.

Design invariant: **a claim can only become SETTLED through a recorded human
approval.** There is exactly one function that settles a claim
(``_execute_settlement``), it is private to this module, and it refuses to run
unless it is handed a persisted :class:`HumanReview` with ``decision=APPROVE``
for that same claim. No pipeline node, API route, or default reaches SETTLED by
any other path. The reviewer's identity and notes are recorded, and the approval
is written to the audit trail.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.audit import record_step
from app.db.models import Claim, ClaimStatus, HumanReview, ReviewDecision


class ReviewError(RuntimeError):
    """Raised when a review action is not permitted (wrong state, etc.)."""


def submit_review(
    db: Session,
    *,
    claim: Claim,
    tenant_id: str,
    reviewer: str,
    decision: ReviewDecision,
    notes: str | None,
) -> HumanReview:
    """Record a human's decision and act on it. Approve -> execute settlement;
    reject -> mark the recommendation overruled. Both require a real reviewer."""
    if claim.status != ClaimStatus.PENDING_REVIEW:
        raise ReviewError(
            f"Claim is {claim.status.value}; only pending_review claims can be reviewed"
        )
    if not reviewer.strip():
        raise ReviewError("A reviewer identity is required (human oversight)")

    review = HumanReview(
        tenant_id=tenant_id, claim_id=claim.id, reviewer=reviewer.strip(),
        decision=decision, notes=notes,
    )
    db.add(review)
    db.flush()  # persist the review BEFORE any settlement can read it

    record_step(db, tenant_id=tenant_id, claim_id=claim.id, step="human_review",
                actor=reviewer.strip(), decided_by="human",
                reasoning=f"Human {decision.value} decision. Notes: {notes or '(none)'}",
                data={"review_id": review.id, "decision": decision.value})

    if decision is ReviewDecision.APPROVE:
        _execute_settlement(db, claim=claim, tenant_id=tenant_id, review=review)
    else:
        claim.status = ClaimStatus.REJECTED
        record_step(db, tenant_id=tenant_id, claim_id=claim.id, step="settlement",
                    actor="system", decided_by="code",
                    reasoning="Recommendation rejected by human; no settlement executed.")

    db.commit()
    return review


def _execute_settlement(
    db: Session, *, claim: Claim, tenant_id: str, review: HumanReview
) -> None:
    """THE only settlement path. Hard-guards on a matching APPROVE review.

    These guards are deliberately redundant with the caller: settlement is the
    one irreversible action, so it independently re-verifies authorization
    instead of trusting that it was called correctly.
    """
    if review is None or review.decision is not ReviewDecision.APPROVE:
        raise ReviewError("Settlement requires a human APPROVE review")
    if review.claim_id != claim.id or review.tenant_id != tenant_id:
        raise ReviewError("Approval does not match this claim/tenant")

    rec = claim.recommendation or {}
    # Amount is whatever code recommended (never recomputed by an LLM here).
    amount = float(rec.get("recommended_amount", 0.0))
    claim.settled_amount = amount
    claim.status = ClaimStatus.SETTLED
    record_step(db, tenant_id=tenant_id, claim_id=claim.id, step="settlement",
                actor="system", decided_by="code",
                reasoning=f"Settlement executed for €{amount} under human approval "
                          f"{review.id} by {review.reviewer}.",
                data={"settled_amount": amount, "approved_by": review.reviewer})


def can_settle(claim: Claim, review: HumanReview | None) -> bool:
    """Public predicate used by tests to assert the invariant: no approval =>
    no settlement, regardless of claim state."""
    return (
        review is not None
        and review.decision is ReviewDecision.APPROVE
        and review.claim_id == claim.id
        and review.tenant_id == claim.tenant_id
    )
