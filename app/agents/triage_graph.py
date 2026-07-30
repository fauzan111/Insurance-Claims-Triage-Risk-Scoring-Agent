"""LangGraph triage agent: policy verification -> fraud scoring -> settlement
recommendation. The graph ALWAYS ends at a recommendation awaiting a human — it
has no node that approves or settles anything. That authority lives only in the
human-review path (``app/review.py``), by design.
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, StateGraph

from app.fraud.classifier import ClaimFeatures, FraudClassifier, band_for
from app.llm.client import LLMClient
from app.schemas import (
    FraudAssessment,
    PolicyVerification,
    SettlementRecommendation,
)
from app.settlement.recommender import recommend


class TriageState(TypedDict, total=False):
    verification: PolicyVerification
    features: ClaimFeatures
    fraud: FraudAssessment
    recommendation: SettlementRecommendation
    # config threaded through:
    settlement_factor: float
    review_threshold: float
    high_threshold: float


def _fraud_node(state: TriageState, classifier: FraudClassifier) -> TriageState:
    result = classifier.score(state["features"])
    band = band_for(result.score, review=state["review_threshold"], high=state["high_threshold"])
    fraud = FraudAssessment(
        score=result.score, band=band, top_factors=result.top_factors,
        model_version="fraud-logreg-v1",
    )
    return {**state, "fraud": fraud}


def _recommend_node(state: TriageState, llm: LLMClient | None) -> TriageState:
    rec = recommend(
        verification=state["verification"], fraud=state["fraud"],
        settlement_factor=state["settlement_factor"], llm=llm,
    )
    return {**state, "recommendation": rec}


def build_triage_graph(*, classifier: FraudClassifier, llm: LLMClient | None):
    graph = StateGraph(TriageState)
    # Node names must not collide with state keys ("fraud"/"recommendation").
    graph.add_node("score_fraud", lambda s: _fraud_node(s, classifier))
    graph.add_node("draft_recommendation", lambda s: _recommend_node(s, llm))
    graph.set_entry_point("score_fraud")
    graph.add_edge("score_fraud", "draft_recommendation")
    graph.add_edge("draft_recommendation", END)  # ends awaiting a human; never auto-acts
    return graph.compile()
