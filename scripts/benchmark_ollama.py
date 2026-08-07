"""CLI benchmark runner executing Ollama baseline dataset."""

import argparse
import asyncio
import json
import statistics
import sys
from decimal import Decimal
from pathlib import Path

from routeforge.contracts import (
    AttemptId,
    Capability,
    ChatMessage,
    ChatRole,
    GovernanceClassification,
    ModelDefinition,
    ModelId,
    OutputFormat,
    ProviderId,
    ProviderRequest,
    QualityProfile,
    RequestId,
)
from routeforge.providers.errors import ProviderExecutionError
from routeforge.providers.ollama import OllamaProvider, OllamaProviderConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Ollama baseline benchmark suite against a target Ollama model."
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama3.2:latest",
        help="Ollama upstream model name to benchmark (default: llama3.2:latest)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama server base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="benchmarks/datasets/ollama_baseline.json",
        help="Path to baseline dataset JSON file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Optional output JSONL file path to store detailed results",
    )
    return parser


def parse_role(role_str: str) -> ChatRole:
    normalized = role_str.upper().strip()
    if normalized == "SYSTEM":
        return ChatRole.SYSTEM
    elif normalized == "ASSISTANT":
        return ChatRole.ASSISTANT
    return ChatRole.USER


async def run_benchmark(
    model_name: str,
    base_url: str,
    dataset_path: Path,
    output_path: Path | None,
) -> int:
    if not dataset_path.exists():
        print(f"Error: Dataset file '{dataset_path}' not found.", file=sys.stderr)
        return 1

    try:
        with open(dataset_path, encoding="utf-8") as f:
            cases = json.load(f)
    except Exception as err:
        print(f"Error: Failed to load dataset JSON: {err}", file=sys.stderr)
        return 1

    model_id = ModelId("benchmark-ollama-model")
    config = OllamaProviderConfig(
        base_url=base_url,
        model_names={model_id: model_name},
    )

    model_def = ModelDefinition(
        model_id=model_id,
        provider_id=ProviderId("ollama"),
        display_name=f"Ollama ({model_name})",
        capabilities=(Capability.TEXT_CHAT,),
        governance_allowed=(GovernanceClassification.PUBLIC,),
        context_window_tokens=8192,
        estimated_input_cost_per_million_tokens_usd=Decimal("0"),
        estimated_output_cost_per_million_tokens_usd=Decimal("0"),
        estimated_latency_ms=200,
        quality_profiles=(
            QualityProfile(
                task_type="general",
                predicted_quality=0.8,
                source="benchmark",
                version="v1",
            ),
        ),
        enabled=True,
        configuration_version="v1",
    )

    results: list[dict[str, object]] = []
    latencies: list[int] = []
    total_input_tokens = 0
    total_output_tokens = 0
    successful_requests = 0
    failed_requests = 0

    print("=== RouteForge Ollama Baseline Benchmark ===")
    print(f"Target Model: {model_name}")
    print(f"Server Base URL: {base_url}")
    print(f"Cases to execute: {len(cases)}\n")

    async with OllamaProvider(config=config) as provider:
        for idx, case in enumerate(cases, start=1):
            case_id = case.get("case_id", f"case-{idx}")
            category = case.get("category", "unknown")
            output_fmt_str = case.get("output_format", "TEXT").upper()
            output_format = OutputFormat.JSON if output_fmt_str == "JSON" else OutputFormat.TEXT

            messages = tuple(
                ChatMessage(
                    role=parse_role(m.get("role", "USER")),
                    content=m.get("content", ""),
                )
                for m in case.get("messages", [])
            )

            req = ProviderRequest(
                request_id=RequestId(f"bm_req_{idx}"),
                attempt_id=AttemptId(f"bm_att_{idx}"),
                model_id=model_id,
                messages=messages,
                output_format=output_format,
                timeout_ms=60000,
                idempotency_key=f"bm_key_{idx}",
            )

            try:
                resp = await provider.complete(req, model_def)
                successful_requests += 1
                latencies.append(resp.latency_ms)
                total_input_tokens += resp.usage.input_tokens
                total_output_tokens += resp.usage.output_tokens

                rec: dict[str, object] = {
                    "case_id": case_id,
                    "category": category,
                    "provider": "ollama",
                    "upstream_model": model_name,
                    "success": True,
                    "finish_reason": str(resp.finish_reason),
                    "latency_ms": resp.latency_ms,
                    "input_tokens": resp.usage.input_tokens,
                    "output_tokens": resp.usage.output_tokens,
                    "total_tokens": resp.usage.total_tokens,
                    "error_code": None,
                }
                results.append(rec)
                print(
                    f"[{idx}/{len(cases)}] {case_id} ({category}): SUCCESS "
                    f"- {resp.latency_ms}ms, in: {resp.usage.input_tokens}, "
                    f"out: {resp.usage.output_tokens}"
                )
            except ProviderExecutionError as err:
                failed_requests += 1
                rec = {
                    "case_id": case_id,
                    "category": category,
                    "provider": "ollama",
                    "upstream_model": model_name,
                    "success": False,
                    "finish_reason": None,
                    "latency_ms": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "error_code": str(err.error.code),
                }
                results.append(rec)
                print(
                    f"[{idx}/{len(cases)}] {case_id} ({category}): FAILED "
                    f"[{err.error.code}] {err.error.message}"
                )
            except Exception as err:
                failed_requests += 1
                rec = {
                    "case_id": case_id,
                    "category": category,
                    "provider": "ollama",
                    "upstream_model": model_name,
                    "success": False,
                    "finish_reason": None,
                    "latency_ms": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "error_code": "UNEXPECTED_ERROR",
                }
                results.append(rec)
                print(f"[{idx}/{len(cases)}] {case_id} ({category}): FAILED - {err}")

    print("\n=== Benchmark Summary ===")
    print(f"Successful Requests: {successful_requests} / {len(cases)}")
    print(f"Failed Requests:     {failed_requests} / {len(cases)}")
    print(f"Total Input Tokens:  {total_input_tokens}")
    print(f"Total Output Tokens: {total_output_tokens}")
    print(f"Total Tokens:        {total_input_tokens + total_output_tokens}")

    if latencies:
        sorted_lat = sorted(latencies)
        median_lat = statistics.median(sorted_lat)
        # Compute p95 index
        p95_idx = round(0.95 * (len(sorted_lat) - 1))
        p95_lat = sorted_lat[p95_idx]
        print(f"Median Latency:      {median_lat:.1f} ms")
        print(f"P95 Latency:         {p95_lat} ms")

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for rec in results:
                f.write(json.dumps(rec) + "\n")
        print(f"\nDetailed JSONL results saved to: {output_path}")

    return 0 if failed_requests == 0 else 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dataset_p = Path(args.dataset)
    output_p = Path(args.output) if args.output else None

    exit_code = asyncio.run(
        run_benchmark(
            model_name=args.model,
            base_url=args.base_url,
            dataset_path=dataset_p,
            output_path=output_p,
        )
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
