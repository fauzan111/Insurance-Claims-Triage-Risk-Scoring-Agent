"""Pydantic schemas — the structured contracts for claims, triage outputs, and
the human review gate."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class PolicyIn(BaseModel):
    policy_number: str = Field(..., min_length=1, max_length=64)
    holder_name: str = Field(..., min_length=1, max_length=255)
    coverage_type: str = Field(..., pattern="^(auto|home|health|travel)$")
    coverage_limit: float = Field(..., gt=0)
    deductible: float = Field(default=0.0, ge=0)
    start_date: date
    end_date: date
    active: bool = True


class ClaimIn(BaseModel):
    policy_number: str = Field(..., min_length=1, max_length=64)
    claim_type: str = Field(..., pattern="^(auto|home|health|travel)$")
    claim_amount: float = Field(..., gt=0)
    incident_date: date
    reported_date: date
    prior_claims_count: int = Field(default=0, ge=0)
    has_documentation: bool = True
    description: str | None = Field(default=None, max_length=4000)


class PolicyVerification(BaseModel):
    verified: bool
    reasons: list[str]          # every check outcome, human-readable
    covered_amount: float       # min(claim, limit) - deductible, clamped >= 0


class FraudAssessment(BaseModel):
    score: float = Field(..., ge=0, le=1)   # model probability
    band: str                                # low | medium | high
    top_factors: list[str]                   # which features drove the score
    model_version: str


class SettlementRecommendation(BaseModel):
    decision: str               # recommend_pay | recommend_review | recommend_deny
    recommended_amount: float   # deterministic (code), never LLM-computed
    reasoning: str              # human-readable rationale


class ReviewIn(BaseModel):
    decision: str = Field(..., pattern="^(approve|reject)$")
    reviewer: str = Field(..., min_length=1, max_length=128)
    notes: str | None = Field(default=None, max_length=2000)


class ClaimOut(BaseModel):
    id: str
    policy_number: str
    claim_type: str
    claim_amount: float
    status: str
    policy_verification: PolicyVerification | None
    fraud_assessment: FraudAssessment | None
    recommendation: SettlementRecommendation | None
    settled_amount: float | None


class AuditEntry(BaseModel):
    step: str
    actor: str
    decided_by: str
    reasoning: str
    data: dict | None
    created_at: str
