"""Multi-tenant data model for the insurance claims-triage agent.

The :class:`Claim` status is a deliberate state machine that makes the human
review gate non-bypassable: triage can only move a claim to ``PENDING_REVIEW``;
only a recorded :class:`HumanReview` with decision APPROVE can move it to
``SETTLED``, and REJECT to ``REJECTED``. There is no column default or transition
that reaches ``SETTLED`` without an approval row.

Every step writes an :class:`AuditLog` row with its reasoning — the queryable
EU AI Act explainability trail.
"""
from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    policy_number: Mapped[str] = mapped_column(String(64), nullable=False)
    holder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # coverage_type: auto | home | health | travel
    coverage_type: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_limit: Mapped[float] = mapped_column(Float, nullable=False)
    deductible: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)

    __table_args__ = (Index("ix_policies_tenant_number", "tenant_id", "policy_number"),)


class ClaimStatus(str, enum.Enum):
    SUBMITTED = "submitted"
    PENDING_REVIEW = "pending_review"     # triage done; awaiting a MANDATORY human
    SETTLED = "settled"                   # human APPROVED the recommendation -> executed
    REJECTED = "rejected"                 # a human overruled the recommendation


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("policies.id"), nullable=True)

    policy_number: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    claim_amount: Mapped[float] = mapped_column(Float, nullable=False)
    incident_date: Mapped[date] = mapped_column(Date, nullable=False)
    reported_date: Mapped[date] = mapped_column(Date, nullable=False)
    prior_claims_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_documentation: Mapped[bool] = mapped_column(default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus), default=ClaimStatus.SUBMITTED, nullable=False
    )
    # Triage outputs (stored as JSON so a claim is self-describing).
    policy_verification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fraud_assessment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recommendation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    settled_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    # Optimistic lock: two concurrent reviews of the same claim can't both commit
    # (the loser raises StaleDataError), preventing double-settle / decision races.
    version_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    reviews: Mapped[list[HumanReview]] = relationship(back_populates="claim")

    __mapper_args__ = {"version_id_col": version_id}
    __table_args__ = (Index("ix_claims_tenant_status", "tenant_id", "status"),)


class ReviewDecision(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"


class HumanReview(Base):
    """The mandatory oversight record. Its existence with decision=APPROVE is the
    ONLY thing that authorizes a settlement. Immutable by convention."""

    __tablename__ = "human_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(128), nullable=False)  # human identity
    decision: Mapped[ReviewDecision] = mapped_column(Enum(ReviewDecision), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    claim: Mapped[Claim] = relationship(back_populates="reviews")

    __table_args__ = (Index("ix_reviews_tenant_claim", "tenant_id", "claim_id"),)


class AuditLog(Base):
    """Immutable-by-convention record of a single step's reasoning. The full
    ordered set for a claim reconstructs the EU AI Act explainability chain."""

    __tablename__ = "audit_logs"

    # Monotonic integer id so the ordered reasoning chain reflects true insertion
    # order even when many steps share the same timestamp within one commit.
    # with_variant(Integer, sqlite) so SQLite uses INTEGER (rowid autoincrement);
    # Postgres keeps BIGINT.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    claim_id: Mapped[str | None] = mapped_column(ForeignKey("claims.id"), nullable=True)
    step: Mapped[str] = mapped_column(String(64), nullable=False)  # policy_verification, fraud, ...
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(16), nullable=False)  # llm|code|model|human
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # structured step output
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_audit_tenant_claim_created", "tenant_id", "claim_id", "created_at"),
    )
