"""Aggregates benchmark JSONL results into versioned measured model profiles."""

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def calculate_median(values: list[int]) -> int:
    if not values:
        return 0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 1:
        return sorted_vals[n // 2]
    return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) // 2


def calculate_p95(values: list[int]) -> int:
    if not values:
        return 0
    sorted_vals = sorted(values)
    idx = min(math.ceil(len(sorted_vals) * 0.95) - 1, len(sorted_vals) - 1)
    return sorted_vals[idx]


def build_profiles(input_path: Path, output_path: Path) -> int:
    if not input_path.is_file():
        print(f"Error: Input JSONL file not found: {input_path}")
        return 1

    records: list[dict[str, Any]] = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    if not records:
        print("Error: Input benchmark results file is empty.")
        return 1

    # Group by (model_id, task_type)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in records:
        key = (r["routeforge_model_id"], r["task_type"])
        grouped.setdefault(key, []).append(r)

    profiles_data: dict[str, dict[str, Any]] = {}

    for (model_id, task_type), item_recs in grouped.items():
        succ_recs = [r for r in item_recs if r.get("success", True)]
        scores = [r["deterministic_quality_score"] for r in item_recs]
        passes = [1 if r.get("passed", False) else 0 for r in item_recs]
        latencies = [r["latency_ms"] for r in succ_recs if r["latency_ms"] >= 0]

        mean_quality = sum(scores) / len(scores) if scores else 0.0
        pass_rate = sum(passes) / len(passes) if passes else 0.0
        med_lat = calculate_median(latencies)
        p95_lat = calculate_p95(latencies)

        model_entry = profiles_data.setdefault(
            model_id,
            {"model_id": model_id, "task_profiles": {}},
        )

        model_entry["task_profiles"][task_type] = {
            "task_type": task_type,
            "measured_quality": round(mean_quality, 4),
            "measured_pass_rate": round(pass_rate, 4),
            "measured_median_latency_ms": med_lat,
            "measured_p95_latency_ms": p95_lat,
            "sample_count": len(item_recs),
            "benchmark_dataset_version": item_recs[0].get("benchmark_version", "routing_v1"),
            "evaluator_version": "v1",
            "source_benchmark_file": input_path.name,
        }

    registry_output = {
        "profile_version": "routing-profile-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "profiles": profiles_data,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(registry_output, f, indent=2)

    print(
        f"Successfully generated profile '{output_path.name}' at {output_path} "
        f"with {len(profiles_data)} model profiles."
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build measured RouteForge model profiles")
    parser.add_argument(
        "--input",
        default="benchmarks/results/two-model-baseline.jsonl",
        help="Input benchmark JSONL file path",
    )
    parser.add_argument(
        "--output",
        default="config/profiles/routing-profile-v1.json",
        help="Output profile JSON file path",
    )

    args = parser.parse_args()
    sys.exit(build_profiles(Path(args.input), Path(args.output)))


if __name__ == "__main__":
    main()
