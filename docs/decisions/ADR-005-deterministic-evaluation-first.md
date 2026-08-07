# ADR-005: Deterministic Verification Before Probabilistic LLM Judging

- Status: Accepted
- Date: 2026-08-06
- Decision owners: RouteForge project
- Related milestones: M9

## Context

RouteForge plans an asynchronous quality verification pipeline (`Planned for M9`) to sample provider responses and verify output quality against policy expectations.

## Decision

1. **Deterministic-First Verification:** Quality verification must execute deterministic checks before invoking probabilistic LLM-as-a-judge evaluators.
2. **Deterministic Checks Include:**
   - JSON schema validation.
   - Exact-match regex patterns.
   - Non-empty output assertions.
   - Grounding and citation pattern checks.
   - Task-specific rule assertions.
3. **Probabilistic Fallback:** LLM-as-a-judge evaluation is invoked only if deterministic checks pass and qualitative assessment is required by policy.

## Alternatives Considered

* **LLM Judge Only:** Routing every sampled response to an LLM evaluator prompt. Rejected due to high financial cost, added latency, non-deterministic scoring variance, and potential judge model bias.
* **No Quality Verification:** Relying entirely on pre-computed benchmark quality profiles. Rejected because live output quality must be monitored for degradation.

## Consequences

### Positive
* Significantly lowers financial cost of verification pipelines by failing malformed responses deterministically.
* Eliminates judge model latency for structural or schema violations.
* Provides clear, reproducible verification failure reason codes.

### Negative and Trade-Offs
* Requires defining explicit schema or pattern expectations per feature policy.

## Revisit Conditions
* Advances in fast, low-cost local judging models making continuous probabilistic evaluation economical.
