# ADR-001: Python Language & FastAPI Framework Selection

- Status: Accepted
- Date: 2026-08-06
- Decision owners: RouteForge project
- Related milestones: M1, M2

## Context

RouteForge requires an ecosystem suited for implementing provider adapters, evaluation engines, routing algorithms, typed domain logic, asynchronous HTTP gateway endpoints, and analytical benchmark suites.

## Decision

1. **Python 3.12** is selected as the primary implementation language for the RouteForge repository.
2. **FastAPI** is selected as the planned HTTP web framework for Milestone M2 API routes.
3. Core domain contracts and routing logic must remain strictly decoupled from FastAPI web routing and Pydantic API schemas.

## Alternatives Considered

* **TypeScript / Node.js:** Strong async I/O performance, but weaker scientific/ML evaluation ecosystem and less standardized typing for numerical/financial data structures.
* **Go:** Excellent concurrency and compiled performance, but slower development iteration for complex multi-constraint evaluation rules and richer quality evaluation pipelines.
* **Polyglot Microservices:** Using Go for gateway proxying and Python for routing logic. Rejected due to microservice prohibition in V1 (`AGENTS.md` Rule 5).

## Consequences

### Positive
* Single unified ecosystem for provider integration, candidate evaluation, routing logic, and quality verification.
* Type safety enforced through Python 3.12 type annotations, `mypy` strict type checking, and dataclass invariants.
* Asynchronous execution support (`asyncio`) for provider requests and background tasks.

### Negative and Trade-Offs
* Lower raw I/O throughput compared to compiled Go proxies.
* Strict discipline required to prevent FastAPI or web framework details from leaking into core domain packages.

## Revisit Conditions
* Demonstrated CPU or I/O bottleneck in production gateway benchmarks that cannot be resolved via async I/O optimization.
* Architectural transition to multi-process or compiled gateway proxies in post-V1 milestones.
