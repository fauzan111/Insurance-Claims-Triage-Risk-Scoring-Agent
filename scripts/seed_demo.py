"""Seed a policy + a low-risk and a high-risk claim, then show the review queue
and reconstruct one claim's audit trail.

    python scripts/seed_demo.py --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import urllib.request
import uuid


def _req(base_url, path, payload=None, token=None, method="POST"):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - local demo target
        return json.loads(resp.read())


def main(base_url: str) -> None:
    tenant = _req(base_url, "/tenants/signup", {"name": f"Demo Ins {uuid.uuid4().hex[:6]}"})
    token = tenant["access_token"]
    print(f"tenant: {tenant['tenant_id']}\n")

    _req(base_url, "/policies", {
        "policy_number": "POL-100", "holder_name": "Mario Rossi", "coverage_type": "auto",
        "coverage_limit": 20000, "deductible": 500,
        "start_date": "2026-01-01", "end_date": "2026-12-31", "active": True,
    }, token=token)

    claims = {
        "low-risk": {"policy_number": "POL-100", "claim_type": "auto", "claim_amount": 4000,
                     "incident_date": "2026-06-01", "reported_date": "2026-06-02",
                     "prior_claims_count": 0, "has_documentation": True},
        "high-risk": {"policy_number": "POL-100", "claim_type": "auto", "claim_amount": 19000,
                      "incident_date": "2026-01-05", "reported_date": "2026-03-20",
                      "prior_claims_count": 4, "has_documentation": False},
    }
    ids = {}
    for label, body in claims.items():
        c = _req(base_url, "/claims", body, token=token)
        f, r = c["fraud_assessment"], c["recommendation"]
        ids[label] = c["id"]
        print(f"{label:10} -> status={c['status']} fraud={f['score']} ({f['band']}) "
              f"rec={r['decision']} €{r['recommended_amount']}")

    queue = _req(base_url, "/reviews/queue", token=token, method="GET")
    print(f"\nreview queue: {len(queue)} claim(s) awaiting a MANDATORY human decision")

    # Approve the low-risk one and show it settles only after the human click.
    approved = _req(base_url, f"/claims/{ids['low-risk']}/review",
                    {"decision": "approve", "reviewer": "adjuster-1", "notes": "clean"},
                    token=token)
    print(f"\nafter human approve: status={approved['status']} "
          f"settled=€{approved['settled_amount']}")

    print("\n--- audit trail for the low-risk claim (explainability) ---")
    chain = _req(base_url, f"/claims/{ids['low-risk']}/audit", token=token, method="GET")
    for i, e in enumerate(chain, 1):
        print(f"{i}. [{e['decided_by']:6}] {e['step']}: {e['reasoning'][:80]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    main(parser.parse_args().base_url)
