"""Policy verification — deterministic rule engine.

Every check here is binary-correct code: is the policy active, is the claim type
covered, was the incident within the coverage period, is the amount within the
limit. The LLM is *not* trusted to decide coverage. (An optional LLM hook exists
for interpreting genuinely ambiguous free-text policy language, but it can only
add advisory notes — it never overrides a deterministic failure.)
"""
from __future__ import annotations

from app.db.models import Claim, Policy
from app.schemas import PolicyVerification


def verify_policy(claim: Claim, policy: Policy | None) -> PolicyVerification:
    reasons: list[str] = []
    ok = True

    if policy is None:
        return PolicyVerification(
            verified=False,
            reasons=[f"No policy found for number {claim.policy_number}"],
            covered_amount=0.0,
        )

    if not policy.active:
        ok = False
        reasons.append("Policy is not active")
    else:
        reasons.append("Policy is active")

    if claim.claim_type != policy.coverage_type:
        ok = False
        reasons.append(
            f"Claim type '{claim.claim_type}' not covered by '{policy.coverage_type}' policy"
        )
    else:
        reasons.append(f"Claim type '{claim.claim_type}' is covered")

    if not (policy.start_date <= claim.incident_date <= policy.end_date):
        ok = False
        reasons.append(
            f"Incident date {claim.incident_date} outside coverage "
            f"{policy.start_date}..{policy.end_date}"
        )
    else:
        reasons.append("Incident date within coverage period")

    if claim.claim_amount > policy.coverage_limit:
        # Not an automatic rejection: claims can exceed the limit and be paid up
        # to it, but we flag it.
        reasons.append(
            f"Claim amount {claim.claim_amount} exceeds limit {policy.coverage_limit} "
            "(payout capped at limit)"
        )

    covered = min(claim.claim_amount, policy.coverage_limit) - policy.deductible
    covered_amount = max(0.0, round(covered, 2))
    if ok and covered_amount <= 0:
        reasons.append("Covered amount is zero after deductible")

    return PolicyVerification(verified=ok, reasons=reasons, covered_amount=covered_amount)
