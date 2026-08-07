# ADR-006: Shadow Evaluation Before Policy Activation

- Status: Accepted
- Date: 2026-08-06
- Decision owners: RouteForge project
- Related milestones: M10

## Context

Updating feature policies (e.g. lowering quality thresholds or adding new candidate models) introduces operational risks to live application traffic.

## Decision

1. **Shadow Policy Pipeline:** RouteForge will support shadow evaluation (`Planned for M10`). New or modified feature policies can be deployed in shadow mode alongside the active production policy.
2. **Asynchronous Non-Blocking Evaluation:** Shadow routing decisions are calculated in parallel or asynchronously after request processing. They do NOT affect live request delivery or client responses.
3. **Audit Comparison:** Disagreements between active policy decisions and shadow policy decisions are logged to PostgreSQL for offline review and benchmark validation.
4. **Explicit Human Activation:** Policy promotion from shadow to active status requires explicit administrative activation.

## Alternatives Considered

* **Direct Production Replacement:** Immediately activating new policy versions in production. Rejected due to risk of unforeseen quality degradation or cost spikes.
* **Autonomous Reinforcement Learning Promotion:** Automatically promoting policies based on live metrics. Rejected due to strict project prohibition on autonomous policy mutations (`ADR-008`).

## Consequences

### Positive
* Enables safe validation of candidate policies against real production traffic workloads.
* Provides empirical telemetry on potential cost savings or quality differences before live deployment.
* Preserves zero risk to production client requests during testing.

### Negative and Trade-Offs
* Requires computing additional candidate evaluation decisions for shadowed requests.

## Revisit Conditions
* Automated canary deployment tooling introduced in post-V1 milestones.
