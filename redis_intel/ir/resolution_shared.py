"""Shared constants, row types and helpers for wrapper-depth resolution."""

from dataclasses import dataclass
from typing import Any

from redis_intel.ir.tree_utils import (
    node_text,
    unwrap_transparent_expression,
)

MAX_WRAPPER_DEPTH = 2
# Recursion bound for pathological chains (aliases, self-recursive wrappers).
# Reached depth is reported as wrapper_depth_exceeded, never a crash.
_HARD_MAX_CHAIN_DEPTH = 64

IOREDIS_CONSTRUCTOR_NAMES = frozenset({"Redis", "IORedis"})
IOREDIS_PACKAGE_NAME = "ioredis"
NODE_REDIS_PACKAGE_NAME = "redis"
NODE_REDIS_FACTORY_NAMES = frozenset({"createClient", "createCluster"})
REQUIRE_ACQUIRED_PACKAGES = frozenset({IOREDIS_PACKAGE_NAME, NODE_REDIS_PACKAGE_NAME})

# Contract rev 3 section 3.4 R2: type annotations that name a Redis client
# type (generic forms resolve to their base name), and the client library
# each annotation implies. The concrete construction for an injected client
# lives outside the file, so the library is inferred from the annotation.
REDIS_CLIENT_TYPE_ANNOTATIONS = frozenset({
    "Redis",
    "IORedis",
    "RedisClientType",
    "Cluster",
})
# The IR `clients.client_library` enum value for node-redis (the package is
# named "redis" but the storage enum is "node_redis", PLAN section 2.4).
NODE_REDIS_LIBRARY_NAME = "node_redis"
_CLIENT_LIBRARY_BY_ANNOTATION = {
    "Redis": IOREDIS_PACKAGE_NAME,
    "IORedis": IOREDIS_PACKAGE_NAME,
    "RedisClientType": NODE_REDIS_LIBRARY_NAME,
    "Cluster": NODE_REDIS_LIBRARY_NAME,
}

_BINDING_KIND_NEW_CALL = "new_call"
_BINDING_KIND_CALL = "call"
_BINDING_KIND_IDENTIFIER = "identifier"
_BINDING_KIND_INJECTION = "injection"
_BINDING_KIND_OTHER = "other"

_WRAPPER_DEPTH_ATTRIBUTE = "DEPTH"
_RESOLUTION_ATTRIBUTE = "resolution"
_MODEL_HYPOTHESIS_CANDIDATE_FLAG = "model_hypothesis_candidate"
_PROVENANCE_ATTRIBUTE = "provenance"
_RESOLVER_PROVENANCE = "ast-resolver@0.3.0"

# Contract rev 3 section 3.4 + §8: which rule resolved the receiver.
_RESOLUTION_CLASS_FIELD_INITIALIZER = "class_field_initializer"
_RESOLUTION_CONSTRUCTOR_INJECTION = "constructor_injection"
_RESOLUTION_FACTORY_RETURN = "factory_return"
_RESOLUTION_DYNAMIC_REQUIRE = "dynamic_require"
_RESOLUTION_DIRECT_CONSTRUCTION = "direct_construction"
_RESOLUTION_ALIAS_BINDING = "alias_binding"

_REASON_DYNAMIC_CONSTRUCTION = "dynamic_construction"
_REASON_WRAPPER_DEPTH_EXCEEDED = "wrapper_depth_exceeded"

_EPISTEMIC_DETERMINISTIC_FACT = "DETERMINISTIC_FACT"
_EPISTEMIC_STATIC_INFERENCE = "STATIC_INFERENCE"
_EPISTEMIC_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ResolvedClient:
    """Outcome of resolving one receiver name within a parsed file.

    ``resolution`` names the contract rev 3 §3.4 rule that resolved the
    receiver (recorded additively in ``evidence_json["resolution"]``).
    """

    receiver_name: str
    client_library: str
    construction: str
    conn_config: dict[str, Any]
    wrapper_depth: int
    epistemic: str
    evidence_json: dict[str, Any]
    span: tuple[int, int, int, int]
    resolution: str | None = None


@dataclass(frozen=True)
class _Binding:
    """One name binding: initializer kind + the initializer node itself.

    ``annotation`` carries the Redis client type-annotation base name for
    ``_BINDING_KIND_INJECTION`` bindings (contract §3.4 R2); it is ``None``
    for every other kind.
    """

    name: str
    kind: str
    node: Any
    span: tuple[int, int, int, int]
    annotation: str | None = None


@dataclass(frozen=True)
class _FunctionDefinition:
    """An in-file function: parameter names plus its resolved return expression."""

    parameters: tuple[str, ...]
    return_node: Any | None


def _unwrap_constructor_node(node: Any) -> Any | None:
    """Peel transparent wrappers (parentheses, await) off a constructor node."""
    return unwrap_transparent_expression(node)


def _string_literal_text(string_node: Any) -> str:
    return node_text(string_node).strip("\"'")


def _binding_kind_for_expression(value_node: Any) -> str:
    if value_node.type == "new_expression":
        return _BINDING_KIND_NEW_CALL
    if value_node.type == "call_expression":
        return _BINDING_KIND_CALL
    if value_node.type == "identifier":
        return _BINDING_KIND_IDENTIFIER
    return _BINDING_KIND_OTHER
