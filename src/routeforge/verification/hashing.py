"""Output hashing functions for audit correlation without raw text retention."""

import hashlib
import json
from typing import Any


def hash_text_output(text: str) -> str:
    """Normalize line endings and compute SHA-256 hash of text output.

    Args:
        text: Raw text output string.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_json_output(content: Any) -> str:
    """Canonicalize JSON and compute SHA-256 hash.

    Args:
        content: JSON string or decoded JSON data structure.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except Exception:
            return hash_text_output(content)
    else:
        parsed = content

    canonical_json = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
