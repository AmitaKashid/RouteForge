# ADR-003: Logical Control-Plane and Data-Plane Separation

- Status: Accepted
- Date: 2026-08-06
- Decision owners: RouteForge project
- Related milestones: M1, M3, M7

## Context

Managing gateway configuration (policies, model definitions, governance rules) has different lifecycle, performance, and security requirements than routing live inference requests.

## Decision

1. **Logical Separation:** RouteForge enforces strict logical separation between Control-Plane operations (policy creation, versioning, activation, administrative configuration) and Data-Plane execution (request validation, candidate eligibility evaluation, model selection, provider execution).
2. **Modular Monolith Execution:** Both planes reside within the single core Python package (`src/routeforge`). Microservice decomposition is explicitly prohibited in V1 (`AGENTS.md` Rule 5).
3. **Immutable Policy Versioning:** The data plane consumes immutable snapshot versions (`PolicyVersion`). It never mutates policies or configuration state during request evaluation.

## Alternatives Considered

* **Undifferentiated Gateway Codebase:** Blending administrative CRUD endpoints and inference routing in shared modules. Rejected due to poor domain isolation and higher risk of regression.
* **Physical Microservice Split:** Deploying separate control-plane and data-plane microservices. Rejected due to operational complexity and V1 modular monolith architectural constraints.

## Consequences

### Positive
* Protects latency-critical inference routing paths from control-plane locks or database mutations.
* Guarantees reproducible, auditable routing decisions tied to immutable policy versions.
* Retains simple single-process deployment while preparing logical boundaries for future growth.

### Negative and Trade-Offs
* Requires disciplined package organization and strict import discipline.
* Requires explicit snapshot synchronization when active policies are updated.

## Revisit Conditions
* Scale or organizational security requirements dictating separate physical control-plane microservices in post-V1 milestones.
