"""Redis Stream queue interface for quality verification jobs."""

import json
import logging
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

VERIFICATION_STREAM_KEY = "routeforge:quality-verification:v1"
VERIFICATION_CONSUMER_GROUP = "routeforge-quality-verifiers-v1"
DEFAULT_STREAM_MAXLEN = 1000


async def ensure_consumer_group(
    redis: Redis,
    stream_key: str = VERIFICATION_STREAM_KEY,
    group_name: str = VERIFICATION_CONSUMER_GROUP,
) -> None:
    """Ensure the Redis stream consumer group exists, creating it if needed."""
    try:
        await redis.xgroup_create(name=stream_key, groupname=group_name, id="0", mkstream=True)
    except Exception as exc:
        # Ignore error if group already exists ("BUSYGROUP")
        if "BUSYGROUP" not in str(exc):
            logger.warning("Error creating Redis consumer group %s: %s", group_name, exc)


async def enqueue_verification_job(
    redis: Redis,
    payload: dict[str, Any],
    stream_key: str = VERIFICATION_STREAM_KEY,
    max_len: int = DEFAULT_STREAM_MAXLEN,
) -> str:
    """Publish a quality verification job to the Redis Stream.

    Args:
        redis: Active Redis client instance.
        payload: Verification job payload dictionary.
        stream_key: Target stream key.
        max_len: Bounded MAXLEN for stream.

    Returns:
        Redis stream entry ID.
    """
    serialized: dict[Any, Any] = {}
    for k, v in payload.items():
        if isinstance(v, (dict, list)):
            serialized[k] = json.dumps(v)
        elif v is None:
            serialized[k] = ""
        else:
            serialized[k] = str(v)

    entry_id = await redis.xadd(
        name=stream_key,
        fields=serialized,
        maxlen=max_len,
        approximate=True,
    )
    return str(entry_id)


async def ack_and_delete_verification_job(
    redis: Redis,
    entry_id: str,
    stream_key: str = VERIFICATION_STREAM_KEY,
    group_name: str = VERIFICATION_CONSUMER_GROUP,
) -> None:
    """Acknowledge and delete a processed entry from the Redis Stream."""
    try:
        await redis.xack(stream_key, group_name, entry_id)
        await redis.xdel(stream_key, entry_id)
    except Exception as exc:
        logger.warning("Error acknowledging/deleting stream entry %s: %s", entry_id, exc)
