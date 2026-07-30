# Insurance Claims Triage & Risk Scoring Agent

A multi-step agent that triages an incoming insurance claim: it verifies policy
details, scores fraud risk with a **trained classifier**, and drafts a settlement
recommendation — with a **mandatory, non-bypassable human review gate** before any
recommendation becomes an action, and a full, queryable audit trail of every
step's reasoning. This is the project that proves **regulated** AI deployment, not
just AI deployment.

Built on [`agent-platform-foundation`](../agent-platform-foundation) — same
multi-tenancy, audit-log, provider-agnostic-LLM, and observability spine.

## The non-bypassable human gate (the star)

> **A claim can only become `SETTLED` through a recorded human `APPROVE`.**
>
> There is exactly one function that settles a claim (`_execute_settlement` in
> `app/review.py`); it is private to that module and refuses to run unless handed
> a persisted `HumanReview` with `decision=APPROVE` for that same claim and
> tenant. The triage pipeline (`app/pipeline.py`) can only move a claim to
> `PENDING_REVIEW`; no graph node, route, or column default reaches `SETTLED` by
> any other path. `tests/unit/test_human_gate.py` attacks this from every angle
> (no review, a reject review, another claim's approval) and proves the claim
> stays unsettled.

## Hybrid execution across the pipeline

| Step | Who decides | Why |
|---|---|---|
| Policy verification | **Code** (rule engine) | Coverage/limits/dates are binary-correct facts |
| Fraud risk | **Trained model** (scikit-learn) | Evidence-based, not LLM vibes |
| Settlement amount | **Code** | Money is never LLM-computed |
| Recommendation wording | **LLM** (optional) | Language only; offline template fallback |
| Final action | **Human** | Mandatory oversight; nothing auto-executes |

## Evidence-based fraud scoring

Fraud risk is a real `LogisticRegression` (`app/fraud/classifier.py`) trained on a
synthetic-but-pattern-realistic claims dataset with features an actuary would
recognise: claim-to-limit ratio, policy recency, prior-claims count, missing
documentation, and incident-to-report lag. It's trained with a fixed seed so it's
reproducible and testable (a blatantly risky claim scores above a clean one), and
it exposes the **top factors** that drove each score for explainability. The LLM
is never asked "is this fraud?".

## Audit trail = EU AI Act explainability

Every step writes an immutable `AuditLog` row (step, actor, `decided_by`,
reasoning, structured data). `GET /claims/{id}/audit` reconstructs the full,
ordered reasoning chain — policy check → fraud score → recommendation → human
decision → settlement — attributing each step to `code` / `model` / `llm` /
`human`. This is the demo surface for "explain how this decision was reached".

## Architecture

```
Claim submitted
   → Policy verification   [code rule engine]           → audit
   → Fraud scoring         [trained classifier]          → audit
   → Settlement recommendation  [code amount + LLM/text] → audit
   → PENDING_REVIEW  ── MANDATORY human gate ──┐
        approve → settlement executed [code]    │  no auto-action anywhere
        reject  → recommendation overruled      │
   → every step immutably logged with its reasoning
```

## Compliance note — EU AI Act mapping

*(Engineering perspective, not legal advice — the point is that the system was
designed with the regime in mind.)*

- **Likely risk classification.** An AI system used by an insurer to assess risk
  and inform claim/settlement decisions about natural persons falls in the
  **high-risk** family under the EU AI Act (Annex III includes risk assessment
  and pricing in insurance; claims triage that influences payout decisions is
  adjacent and best treated as high-risk).
- **What high-risk obligations this build addresses, and how:**
  - *Human oversight (Art. 14)* — the non-bypassable review gate; no settlement
    without a recorded human `APPROVE`, with reviewer identity retained.
  - *Record-keeping / logging (Art. 12)* — immutable, per-step `AuditLog`; the
    full reasoning chain is reconstructable per claim.
  - *Transparency & explainability (Art. 13)* — fraud "top factors" and the audit
    viewer explain each decision in human terms.
  - *Accuracy & robustness (Art. 15)* — deterministic rules for coverage/money; a
    trained, reproducible model for risk; automated tests pinning both.
  - *Data governance* — multi-tenant isolation; prompts/PII minimised in logs.
- **Not claimed:** this is not a conformity assessment or a CE marking. It is a
  demonstration that the required controls were designed and built.

## Runs fully offline (no API key)

The fraud model is trained in-process (fixed seed, ~1s). No LLM key → the
recommendation reasoning uses a deterministic template. So the whole pipeline
runs from one container with zero secrets.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest tests/unit -q            # 23 tests, no external services

make run                        # http://localhost:8000  (offline)
make demo                       # policy + low/high-risk claims + approve + audit trail

docker compose up --build       # full stack with Postgres + Redis
```

Open **http://localhost:8000/**: create the demo policy, submit a low- or
high-risk claim (watch the fraud band + recommendation), then **approve or reject**
from the review queue, and click **Audit** to see the full reasoning chain.

### API

| Method | Path | Purpose |
|---|---|---|
| POST | `/tenants/signup` | Create a tenant; returns a token |
| POST | `/policies` | Create a policy |
| POST | `/claims` | Submit a claim (auto-triaged to `pending_review`) |
| GET  | `/reviews/queue` | Claims awaiting a mandatory human decision |
| POST | `/claims/{id}/review` | The ONLY settle/reject path (needs a reviewer) |
| GET  | `/claims/{id}/audit` | Reconstruct the full reasoning chain |
| GET  | `/health` | Liveness |

## Deploy live (Render, one blueprint)

The repo ships a [`render.yaml`](./render.yaml): **New → Blueprint → connect this
repo → Apply**. Add `ANTHROPIC_API_KEY` for LLM-drafted rationales in the
Environment tab (the fraud model runs regardless).

> Free-tier notes: the web service sleeps after ~15 min idle (~30s cold start);
> free Postgres expires after 90 days.

## Tech stack

Python 3.12 · FastAPI · LangGraph · scikit-learn · SQLAlchemy · Celery/Redis ·
structlog · Docker Compose · GitHub Actions · pytest.
