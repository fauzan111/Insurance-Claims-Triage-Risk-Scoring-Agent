"""Human review API — the ONLY route that can settle or reject a claim."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.claims import to_claim_out
from app.auth.tenant import TenantContext, get_tenant_context
from app.db.base import get_db
from app.db.models import Claim, ClaimStatus, ReviewDecision
from app.review import ReviewError, submit_review
from app.schemas import ClaimOut, ReviewIn

router = APIRouter(tags=["review"])


@router.get("/reviews/queue", response_model=list[ClaimOut])
def review_queue(
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> list[ClaimOut]:
    """Claims awaiting a mandatory human decision."""
    rows = db.scalars(
        select(Claim).where(
            Claim.tenant_id == ctx.tenant_id, Claim.status == ClaimStatus.PENDING_REVIEW
        ).order_by(Claim.created_at.asc())
    ).all()
    return [to_claim_out(c) for c in rows]


@router.post("/claims/{claim_id}/review", response_model=ClaimOut)
def review_claim(
    claim_id: str,
    body: ReviewIn,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> ClaimOut:
    claim = db.get(Claim, claim_id)
    if claim is None or claim.tenant_id != ctx.tenant_id:  # tenant scoping
        raise HTTPException(status_code=404, detail="Claim not found")
    try:
        submit_review(
            db, claim=claim, tenant_id=ctx.tenant_id,
            reviewer=body.reviewer, decision=ReviewDecision(body.decision), notes=body.notes,
        )
    except ReviewError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StaleDataError as exc:
        # Another reviewer transitioned this claim concurrently; the loser aborts.
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Claim was reviewed concurrently; reload and retry"
        ) from exc
    db.refresh(claim)
    return to_claim_out(claim)
