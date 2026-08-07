# AGENTS.md — Persistent Engineering Implementation Contract

This document forms the binding implementation contract for AI coding agents and human developers working on RouteForge.

## 1. Project Purpose

RouteForge is a quality-aware multi-provider LLM gateway. It routes requests across eligible language models based on quality, latency, cost, reliability, governance, and feature-policy constraints.

## 2. V1 Scope

The V1 release delivers a production-ready, deterministic gateway core with:
* OpenAI-compatible request and response routing interface
* Configurable model routing policies (quality thresholds, cost budgets, latency SLAs)
* Multi-provider adapters (e.g., OpenAI, Anthropic, OpenRouter)
* Durable control plane state stored in PostgreSQL
* Real-time operational state stored in Redis
* Fallback, retry, and circuit-breaker reliability semantics
* Team governance and rate limits
* Asynchronous quality verification and policy evaluation pipelines

## 3. Explicit V1 Non-Goals

The following are strictly out of scope for V1:
* Semantic caching or vector storage integrations
* Distributed tracing mesh or complex service-mesh wrappers
* Direct fine-tuning or model training workflows
* GUI dashboard or frontend user interfaces
* Speculative decoding or custom inference engine implementations

## 4. Milestone-Based Development

Development follows strict sequential milestones (M0 through M11). Features must be implemented ONLY within their designated milestone. Creating abstractions, placeholders, or code for future milestones before reaching them is prohibited.

## 5. Current Modular-Monolith Architecture

RouteForge is structured as a Python modular monolith using a `src/` layout (`src/routeforge`). Microservice decomposition is explicitly prohibited in V1. Every component must reside within the single core package.

## 6. Dependency Rules

Every new dependency must solve a demonstrated requirement and must be explicitly approved. Unused or speculative dependencies are forbidden. All runtime dependencies are declared in `pyproject.toml` and locked via `uv.lock`.

## 7. Domain-Layer Isolation Rules

Domain models, routing logic, and core invariants must remain strictly isolated from external framework details (such as HTTP routing or database drivers). Domain code must not depend on web frameworks or provider-specific SDKs.

## 8. Provider Isolation Rules

LLM providers (OpenAI, Anthropic, etc.) must be encapsulated behind clean interface contracts. Provider adapters must translate vendor-specific payloads into internal canonical representations. Core routing logic must remain vendor-agnostic.

## 9. Deterministic Routing Requirement

Given identical inputs, configuration, and system state, routing decisions must be strictly deterministic. Ties must be broken predictably using explicit, ordered rules.

## 10. Stable Machine-Readable Reason Codes

All routing decisions, rejections, fallbacks, and error conditions must emit stable, machine-readable reason codes (e.g., `MODEL_UNAVAILABLE`, `BUDGET_EXCEEDED`, `LATENCY_SLA_VIOLATED`). Free-text error strings must not be parsed for programmatic control flow.

## 11. PostgreSQL Durable-State Responsibility

PostgreSQL is the single source of truth for persistent control-plane state, including model metadata, provider configurations, routing policy rules, tenant API keys, and audit logs.

## 12. Redis Transient-State Responsibility

Redis handles high-frequency transient state only, including active rate-limit counters, provider health status, sliding-window latency samples, and circuit-breaker states.

## 13. Testing Expectations

All changes must include corresponding unit or integration tests under `tests/`. Test coverage across `src/routeforge` must remain at or above 90%. Tests must be deterministic and must not rely on live external services or network calls.

## 14. Central Validation Command

All code changes must pass the central validation command:
```bash
uv run python scripts/validate.py
```
This command runs formatting checks (`ruff format`), linting (`ruff check`), strict type checking (`mypy`), and test execution (`pytest`).

## 15. Documentation Update Expectations

Whenever architectural decisions, contracts, or milestone progress change, the corresponding documentation in `docs/` must be updated concurrently.

## 16. Secret-Handling Rules

Secrets, API keys, and private credentials must never be committed to source control or logged in raw outputs. Environment variables must be loaded via structured configuration layers.

## 17. No Invented Benchmark Claims

Performance, latency, or throughput claims must be backed by reproducible benchmark suites run within the repository. Synthetic claims or unsubstantiated metrics are strictly prohibited.

## 18. No Semantic Caching in V1

Semantic caching is explicitly excluded from V1. Routing logic must not incorporate vector similarity or prompt embedding caches.

## 19. No Implementation from Future Milestones

Do not implement or create empty placeholder packages/modules for future milestone features. Solve only the task at hand.

## 20. Updating CURRENT_STATE.md

## 21. Gateway-Specific Rules

1. API Pydantic models must remain isolated under `routeforge.gateway`.
2. Core domain contracts must remain strictly independent of Pydantic and FastAPI.
3. HTTP models and internal domain contracts must never be treated as the same object.
4. Translation between HTTP wire models and internal domain contracts must be explicit.
5. Unsupported API request parameters must be explicitly rejected, never silently ignored.
6. The external model parameter for API requests is the virtual model name `routeforge`.
7. External API clients do not choose backend models directly.
8. No HTTP route may return hardcoded inference output while appearing functional.
9. New HTTP endpoints require integration tests and OpenAPI schema verification.
10. Streaming, tool calling, and multimodal input remain explicitly excluded from V1.

---

*Every new service, dependency, database, abstraction, and package boundary must solve a demonstrated requirement.*

