"""CLI smoke-test script for direct Ollama provider verification."""

import argparse
import asyncio
import json
import sys
from decimal import Decimal

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
        description="Smoke test direct execution against an Ollama server instance."
    )
    parser.add_argument(
        "--model",
        type=str,
        default="llama3.2:latest",
        help="Ollama upstream model name to test (default: llama3.2:latest)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama server base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="Explain deterministic LLM routing in one short sentence.",
        help="Test prompt message to send",
    )
    return parser


async def run_smoke_test(model_name: str, base_url: str, prompt: str) -> int:
    model_id = ModelId("smoke-ollama-model")
    config = OllamaProviderConfig(
        base_url=base_url,
        model_names={model_id: model_name},
    )

    request = ProviderRequest(
        request_id=RequestId("smoke_req_1"),
        attempt_id=AttemptId("smoke_att_1"),
        model_id=model_id,
        messages=(ChatMessage(role=ChatRole.USER, content=prompt),),
        output_format=OutputFormat.TEXT,
        timeout_ms=30000,
        idempotency_key="smoke_key_1",
    )

    model = ModelDefinition(
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
                source="smoke",
                version="v1",
            ),
        ),
        enabled=True,
        configuration_version="v1",
    )

    try:
        async with OllamaProvider(config=config) as provider:
            response = await provider.complete(request, model)

        output_data = {
            "status": "SUCCESS",
            "provider": response.provider_id,
            "model_id": response.model_id,
            "upstream_model": model_name,
            "content": response.content,
            "finish_reason": response.finish_reason,
            "latency_ms": response.latency_ms,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
                "source": response.usage.source,
            },
        }
        print(json.dumps(output_data, indent=2))
        return 0
    except ProviderExecutionError as err:
        print(
            f"Ollama smoke test failed [{err.error.code}]: {err.error.message}",
            file=sys.stderr,
        )
        return 1
    except Exception as err:
        print(f"Ollama smoke test unexpected failure: {err}", file=sys.stderr)
        return 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(run_smoke_test(args.model, args.base_url, args.prompt))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
