# ADR-007: Explicit Exclusion of Semantic Caching in V1

- Status: Accepted
- Date: 2026-08-06
- Decision owners: RouteForge project
- Related milestones: V1 Scope Non-Goal

## Context

Semantic caching uses vector embeddings to match incoming prompts against cached historical responses, serving cached answers when vector similarity exceeds a defined similarity threshold.

## Decision

1. **Explicit V1 Non-Goal:** Semantic caching and vector database integration are strictly excluded from V1 scope (`AGENTS.md` Rule 3 & 18).
2. **Routing Isolation:** Core routing logic must not incorporate vector similarity or prompt embedding caches (`AGENTS.md` Rule 18).

## Rationale

* **False Match Risks:** Semantic similarity does not guarantee semantic equivalence. Small prompt variations (e.g. changing "DO NOT include PII" to "Include PII") can yield high vector similarity while requiring opposite responses.
* **Tenant & Governance Leakage:** Cached responses risk leaking confidential information across team boundaries or governance classifications.
* **Policy Version Invalidation:** Answers generated under previous policy versions or model definitions may violate newly active policy constraints.
* **Operational Complexity:** Managing vector databases, embedding model latency, similarity threshold tuning, and cache invalidation detracts from building a robust, deterministic LLM gateway core.

## Alternatives Considered

* **Exact-Match Caching:** Caching responses based on deterministic SHA-256 hashes of normalized requests. Deferred until post-V1 to prioritize core gateway resilience.
* **Vector Store Integration:** Adding Qdrant/Pinecone/Milvus adapters. Rejected for V1.

## Consequences

### Positive
* Keeps V1 architecture lean, deterministic, and security-isolated.
* Prevents data leaks across tenant governance boundaries.
* Ensures 100% of responses are evaluated against active policy constraints at request time.

### Negative and Trade-Offs
* Identical or semantically similar prompts incur standard model execution costs.

## Revisit Conditions
* Post-V1 architecture evaluation after core routing, resilience, and quality verification milestones are complete.
