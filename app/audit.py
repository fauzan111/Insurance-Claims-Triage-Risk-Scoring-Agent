"""Audit-trail helpers: write one immutable step record, and reconstruct the
full ordered reasoning chain for a claim (the EU AI Act explainability view)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.schemas import AuditEntry


def record_step(
    db: Session,
    *,
    tenant_id: str,
    claim_id: str,
    step: str,
    actor: str,
    decided_by: str,
    reasoning: str,
    data: dict | None = None,
) -> None:
    db.add(AuditLog(
        tenant_id=tenant_id, claim_id=claim_id, step=step, actor=actor,
        decided_by=decided_by, reasoning=reasoning, data=data,
    ))


def reconstruct_chain(db: Session, *, tenant_id: str, claim_id: str) -> list[AuditEntry]:
    rows = db.scalars(
        select(AuditLog).where(
            AuditLog.tenant_id == tenant_id, AuditLog.claim_id == claim_id
        # Order by the monotonic id alone: it is the true insertion order and is
        # immune to any wall-clock adjustment between steps.
        ).order_by(AuditLog.id.asc())
    ).all()
    return [
        AuditEntry(
            step=r.step, actor=r.actor, decided_by=r.decided_by, reasoning=r.reasoning,
            data=r.data, created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]
