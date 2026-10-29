"""Wrapper-DEPTH resolution of Redis client chains.

Contract ``ir-boundary`` rev 3, §3.4/§5.2/§5.3.

The resolver maps a callsite receiver name to the concrete client construction
behind it using a per-file binding table built from imports, ``require``
calls, class bodies, variable declarations and in-file function definitions:

- ``new_call`` bindings (``const redis_client = new Redis(...)``, or an R1
  class field ``this.client = new Redis(...)``) are concrete client
  constructions when the constructor is a known client class, and wrapper
  hops otherwise (the wrapped client is the first constructor argument, e.g.
  ``new Proxy(redis_client)``);
- ``injection`` bindings are R2 constructor-parameter injections
  (``this.client = <param>`` where the parameter's type annotation names a
  Redis client type, including TS parameter properties): the concrete
  construction lives outside the file, so the row is ``STATIC_INFERENCE``
  at DEPTH 1 with the annotation name as ``construction``;
- ``call`` bindings resolve through in-file factories (R3) one level plus the
  inner form's DEPTH, or through known factory calls (``createClient({...})``);
- ``identifier`` bindings are aliases (``const aliased_client = redis_client;``)
  and count as one hop;
- R4 ``require('ioredis')``/``require('redis')`` bindings are treated as
  import equivalents (DEPTH 0), including ``new (require('ioredis'))(...)``.

Every binding hop increments the observed DEPTH per §5.2: R1/R4 receivers are
DEPTH 0, R2 receivers DEPTH 1, R3 receivers 1 + the inner form's DEPTH. A
chain resolving to a concrete construction at depth <= 2 stays concrete:
``DETERMINISTIC_FACT`` at depth 0, ``STATIC_INFERENCE`` for wrapper-resolved
chains. Deeper chains escalate to a row-level UNKNOWN with reason
``wrapper_depth_exceeded``; constructions whose arguments are non-constant
(``process.env.REDIS_URL``) escalate with reason ``dynamic_construction`` —
both carrying ``model_hypothesis_candidate = true`` (§5.2 escalation table).
Constructor arguments are extracted into a raw ``conn_config`` mapping; the
governance redactor is applied by the builder at the single sanctioned seam
(§6). No conn args means an empty mapping — the resolver never fabricates
configuration. Concrete resolutions record which §3.4 rule resolved the
receiver in ``evidence_json["resolution"]`` (additive key, §8 rev 3).

The resolver is pure: no file I/O, no clock, no randomness.
"""

from dataclasses import replace
from typing import Any

from redis_intel.ir.resolution_chain import ChainResolutionMixin
from redis_intel.ir.resolution_collect import CollectionMixin
from redis_intel.ir.resolution_concrete import ConcreteClientMixin
from redis_intel.ir.resolution_conn_config import ConnConfigMixin
from redis_intel.ir.resolution_dispatch import DispatchResolutionMixin
from redis_intel.ir.resolution_escalation import EscalationMixin
from redis_intel.ir.resolution_expression import ExpressionResolutionMixin
from redis_intel.ir.resolution_fields import FieldRecordingMixin
from redis_intel.ir.resolution_functions import FunctionRecordingMixin
from redis_intel.ir.resolution_library import LibraryDetectionMixin
from redis_intel.ir.resolution_shared import (
    _BINDING_KIND_CALL,
    _BINDING_KIND_IDENTIFIER,
    _BINDING_KIND_INJECTION,
    _BINDING_KIND_NEW_CALL,
    _BINDING_KIND_OTHER,
    _CLIENT_LIBRARY_BY_ANNOTATION,
    _EPISTEMIC_DETERMINISTIC_FACT,
    _EPISTEMIC_STATIC_INFERENCE,
    _EPISTEMIC_UNKNOWN,
    _HARD_MAX_CHAIN_DEPTH,
    _MODEL_HYPOTHESIS_CANDIDATE_FLAG,
    _PROVENANCE_ATTRIBUTE,
    _REASON_DYNAMIC_CONSTRUCTION,
    _REASON_WRAPPER_DEPTH_EXCEEDED,
    _RESOLUTION_ALIAS_BINDING,
    _RESOLUTION_ATTRIBUTE,
    _RESOLUTION_CLASS_FIELD_INITIALIZER,
    _RESOLUTION_CONSTRUCTOR_INJECTION,
    _RESOLUTION_DIRECT_CONSTRUCTION,
    _RESOLUTION_DYNAMIC_REQUIRE,
    _RESOLUTION_FACTORY_RETURN,
    _RESOLVER_PROVENANCE,
    _WRAPPER_DEPTH_ATTRIBUTE,
    IOREDIS_CONSTRUCTOR_NAMES,
    IOREDIS_PACKAGE_NAME,
    MAX_WRAPPER_DEPTH,
    NODE_REDIS_FACTORY_NAMES,
    NODE_REDIS_LIBRARY_NAME,
    NODE_REDIS_PACKAGE_NAME,
    REDIS_CLIENT_TYPE_ANNOTATIONS,
    REQUIRE_ACQUIRED_PACKAGES,
    ResolvedClient,
    _Binding,
    _binding_kind_for_expression,
    _FunctionDefinition,
    _string_literal_text,
    _unwrap_constructor_node,
)
from redis_intel.ir.tree_utils import (
    MAX_AST_NODE_BUDGET,
    iter_preorder_nodes_bounded,
    node_text,
    span_from_node,
    unwrap_transparent_expression,
)

