# Architecture Decision Records (ADRs)

This directory contains the formal Architecture Decision Records for the RouteForge project.

## Index of Decisions

| ADR ID | Title | Status | Related Milestones | Summary |
| :--- | :--- | :---: | :---: | :--- |
| [ADR-001](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/decisions/ADR-001-python-fastapi.md) | Python Language & FastAPI Framework Selection | Accepted | M1, M2 | Standardizes on Python 3.12 for domain logic and FastAPI for planned M2 HTTP API endpoints. |
| [ADR-002](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/decisions/ADR-002-postgresql-redis-responsibilities.md) | PostgreSQL Durable State & Redis Transient State Separation | Accepted | M3, M4, M8 | Establishes PostgreSQL for durable control-plane state and Redis strictly for high-frequency transient operational state. |
| [ADR-003](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/decisions/ADR-003-control-data-plane-separation.md) | Logical Control-Plane and Data-Plane Separation | Accepted | M1, M3, M7 | Enforces logical boundary between policy management and latency-sensitive inference request routing inside a modular monolith. |
| [ADR-004](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/decisions/ADR-004-policy-constrained-routing.md) | Hard Policy-Constrained Lowest-Cost Routing | Accepted | M1.5, M1.6 | Filters candidate models through hard constraint eligibility gates before selecting the lowest-cost model. |
| [ADR-005](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/decisions/ADR-005-deterministic-evaluation-first.md) | Deterministic Verification Before Probabilistic LLM Judging | Accepted | M9 | Requires deterministic rules (schema, regex, assertions) prior to invoking costlier probabilistic LLM-as-a-judge verification. |
| [ADR-006](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/decisions/ADR-006-shadow-before-activation.md) | Shadow Evaluation Before Policy Activation | Accepted | M10 | Evaluates new candidate feature policies in parallel shadow mode before promoting them to active status. |
| [ADR-007](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/decisions/ADR-007-no-semantic-caching-v1.md) | Explicit Exclusion of Semantic Caching in V1 | Accepted | V1 Scope | Excludes vector storage and semantic prompt caching from V1 to prevent false matches, stale responses, and security leaks. |
| [ADR-008](file:///c:/Users/Admin/.gemini/antigravity-ide/scratch/RouteForge/docs/decisions/ADR-008-no-online-retraining.md) | Explicit Exclusion of Automatic Online Retraining | Accepted | V1 Scope | Prohibits autonomous online reinforcement learning routing to guarantee predictable, auditable, and stable behavior. |
