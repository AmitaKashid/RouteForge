# ADR-008: Explicit Exclusion of Automatic Online Retraining

- Status: Accepted
- Date: 2026-08-06
- Decision owners: RouteForge project
- Related milestones: V1 Scope Non-Goal

## Context

Adaptive routing systems sometimes employ online reinforcement learning or autonomous feedback loops to adjust model selection weights dynamically based on real-time feedback.

## Decision

1. **Explicit V1 Non-Goal:** Autonomous online model retraining, online reinforcement learning routers, and automatic policy threshold adjustments are strictly prohibited in V1.
2. **Explicit Offline Updates:** Policy thresholds, quality profile ratings, and candidate models are modified strictly through versioned configurations (`PolicyVersion`, `ModelDefinition`) and human-driven deployments.
3. **Auditable Evaluation:** Quality verification failures are logged to PostgreSQL datasets for offline analysis, reproducible benchmark evaluation, and explicit human review.

## Rationale

* **Unstable Behavior:** Online learning algorithms can produce non-deterministic routing shifts that are impossible to reproduce or debug.
* **Audit & Governance Compliance:** Enterprise routing gateways must provide reproducible audit trails explaining why specific models were selected.
* **Feedback Loop Vulnerability:** Autonomous online updates are susceptible to feedback loops, adversarial prompt manipulation, or localized provider outages triggering global policy corruption.

## Alternatives Considered

* **Contextual Multi-Armed Bandits:** Dynamically shifting traffic weights to models with high reward signals. Rejected due to auditability concerns and policy predictability requirements.

## Consequences

### Positive
* 100% predictable, reproducible, and auditable routing decisions.
* Prevents runaway feedback loops or unexpected routing behavior shifts.
* Policy changes require explicit code or configuration commits with full version history.

### Negative and Trade-Offs
* Requires manual or scripted evaluation runs to update model quality profiles when providers upgrade models.

## Revisit Conditions
* Post-V1 research into offline batch retraining pipelines with formal approval gates.