__all__ = [
    "ClientChainResolver",
    "LibraryDetectionMixin",
    "DispatchResolutionMixin",
    "ChainResolutionMixin",
    "ExpressionResolutionMixin",
    "ConcreteClientMixin",
    "ConnConfigMixin",
    "EscalationMixin",
    "CollectionMixin",
    "FieldRecordingMixin",
    "FunctionRecordingMixin",
    "MAX_WRAPPER_DEPTH",
    "_HARD_MAX_CHAIN_DEPTH",
    "IOREDIS_CONSTRUCTOR_NAMES",
    "IOREDIS_PACKAGE_NAME",
    "NODE_REDIS_PACKAGE_NAME",
    "NODE_REDIS_FACTORY_NAMES",
    "REQUIRE_ACQUIRED_PACKAGES",
    "REDIS_CLIENT_TYPE_ANNOTATIONS",
    "NODE_REDIS_LIBRARY_NAME",
    "_CLIENT_LIBRARY_BY_ANNOTATION",
    "_BINDING_KIND_NEW_CALL",
    "_BINDING_KIND_CALL",
    "_BINDING_KIND_IDENTIFIER",
    "_BINDING_KIND_INJECTION",
    "_BINDING_KIND_OTHER",
    "_WRAPPER_DEPTH_ATTRIBUTE",
    "_RESOLUTION_ATTRIBUTE",
    "_MODEL_HYPOTHESIS_CANDIDATE_FLAG",
    "_PROVENANCE_ATTRIBUTE",
    "_RESOLVER_PROVENANCE",
    "_RESOLUTION_CLASS_FIELD_INITIALIZER",
    "_RESOLUTION_CONSTRUCTOR_INJECTION",
    "_RESOLUTION_FACTORY_RETURN",
    "_RESOLUTION_DYNAMIC_REQUIRE",
    "_RESOLUTION_DIRECT_CONSTRUCTION",
    "_RESOLUTION_ALIAS_BINDING",
    "_REASON_DYNAMIC_CONSTRUCTION",
    "_REASON_WRAPPER_DEPTH_EXCEEDED",
    "_EPISTEMIC_DETERMINISTIC_FACT",
    "_EPISTEMIC_STATIC_INFERENCE",
    "_EPISTEMIC_UNKNOWN",
    "ResolvedClient",
    "_Binding",
    "_FunctionDefinition",
    "_unwrap_constructor_node",
    "_string_literal_text",
    "_binding_kind_for_expression",
    "MAX_AST_NODE_BUDGET",
    "iter_preorder_nodes_bounded",
    "node_text",
    "span_from_node",
    "unwrap_transparent_expression",
]


class ClientChainResolver(
    LibraryDetectionMixin,
    DispatchResolutionMixin,
    ChainResolutionMixin,
    ExpressionResolutionMixin,
    ConcreteClientMixin,
    ConnConfigMixin,
    EscalationMixin,
    CollectionMixin,
    FieldRecordingMixin,
    FunctionRecordingMixin,
):
    """Resolve receiver names to client constructions within one parsed file."""

    def __init__(self, tree: Any) -> None:
        self._tree = tree
        self._bindings: dict[str, _Binding] = {}
        self._functions: dict[str, _FunctionDefinition] = {}
        self._methods: dict[str, _FunctionDefinition] = {}
        self._import_aliases: dict[str, tuple[str, str]] = {}
        self._require_aliases: dict[str, str] = {}
        self._collect_bindings()

    def resolve(self, receiver_name: str) -> ResolvedClient | None:
        """Resolve ``receiver_name``; return None when the name is not bound.

        Zero-argument call receivers (``makeClient()``, ``this.getRedis()``)
        resolve through the named in-file factory (R3); the receiver text of a
        member call is the verbatim receiver expression, so the call suffix is
        stripped here. Calls with arguments keep the full text and do not
        resolve through this text-level path — their arguments cannot be
        substituted into the factory body from text alone.
        """
        resolved = self._resolve_zero_argument_call_receiver(receiver_name)
        if resolved is None:
            resolved = self._resolve_binding(
                receiver_name, depth=0, visited=frozenset(), param_scope={}
            )
        if resolved is None:
            return None
        return replace(resolved, receiver_name=receiver_name)
