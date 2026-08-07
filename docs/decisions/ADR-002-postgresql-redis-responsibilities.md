# ADR-002: PostgreSQL Durable State & Redis Transient State Separation

- Status: Accepted
- Date: 2026-08-06
- Decision owners: RouteForge project
- Related milestones: M3, M4, M8

## Context

RouteForge manages both persistent control-plane state (model definitions, feature policies, audit logs, team configurations) and high-frequency real-time operational state (rate-limit counters, circuit-breaker states, sliding-window latency samples).

## Decision

1. **PostgreSQL** (`Planned for M3`) is the single source of truth for all persistent, durable control-plane state, including model metadata, feature policies, policy versions, team API keys, cost records, and audit decision logs (`AGENTS.md` Rule 11).
2. **Redis** (`Planned for M4` / `M8`) handles high-frequency transient state only, including active rate-limit sliding windows, provider health status, sliding-window latency samples, and circuit-breaker states (`AGENTS.md` Rule 12).
3. Neither PostgreSQL nor Redis is implemented in M1; M1 uses in-memory registries and local JSON configuration.

## Alternatives Considered

* **PostgreSQL Only:** Storing active rate-limit counters and health states in PostgreSQL tables. Rejected due to high write-amplification and lock contention on latency-sensitive request paths.
* **Redis as Primary Database:** Storing durable policies and audit logs in Redis with persistence enabled. Rejected due to relational query limitations for audit reporting and weaker ACID transaction guarantees.
* **Event-Streaming Platform (Kafka / RabbitMQ):** Adding a messaging broker for operational telemetry. Rejected to maintain a restrained V1 architecture.

## Consequences

### Positive
* Clear operational division: relational ACID guarantees for critical configuration and financial records; in-memory speed for transient counters.
* Prevents Redis cache evictions or memory pressure from losing audit or governance history.
* Simplifies backup and disaster recovery.

### Negative and Trade-Offs
* Requires managing two separate storage systems in deployment environments.
* Requires cache invalidation strategy when control-plane updates occur in PostgreSQL.

## Revisit Conditions
* Operational scale requiring distributed event buses for asynchronous telemetry ingest.
* Multi-region active-active deployment requirements.
