"""Audit-trail viewer — reconstructs the full ordered reasoning chain for a
claim. This is the EU AI Act explainability demo surface."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit import reconstruct_chain
from app.auth.tenant import TenantContext, get_tenant_context
from app.db.base import get_db
from app.db.models import Claim
from app.schemas import AuditEntry

router = APIRouter(tags=["audit"])


@router.get("/claims/{claim_id}/audit", response_model=list[AuditEntry])
def claim_audit(
    claim_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
) -> list[AuditEntry]:
    claim = db.get(Claim, claim_id)
    if claim is None or claim.tenant_id != ctx.tenant_id:  # tenant scoping
        raise HTTPException(status_code=404, detail="Claim not found")
    return reconstruct_chain(db, tenant_id=ctx.tenant_id, claim_id=claim_id)
