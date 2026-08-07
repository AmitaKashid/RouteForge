# ADR-004: Hard Policy-Constrained Lowest-Cost Routing

- Status: Accepted
- Date: 2026-08-06
- Decision owners: RouteForge project
- Related milestones: M1.5, M1.6

## Context

RouteForge must evaluate candidate models against multiple constraints (quality, latency, cost, capabilities, governance, provider health) and select an optimal target model.

## Decision

1. **Two-Stage Deterministic Pipeline:**
   - **Stage 1 (Hard Eligibility Filtering):** Every candidate model is evaluated against hard policy and request constraints via `evaluate_candidate`. Any violation produces explicit, stable rejection reasons (`MODEL_NOT_ALLOWED`, `CAPABILITY_MISMATCH`, `QUALITY_BELOW_THRESHOLD`, `LATENCY_ABOVE_TARGET`, `COST_ABOVE_REQUEST_LIMIT`, `GOVERNANCE_MISMATCH`, `PROVIDER_UNAVAILABLE`, `DEGRADED_STATE_NOT_ALLOWED`).
   - **Stage 2 (Lowest-Cost Selection):** Among candidates passing all hard constraints, `route_request` selects the candidate with the lowest `estimated_cost_usd` (`Decimal`).
2. **Deterministic Tie-Breaking:** Ties in cost are broken predictably by `model_id` ascending (`AGENTS.md` Rule 9).
3. **No Weighted Scoring in V1:** Quality, latency, and capability requirements are strict gating filters, not continuous weighted scoring objectives.

## Alternatives Considered

* **Weighted Utility Function:** Combining normalized cost, quality, and latency scores into a floating-point scalar (`score = w1*quality - w2*cost - w3*latency`). Rejected because weighted scores can trade off strict governance or latency requirements, introduce floating-point instability, and reduce auditability.
* **Cost-Only Routing:** Routing strictly by price without quality or governance thresholds. Rejected because enterprise features require quality guarantees and governance compliance.

## Consequences

### Positive
* 100% deterministic, auditable, and reproducible routing decisions.
* Hard policy and governance boundaries can never be breached by low-cost models.
* Predictable cost-optimization behavior that is easily understood by policy administrators.

### Negative and Trade-Offs
* Does not automatically pick a higher-quality model when cost is marginally higher, unless specified in quality constraints.

## Revisit Conditions
* Business requirements for soft optimization or probabilistic multi-objective trade-offs in post-V1 milestones.
