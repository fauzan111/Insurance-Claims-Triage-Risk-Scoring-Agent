"""Triage pipeline: policy verification -> fraud scoring -> recommendation.

It ends by placing the claim in ``PENDING_REVIEW``. It NEVER settles, approves,
or rejects — those transitions exist only in ``app/review.py`` behind a recorded
human decision. Each step writes an audit record with its reasoning.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.triage_graph import build_triage_graph
from app.audit import record_step
from app.db.models import Claim, ClaimStatus, Policy
from app.fraud.classifier import ClaimFeatures, FraudClassifier
from app.llm.client import LLMClient
from app.policy.verifier import verify_policy


def _build_features(claim: Claim, policy: Policy | None) -> ClaimFeatures:
    limit = policy.coverage_limit if policy else claim.claim_amount
    ratio = claim.claim_amount / limit if limit > 0 else 1.0
    policy_age = (claim.incident_date - policy.start_date).days if policy else 0
    report_lag = max(0, (claim.reported_date - claim.incident_date).days)
    return ClaimFeatures(
        amount_to_limit_ratio=round(ratio, 4),
        policy_age_days=max(0, policy_age),
        prior_claims_count=claim.prior_claims_count,
        missing_documentation=0 if claim.has_documentation else 1,
        report_lag_days=report_lag,
    )


def triage_claim(
    db: Session,
    *,
    claim_id: str,
    tenant_id: str,
    classifier: FraudClassifier,
    llm: LLMClient | None,
    settlement_factor: float,
    review_threshold: float,
    high_threshold: float,
) -> None:
    claim = db.get(Claim, claim_id)
    if claim is None or claim.tenant_id != tenant_id:
        return
    if claim.status != ClaimStatus.SUBMITTED:
        return  # idempotent: only a freshly submitted claim is triaged

    policy = (
        db.query(Policy)
        .filter(Policy.tenant_id == tenant_id, Policy.policy_number == claim.policy_number)
        .one_or_none()
    )
    if policy is not None:
        claim.policy_id = policy.id

    # 1. Deterministic policy verification.
    verification = verify_policy(claim, policy)
    claim.policy_verification = verification.model_dump()
    record_step(db, tenant_id=tenant_id, claim_id=claim.id, step="policy_verification",
                actor="policy-verifier", decided_by="code",
                reasoning="; ".join(verification.reasons), data=verification.model_dump())

    # 2. Trained-model fraud scoring + 3. recommendation (via the graph).
    features = _build_features(claim, policy)
    graph = build_triage_graph(classifier=classifier, llm=llm)
    final = graph.invoke({
        "verification": verification, "features": features,
        "settlement_factor": settlement_factor,
        "review_threshold": review_threshold, "high_threshold": high_threshold,
    })
    fraud = final["fraud"]
    rec = final["recommendation"]

    claim.fraud_assessment = fraud.model_dump()
    record_step(db, tenant_id=tenant_id, claim_id=claim.id, step="fraud_scoring",
                actor="fraud-classifier", decided_by="model",
                reasoning=f"score {fraud.score} ({fraud.band}); factors: "
                          + (", ".join(fraud.top_factors) or "none"),
                data=fraud.model_dump())

    claim.recommendation = rec.model_dump()
    record_step(db, tenant_id=tenant_id, claim_id=claim.id, step="recommendation",
                actor="settlement-recommender",
                decided_by="llm" if llm is not None else "code",
                reasoning=rec.reasoning, data=rec.model_dump())

    # 4. Hand to the MANDATORY human gate. No auto-action.
    claim.status = ClaimStatus.PENDING_REVIEW
    record_step(db, tenant_id=tenant_id, claim_id=claim.id, step="await_human_review",
                actor="system", decided_by="code",
                reasoning="Triage complete. Recommendation requires human approval "
                          "before any settlement action.")
    db.commit()
