"""Claims API: submit (auto-triages) + read. Every read is tenant-scoped."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.tenant import TenantContext, get_tenant_context
from app.config import get_settings
from app.db.base import get_db
from app.db.models import Claim, ClaimStatus
from app.pipeline import triage_claim
from app.runtime import get_fraud_classifier, get_llm_or_none
from app.schemas import (
    ClaimIn,
    ClaimOut,
    FraudAssessment,
    PolicyVerification,
    SettlementRecommendation,
)

router = APIRouter(prefix="/claims", tags=["claims"])


def to_claim_out(claim: Claim) -> ClaimOut:
    return ClaimOut(
        id=claim.id, policy_number=claim.policy_number, claim_type=claim.claim_type,
        claim_amount=claim.claim_amount, status=claim.status.value,
        policy_verification=(
            PolicyVerification(**claim.policy_verification)
            if claim.policy_verification else None
        ),
        fraud_assessment=(
            FraudAssessment(**claim.fraud_assessment) if claim.fraud_assessment else None
        ),
        recommendation=(
            SettlementRecommendation(**claim.recommendation) if claim.recommendation else None
        ),
        settled_amount=claim.settled_amount,
    )


@router.post("", response_model=ClaimOut)
def submit_claim(
    body: ClaimIn,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> ClaimOut:
    settings = get_settings()
    claim = Claim(
        tenant_id=ctx.tenant_id, policy_number=body.policy_number, claim_type=body.claim_type,
        claim_amount=body.claim_amount, incident_date=body.incident_date,
        reported_date=body.reported_date, prior_claims_count=body.prior_claims_count,
        has_documentation=body.has_documentation, description=body.description,
        status=ClaimStatus.SUBMITTED,
    )
    db.add(claim)
    db.commit()

    triage_claim(
        db, claim_id=claim.id, tenant_id=ctx.tenant_id,
        classifier=get_fraud_classifier(), llm=get_llm_or_none(),
        settlement_factor=settings.settlement_factor,
        review_threshold=settings.fraud_review_threshold,
        high_threshold=settings.fraud_high_threshold,
    )
    db.refresh(claim)
    return to_claim_out(claim)


@router.get("", response_model=list[ClaimOut])
def list_claims(
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> list[ClaimOut]:
    rows = db.scalars(
        select(Claim).where(Claim.tenant_id == ctx.tenant_id).order_by(Claim.created_at.desc())
    ).all()
    return [to_claim_out(c) for c in rows]


@router.get("/{claim_id}", response_model=ClaimOut)
def get_claim(
    claim_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> ClaimOut:
    claim = db.get(Claim, claim_id)
    if claim is None or claim.tenant_id != ctx.tenant_id:  # tenant scoping
        raise HTTPException(status_code=404, detail="Claim not found")
    return to_claim_out(claim)
