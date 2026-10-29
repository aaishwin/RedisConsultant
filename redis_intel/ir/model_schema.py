"""Enumerations, boundary validators and the revision dataclass of the C-2 IR.

Split out of :mod:`redis_intel.ir.models` so that module stays inside the
repository's 250-code-line limit (style contract rule 8). ``models`` re-exports
every name here, so external imports are unchanged.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

IR_SCHEMA_VERSION = "0.1.0"

EPISTEMIC_TIERS: tuple[str, ...] = (
    "DETERMINISTIC_FACT",
    "STATIC_INFERENCE",
    "MODEL_HYPOTHESIS",
    "RUNTIME_OBSERVATION",
    "VERIFIED_OUTCOME",
    "UNKNOWN",
)

GRAMMAR_IDS: tuple[str, ...] = ("typescript", "tsx", "javascript", "python")
SCOPE_KINDS: tuple[str, ...] = (
    "module",
    "function",
    "method",
    "class",
    "lambda",
    "arrow",
    "script",
)
SYMBOL_KINDS: tuple[str, ...] = (
    "variable",
    "parameter",
    "property",
    "import",
    "unknown",
)
CLIENT_LIBRARIES: tuple[str, ...] = ("ioredis", "node_redis", "redis_py", "unknown")
OP_KINDS: tuple[str, ...] = (
    "READ",
    "WRITE",
    "DELETE",
    "EXPIRE",
    "PIPELINE",
    "TRANSACTION",
    "LUA_SCRIPT",
    "PUBSUB",
)
KEY_EXPR_KINDS: tuple[str, ...] = ("literal", "template", "dynamic_unknown")
SERIALIZER_METHODS: tuple[str, ...] = ("json", "msgpack", "string", "buffer", "unknown")
EDGE_TYPES: tuple[str, ...] = (
    "CALLS",
    "KEY_FLOW",
    "READS",
    "WRITES",
    "DELETES",
    "EXPIRES",
    "INVALIDATES",
    "DATA_FLOW",
    "IMPORTS",
)
NODE_KINDS: tuple[str, ...] = (
    "scope",
    "symbol",
    "op",
    "key_expr",
    "client",
    "namespace",
    "file",
)
UNKNOWN_REASONS: tuple[str, ...] = (
    "unsupported_syntax",
    "unresolvable_expression",
    "wrapper_depth_exceeded",
    "dynamic_construction",
    "node_budget_exceeded",
    "file_too_large",
    "parse_error",
)
REVISION_KINDS: tuple[str, ...] = ("full", "incremental")

SUBJECT_KINDS: tuple[str, ...] = (
    "file",
    "scope",
    "callsite",
    "key_expr",
    "client",
    "op",
    "symbol",
)


def require_enum_value(
    value: str, allowed_values: tuple[str, ...], field_name: str
) -> None:
    if value not in allowed_values:
        raise ValueError(f"{field_name} must be one of {allowed_values}, got {value!r}")


def require_type(value: object, expected_type: type, field_name: str) -> None:
    if not isinstance(value, expected_type):
        raise TypeError(
            f"{field_name} must be {expected_type.__name__}, got {type(value).__name__}"
        )


def require_non_negative_int(value: int, field_name: str) -> None:
    require_type(value, int, field_name)
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0, got {value}")


def sorted_json_value(value: Any) -> Any:
    """Recursively sort mapping keys so nested JSON is canonical at construction."""
    if isinstance(value, Mapping):
        return {key: sorted_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [sorted_json_value(element) for element in value]
    if isinstance(value, tuple):
        return tuple(sorted_json_value(element) for element in value)
    return value


def require_evidence_json(value: Any, field_name: str) -> dict[str, Any]:
    require_type(value, dict, field_name)
    return sorted_json_value(value)


@dataclass(frozen=True)
class Revision:
    git_ref: str
    parent_revision_id: int | None
    kind: str
    file_count: int

    def __post_init__(self) -> None:
        require_type(self.git_ref, str, "git_ref")
        require_enum_value(self.kind, REVISION_KINDS, "kind")
        require_non_negative_int(self.file_count, "file_count")
        if self.parent_revision_id is not None:
            require_non_negative_int(self.parent_revision_id, "parent_revision_id")
