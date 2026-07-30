"""Evidence-based fraud scoring — a trained classifier, not LLM judgment.

A scikit-learn ``LogisticRegression`` is trained (fixed seed, reproducible) on a
synthetic-but-pattern-realistic claims dataset. Fraud risk is a learned function
of concrete features an actuary would recognise — how large the claim is versus
the policy limit, how soon after the policy started the incident occurred, the
claimant's prior-claims history, whether documentation is present, and the lag
between incident and report. The LLM is never asked "is this fraud?"; it only
drafts human-readable reasoning downstream.

The model trains in-memory on first use and is cached. Deterministic, so a given
claim always gets the same score and tests can assert ordering (a blatantly
risky claim scores higher than a clean one).
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from sklearn.linear_model import LogisticRegression

MODEL_VERSION = "fraud-logreg-v1"

# Feature order is the public contract between training and scoring.
FEATURE_NAMES = [
    "amount_to_limit_ratio",   # higher -> riskier
    "policy_age_days",         # lower (very recent policy) -> riskier
    "prior_claims_count",      # higher -> riskier
    "missing_documentation",   # 1 if no docs -> riskier
    "report_lag_days",         # longer delay to report -> riskier
]

# Human-readable descriptions for the "top factors" explanation.
_FACTOR_TEXT = {
    "amount_to_limit_ratio": "claim is large relative to the policy limit",
    "policy_age_days": "incident occurred soon after the policy started",
    "prior_claims_count": "claimant has multiple prior claims",
    "missing_documentation": "supporting documentation is missing",
    "report_lag_days": "long delay between incident and report",
}


@dataclass
class ClaimFeatures:
    amount_to_limit_ratio: float
    policy_age_days: int
    prior_claims_count: int
    missing_documentation: int  # 0/1
    report_lag_days: int

    def vector(self) -> list[float]:
        return [
            self.amount_to_limit_ratio,
            float(self.policy_age_days),
            float(self.prior_claims_count),
            float(self.missing_documentation),
            float(self.report_lag_days),
        ]


def _generate_training_data(seed: int, n: int = 5000) -> tuple[np.ndarray, np.ndarray]:
    """Synthetic claims whose fraud label follows a realistic latent risk model.

    The classifier then *learns* this relationship from data — it isn't given the
    rule. Features and the label-generating logic are intentionally separated by
    logistic noise so the fit is a real (imperfect) model, not a lookup table.
    """
    rng = np.random.default_rng(seed)

    ratio = rng.beta(2, 5, n) * 1.4           # mostly < 1, occasional over-limit
    policy_age = rng.integers(1, 1500, n)      # days since policy start
    prior = rng.poisson(0.6, n)                # prior claims count
    missing = rng.binomial(1, 0.18, n)         # missing docs ~18%
    lag = rng.integers(0, 90, n)               # report lag days

    # Latent fraud propensity (the pattern the model must recover).
    z = (
        -2.3
        + 2.4 * ratio
        + 1.1 * missing
        + 0.45 * prior
        + 0.9 * (policy_age < 60)              # brand-new policy is a red flag
        + 0.02 * lag
    )
    prob = 1 / (1 + np.exp(-z))
    y = (rng.random(n) < prob).astype(int)

    x = np.column_stack([ratio, policy_age, prior, missing, lag]).astype(float)
    return x, y


class FraudClassifier:
    def __init__(self, seed: int) -> None:
        x, y = _generate_training_data(seed)
        # class_weight balances the (minority) fraud class so scores spread out.
        self._model = LogisticRegression(max_iter=1000, class_weight="balanced")
        with warnings.catch_warnings():
            # Benign scipy/sklearn version chatter ("Unknown solver options").
            warnings.simplefilter("ignore")
            self._model.fit(x, y)
        self._means = x.mean(axis=0)
        self._stds = x.std(axis=0) + 1e-9

    def score(self, feats: ClaimFeatures) -> FraudAssessmentResult:
        x = np.array([feats.vector()], dtype=float)
        prob = float(self._model.predict_proba(x)[0, 1])
        factors = self._top_factors(feats)
        return FraudAssessmentResult(score=round(prob, 4), top_factors=factors)

    def _top_factors(self, feats: ClaimFeatures) -> list[str]:
        """Explainability: the features that pushed this claim's score up most,
        by standardized contribution (coef * z-score)."""
        x = np.array(feats.vector(), dtype=float)
        z = (x - self._means) / self._stds
        contrib = self._model.coef_[0] * z
        ranked = sorted(
            zip(FEATURE_NAMES, contrib, strict=True), key=lambda t: t[1], reverse=True
        )
        return [_FACTOR_TEXT[name] for name, c in ranked if c > 0][:3]


@dataclass
class FraudAssessmentResult:
    score: float
    top_factors: list[str]


def band_for(score: float, *, review: float, high: float) -> str:
    if score >= high:
        return "high"
    if score >= review:
        return "medium"
    return "low"


@lru_cache
def get_classifier(seed: int) -> FraudClassifier:
    return FraudClassifier(seed)
