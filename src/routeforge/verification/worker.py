"""Background worker consuming Redis stream verification jobs and running reference evaluations."""

import argparse
import asyncio
import json
import logging
import signal
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from routeforge.contracts.common import utc_now
from routeforge.contracts.inference import ChatMessage, ChatRole, OutputFormat
from routeforge.contracts.providers import ProviderRequest
from routeforge.contracts.verification import VerificationStrategy
from routeforge.providers.mock import DeterministicMockProvider
from routeforge.providers.ollama import OllamaProvider
from routeforge.registries.file_loader import load_configuration_registry
from routeforge.storage.models import QualityVerificationRecord
from routeforge.verification.comparison import evaluate_verification
from routeforge.verification.hashing import hash_json_output, hash_text_output
from routeforge.verification.queue import (
    VERIFICATION_CONSUMER_GROUP,
    VERIFICATION_STREAM_KEY,
    ack_and_delete_verification_job,
    ensure_consumer_group,
)

logger = logging.getLogger("routeforge.verification.worker")


class VerificationWorker:
    """Worker process for evaluating quality verification jobs."""

    def __init__(
        self,
        redis: aioredis.Redis,
        session_factory: async_sessionmaker[AsyncSession],
        consumer_name: str | None = None,
        max_delivery_attempts: int = 3,
        pending_idle_ms: int = 30000,
    ) -> None:
        self.redis = redis
        self.session_factory = session_factory
        self.consumer_name = consumer_name or f"worker-{uuid.uuid4().hex[:8]}"
        self.max_delivery_attempts = max_delivery_attempts
        self.pending_idle_ms = pending_idle_ms
        self.running = True
        self.registry = load_configuration_registry()

    def stop(self) -> None:
        self.running = False

    async def process_job(self, entry_id: str, fields: dict[str, str]) -> None:
        """Process a single verification job."""
        verification_id_str = fields.get("verification_id")
        if not verification_id_str:
            await ack_and_delete_verification_job(self.redis, entry_id)
            return

        try:
            verification_uuid = uuid.UUID(verification_id_str)
        except ValueError:
            await ack_and_delete_verification_job(self.redis, entry_id)
            return

        async with self.session_factory() as session:
            stmt = select(QualityVerificationRecord).where(
                QualityVerificationRecord.verification_id == verification_uuid
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if not record:
                await ack_and_delete_verification_job(self.redis, entry_id)
                return

            if record.status in ("SUCCEEDED", "FAILED", "SKIPPED"):
                # Already terminal in database
                await ack_and_delete_verification_job(self.redis, entry_id)
                return

            # Check delivery attempts limit
            new_attempts = record.delivery_attempts + 1
            if new_attempts > self.max_delivery_attempts:
                record.status = "FAILED"
                record.failure_code = "MAXIMUM_DELIVERIES_EXCEEDED"
                record.delivery_attempts = new_attempts
                record.completed_at = utc_now()
                await session.commit()
                await ack_and_delete_verification_job(self.redis, entry_id)
                return

            # Mark RUNNING and increment attempts
            record.status = "RUNNING"
            record.delivery_attempts = new_attempts
            record.started_at = utc_now()
            await session.commit()

            # Execute verification evaluation logic
            try:
                await self._execute_verification(record, fields, session)
            except Exception as exc:
                logger.error("Error executing verification job %s: %s", verification_id_str, exc)
                record.status = "FAILED"
                record.failure_code = "COMPARISON_ERROR"
                record.completed_at = utc_now()
                await session.commit()

            # Clean up stream entry
            await ack_and_delete_verification_job(self.redis, entry_id)

    async def _execute_verification(
        self,
        record: QualityVerificationRecord,
        fields: dict[str, str],
        session: AsyncSession,
    ) -> None:
        # Load reference model definition
        try:
            model_def = self.registry.models.get_model(record.reference_model_id)
        except Exception:
            record.status = "FAILED"
            record.failure_code = "VERIFICATION_CONFIGURATION_ERROR"
            record.completed_at = utc_now()
            await session.commit()
            return

        selected_content = fields.get("selected_response_content", "")
        messages_raw = fields.get("messages", "[]")
        output_format_raw = fields.get("output_format")

        try:
            messages_list = json.loads(messages_raw)
            chat_messages = [
                ChatMessage(role=ChatRole(m["role"]), content=m["content"]) for m in messages_list
            ]
        except Exception:
            chat_messages = [ChatMessage(role=ChatRole.USER, content="Verification test")]

        output_format: OutputFormat | None = None
        if output_format_raw:
            try:
                output_format = OutputFormat(output_format_raw)
            except Exception:
                output_format = None

        provider_req = ProviderRequest(
            messages=tuple(chat_messages),
            output_format=output_format,
        )

        start_time = datetime.now(UTC)
        # Execute reference model
        try:
            if str(model_def.provider_id) == "mock":
                provider = DeterministicMockProvider()
            elif str(model_def.provider_id) == "ollama":
                provider = OllamaProvider()
            else:
                provider = DeterministicMockProvider()

            resp = await provider.execute(model_def.model_id, provider_req)
            ref_latency = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            ref_content = resp.content
            ref_in_tokens = resp.usage.input_tokens
            ref_out_tokens = resp.usage.output_tokens
            ref_tot_tokens = resp.usage.total_tokens
        except Exception as p_err:
            logger.warning("Reference provider execution error: %s", p_err)
            record.status = "FAILED"
            record.failure_code = "REFERENCE_PROVIDER_ERROR"
            record.completed_at = utc_now()
            await session.commit()
            return

        if not ref_content or not ref_content.strip():
            record.status = "FAILED"
            record.failure_code = "INVALID_REFERENCE_RESPONSE"
            record.completed_at = utc_now()
            await session.commit()
            return

        # Calculate reference output hash
        strategy = VerificationStrategy(record.strategy)
        if strategy == VerificationStrategy.JSON_FIELD_AGREEMENT:
            ref_hash = hash_json_output(ref_content)
        else:
            ref_hash = hash_text_output(ref_content)

        # Run comparison strategy
        try:
            score, passed, failure_code = evaluate_verification(
                strategy=strategy,
                selected_output=selected_content,
                reference_output=ref_content,
                minimum_score=record.minimum_score,
            )
        except Exception as c_err:
            logger.error("Comparison strategy calculation failed: %s", c_err)
            record.status = "FAILED"
            record.failure_code = "COMPARISON_ERROR"
            record.completed_at = utc_now()
            await session.commit()
            return

        # Calculate cost
        in_cost_rate = model_def.estimated_input_cost_per_million_tokens_usd
        out_cost_rate = model_def.estimated_output_cost_per_million_tokens_usd
        ref_cost = (Decimal(ref_in_tokens) / Decimal(1_000_000)) * in_cost_rate + (
            Decimal(ref_out_tokens) / Decimal(1_000_000)
        ) * out_cost_rate

        # Update record to SUCCEEDED
        record.status = "SUCCEEDED"
        record.score = score
        record.passed = passed
        record.failure_code = failure_code
        record.reference_output_hash = ref_hash
        record.reference_input_tokens = ref_in_tokens
        record.reference_output_tokens = ref_out_tokens
        record.reference_total_tokens = ref_tot_tokens
        record.reference_latency_ms = ref_latency
        record.reference_cost_usd = ref_cost
        record.reference_cost_source = "configured-model-pricing-v1"
        record.completed_at = utc_now()
        await session.commit()

    async def reclaim_pending_jobs(self) -> None:
        """Reclaim and process stuck pending entries from the stream consumer group."""
        try:
            pending_res = await self.redis.xpending_range(
                name=VERIFICATION_STREAM_KEY,
                groupname=VERIFICATION_CONSUMER_GROUP,
                min="-",
                max="+",
                count=10,
            )
            for p_info in pending_res:
                idle_ms = p_info.get("idle", 0)
                entry_id = p_info.get("message_id")
                if idle_ms > self.pending_idle_ms and entry_id:
                    claimed = await self.redis.xclaim(
                        name=VERIFICATION_STREAM_KEY,
                        groupname=VERIFICATION_CONSUMER_GROUP,
                        consumername=self.consumer_name,
                        min_idle_time=self.pending_idle_ms,
                        message_ids=[entry_id],
                    )
                    for item in claimed:
                        msg_id = item[0]
                        fields_dict = {
                            (k.decode("utf-8") if isinstance(k, bytes) else str(k)): (
                                v.decode("utf-8") if isinstance(v, bytes) else str(v)
                            )
                            for k, v in item[1].items()
                        }
                        await self.process_job(
                            msg_id.decode("utf-8") if isinstance(msg_id, bytes) else str(msg_id),
                            fields_dict,
                        )
        except Exception as exc:
            logger.debug("Pending jobs reclamation check failed: %s", exc)

    async def run(self, once: bool = False) -> None:
        """Main worker execution loop."""
        await ensure_consumer_group(self.redis)

        while self.running:
            try:
                # Reclaim pending jobs first
                await self.reclaim_pending_jobs()

                # Read new jobs
                response = await self.redis.xreadgroup(
                    groupname=VERIFICATION_CONSUMER_GROUP,
                    consumername=self.consumer_name,
                    streams={VERIFICATION_STREAM_KEY: ">"},
                    count=1,
                    block=1000,
                )

                if response:
                    for _stream_key, entries in response:
                        for entry_id, fields in entries:
                            entry_id_str = (
                                entry_id.decode("utf-8")
                                if isinstance(entry_id, bytes)
                                else str(entry_id)
                            )
                            fields_dict = {
                                (k.decode("utf-8") if isinstance(k, bytes) else str(k)): (
                                    v.decode("utf-8") if isinstance(v, bytes) else str(v)
                                )
                                for k, v in fields.items()
                            }
                            await self.process_job(entry_id_str, fields_dict)

                if once:
                    break
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in worker loop: %s", exc)
                if once:
                    break
                await asyncio.sleep(1)


async def main() -> None:
    parser = argparse.ArgumentParser(description="RouteForge Quality Verification Worker")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
    parser.add_argument("--consumer-name", type=str, help="Consumer name for Redis consumer group.")
    parser.add_argument(
        "--db-url",
        type=str,
        default="postgresql+asyncpg://routeforge:routeforge_pass@localhost:5432/routeforge_dev",
        help="PostgreSQL connection string.",
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default="redis://localhost:6379/0",
        help="Redis connection string.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    engine = create_async_engine(args.db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    redis_client = aioredis.from_url(args.redis_url)

    worker = VerificationWorker(
        redis=redis_client,
        session_factory=session_factory,
        consumer_name=args.consumer_name,
    )

    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received, stopping worker...")
        worker.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Signal handling on Windows
            pass

    logger.info("Starting verification worker (%s)...", worker.consumer_name)
    try:
        await worker.run(once=args.once)
    finally:
        await redis_client.aclose()
        await engine.dispose()
        logger.info("Worker shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
