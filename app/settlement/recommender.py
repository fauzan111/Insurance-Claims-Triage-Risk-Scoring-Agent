"""Settlement recommendation — hybrid execution.

The **recommended amount is computed in code** (covered amount × factor), never
by the LLM. The LLM's only job is to phrase the human-readable reasoning; offline
it falls back to a deterministic template. And critically: a recommendation is a
*proposal only* — it is never executed here. Execution requires a human approval
(see ``app/review.py``).
"""
from __future__ import annotations

from app.llm.client import LLMClient
from app.schemas import FraudAssessment, PolicyVerification, SettlementRecommendation

_SYSTEM = (
    "You are an insurance claims analyst assistant. Given a claim's policy "
    "verification result, fraud risk band, and the code-computed recommended "
    "amount, write a concise 2-3 sentence rationale for the human reviewer. "
    "Do NOT change the amount. Do NOT make the final decision — a human will."
)


def recommend(
    *,
    verification: PolicyVerification,
    fraud: FraudAssessment,
    settlement_factor: float,
    llm: LLMClient | None,
) -> SettlementRecommendation:
    # --- Decision + amount are deterministic code ---
    if not verification.verified:
        decision = "recommend_deny"
        amount = 0.0
    elif fraud.band == "high":
        decision = "recommend_review"   # elevated fraud risk -> closer human look
        amount = round(verification.covered_amount * settlement_factor, 2)
    else:
        decision = "recommend_pay"
        amount = round(verification.covered_amount * settlement_factor, 2)

    reasoning = _draft_reasoning(verification, fraud, decision, amount, llm)
    return SettlementRecommendation(
        decision=decision, recommended_amount=amount, reasoning=reasoning
    )


def _draft_reasoning(
    verification: PolicyVerification,
    fraud: FraudAssessment,
    decision: str,
    amount: float,
    llm: LLMClient | None,
) -> str:
    if llm is None:
        return _template_reasoning(verification, fraud, decision, amount)
    prompt = (
        f"Policy verified: {verification.verified}. "
        f"Reasons: {'; '.join(verification.reasons)}. "
        f"Fraud band: {fraud.band} (score {fraud.score}); "
        f"factors: {', '.join(fraud.top_factors) or 'none'}. "
        f"Code-computed decision: {decision}; recommended amount: {amount}."
    )
    resp = llm.complete(system=_SYSTEM, prompt=prompt, max_tokens=200)
    return resp.text.strip() or _template_reasoning(verification, fraud, decision, amount)


def _template_reasoning(
    verification: PolicyVerification,
    fraud: FraudAssessment,
    decision: str,
    amount: float,
) -> str:
    if decision == "recommend_deny":
        return (
            "Policy verification failed ("
            + "; ".join(verification.reasons)
            + "). Recommend denial pending human review."
        )
    risk = f"Fraud risk is {fraud.band} (score {fraud.score})"
    if fraud.top_factors:
        risk += f", driven by: {', '.join(fraud.top_factors)}"
    verb = "closer review before payout" if decision == "recommend_review" else "payout"
    return (
        f"Policy verified; covered amount €{verification.covered_amount}. {risk}. "
        f"Recommend {verb} of €{amount}, subject to mandatory human approval."
    )
