"""Shared constants and pure helpers for IR ingestion (contract §4.1).

Split out of ``builder.py`` so every module stays inside rule 8's 250-code-line
limit. Nothing here imports ``builder.py`` or a builder mixin, so the mixin
modules can depend on this module without creating an import cycle.
"""

import hashlib
import re
from typing import Any

from redis_intel.frontend import RawRedisCallsite, Span

_PROVENANCE = "ir-builder@0.1.0"

_EPISTEMIC_DETERMINISTIC_FACT = "DETERMINISTIC_FACT"
_EPISTEMIC_STATIC_INFERENCE = "STATIC_INFERENCE"
_EPISTEMIC_UNKNOWN = "UNKNOWN"

_CLIENT_LIBRARIES_BY_HINT = {
    "ioredis": "ioredis",
    "node_redis": "node_redis",
    "redis": "node_redis",
    "Redis": "ioredis",
    "IORedis": "ioredis",
    "RedisClientType": "node_redis",
    "Cluster": "node_redis",
}

_METHOD_OP_KINDS = {
    "get": "READ",
    "mget": "READ",
    "hget": "READ",
    "hgetall": "READ",
    "lrange": "READ",
    "smembers": "READ",
    "zrange": "READ",
    "exists": "READ",
    "ttl": "READ",
    "keys": "READ",
    "scan": "READ",
    "set": "WRITE",
    "mset": "WRITE",
    "hset": "WRITE",
    "lpush": "WRITE",
    "rpush": "WRITE",
    "sadd": "WRITE",
    "zadd": "WRITE",
    "incr": "WRITE",
    "incrby": "WRITE",
    "decr": "WRITE",
    "expire": "EXPIRE",
    "pexpire": "EXPIRE",
    "expireat": "EXPIRE",
    "persist": "EXPIRE",
    "del": "DELETE",
    "unlink": "DELETE",
    "hdel": "DELETE",
    "srem": "DELETE",
    "zrem": "DELETE",
    "lpop": "DELETE",
    "rpop": "DELETE",
    "pipeline": "PIPELINE",
    "multi": "TRANSACTION",
    "exec": "TRANSACTION",
    "eval": "LUA_SCRIPT",
    "evalsha": "LUA_SCRIPT",
    "publish": "PUBSUB",
    "subscribe": "PUBSUB",
    "unsubscribe": "PUBSUB",
    "psubscribe": "PUBSUB",
}

_TTL_BEARING_METHODS = frozenset({
    "set",
    "setex",
    "psetex",
    "expire",
    "pexpire",
    "expireat",
    "setrange",
    "getset",
    "hset",
})

_SIGNATURE_HASH_SALT = "ir-builder:signature:v1"

_TEMPLATE_SLOT_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _span_to_tuple(span: Span) -> tuple[int, int, int, int]:
    return (span.start_line, span.start_col, span.end_line, span.end_col)


def _signature_hash(signature_text: str) -> str:
    normalized = " ".join(signature_text.split())
    return hashlib.sha256(f"{_SIGNATURE_HASH_SALT}:{normalized}".encode()).hexdigest()


def _classify_key_expr(argument_text: str) -> tuple[str, str, list[dict[str, Any]]]:
    stripped = argument_text.strip()
    if _is_string_literal(stripped):
        return "literal", stripped, []
    if _is_template(stripped):
        slots = [
            {"name": _extract_slot_name(stripped), "span": None, "symbol_id": None}
        ]
        return "template", stripped, slots
    # A "+"-concatenation key is not a statically complete template — its
    # parts come from runtime values — so it is a dynamic_unknown key row
    # (contract §5.1: dynamic key ⇒ dynamic_unknown row + the
    # dynamic_construction unknowns entry). Full string literals (including
    # URI literals) stay "literal"; only non-literal concatenations get here.
    if _is_concatenation(stripped):
        return "dynamic_unknown", stripped, []
    return "dynamic_unknown", stripped, []


def _is_string_literal(text: str) -> bool:
    return len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]


def _derive_namespace_prefix(template_text: str) -> str | None:
    """Derive a namespace prefix from a template key (e.g. ``user:{id}:profile``).

    Only non-trivial prefixes (text before the first ``:``) are emitted; keys
    without a ``:`` or starting with ``:`` yield ``None``.
    """
    stripped = template_text.strip("\"'`")
    separator_index = stripped.find(":")
    if separator_index <= 0:
        return None
    return stripped[: separator_index + 1]


def _is_template(text: str) -> bool:
    return "${" in text


def _is_concatenation(text: str) -> bool:
    # Any non-literal key text containing a top-level "+" concatenation is
    # dynamic; the shared " +" heuristic already guards template detection.
    return " +" in text


def _extract_slot_name(template_text: str) -> str:
    match = _TEMPLATE_SLOT_PATTERN.search(template_text)
    if match is not None:
        return match.group(1).strip()
    parts = template_text.split("+")
    return " + ".join(part.strip() for part in parts)


def _key_sort_slots(slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(slots, key=lambda slot: slot.get("name", ""))


def _ttl_argument_index(callsite: RawRedisCallsite) -> int | None:
    method = callsite.method.lower()
    if method in {"expire", "pexpire", "setex", "psetex"}:
        return 1
    if method in {"set", "setrange", "getset", "hset"}:
        return 2
    return None


def _resolve_ttl_seconds(expression: str) -> int | None:
    stripped = expression.strip()
    try:
        return int(stripped)
    except ValueError:
        return None


def _classify_serializer(method: str) -> str:
    lowered = method.lower()
    if "json" in lowered:
        return "json"
    if "msgpack" in lowered:
        return "msgpack"
    if "buffer" in lowered:
        return "buffer"
    return "string"
