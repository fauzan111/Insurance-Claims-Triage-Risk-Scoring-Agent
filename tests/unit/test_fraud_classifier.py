"""The fraud classifier is a real trained model, evaluated on features — not LLM
vibes. Tests assert it's deterministic and orders risk sensibly."""
from __future__ import annotations

from app.fraud.classifier import ClaimFeatures, band_for, get_classifier


def _clf():
    return get_classifier(seed=42)


def test_classifier_is_deterministic():
    a = _clf().score(ClaimFeatures(0.5, 400, 0, 0, 5)).score
    b = get_classifier(seed=42).score(ClaimFeatures(0.5, 400, 0, 0, 5)).score
    assert a == b  # same seed -> same trained model -> same score


def test_high_risk_scores_above_low_risk():
    clf = _clf()
    low = clf.score(ClaimFeatures(
        amount_to_limit_ratio=0.1, policy_age_days=900, prior_claims_count=0,
        missing_documentation=0, report_lag_days=1)).score
    high = clf.score(ClaimFeatures(
        amount_to_limit_ratio=1.2, policy_age_days=10, prior_claims_count=4,
        missing_documentation=1, report_lag_days=80)).score
    assert high > low
    assert 0.0 <= low <= 1.0 and 0.0 <= high <= 1.0


def test_top_factors_explainability():
    clf = _clf()
    result = clf.score(ClaimFeatures(
        amount_to_limit_ratio=1.3, policy_age_days=5, prior_claims_count=3,
        missing_documentation=1, report_lag_days=70))
    assert result.top_factors  # non-empty explanation for a risky claim
    assert all(isinstance(f, str) for f in result.top_factors)


def test_band_thresholds():
    assert band_for(0.05, review=0.3, high=0.6) == "low"
    assert band_for(0.4, review=0.3, high=0.6) == "medium"
    assert band_for(0.8, review=0.3, high=0.6) == "high"
