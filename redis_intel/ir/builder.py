"""IrBuilder: pure ParseResults → IrDelta ingestion (contract §4.1).

Pure function with respect to inputs: no file I/O, no clock, no randomness. Same input
tuple + same redactor ⇒ byte-identical serialized IrDelta. The governance
redaction seam (§6) is called at exactly one point — per ``clients`` row
construction — before any client row exists; the raw config never reaches an
IR row. Zero silent drops: every callsite, scope, and unresolved node maps to
at least one entity row or one standalone ``unknowns`` entry (§5.3).

The ingestion state machine is split across sibling mixin modules
(``builder_ordering``, ``builder_ingest``, ``builder_client``, ``builder_ops``,
``builder_ttl``) with the shared constants and helpers in ``builder_shared``,
so each module stays inside rule 8's 250-code-line limit. The names below are
imported for backwards compatibility: every name that used to be importable
from this module still is.
"""

import hashlib as hashlib
import re as re
from collections.abc import Callable as Callable
from collections.abc import Iterable as Iterable
from collections.abc import Mapping as Mapping
from dataclasses import replace as replace
from typing import Any as Any

from redis_intel.frontend import ParseResult as ParseResult
from redis_intel.frontend import RawRedisCallsite as RawRedisCallsite
from redis_intel.frontend import RawScope as RawScope
from redis_intel.frontend import Span as Span
from redis_intel.governance.conn_config_redaction import (
    redact_conn_config as redact_conn_config,
)
from redis_intel.ir.builder_client import _ClientMixin
from redis_intel.ir.builder_ingest import _IngestMixin
from redis_intel.ir.builder_ops import _OpEmitterMixin
from redis_intel.ir.builder_ordering import _OrderingMixin
from redis_intel.ir.builder_shared import (
    _CLIENT_LIBRARIES_BY_HINT as _CLIENT_LIBRARIES_BY_HINT,
)
from redis_intel.ir.builder_shared import (
    _EPISTEMIC_DETERMINISTIC_FACT as _EPISTEMIC_DETERMINISTIC_FACT,
)
from redis_intel.ir.builder_shared import (
    _EPISTEMIC_STATIC_INFERENCE as _EPISTEMIC_STATIC_INFERENCE,
)
from redis_intel.ir.builder_shared import _EPISTEMIC_UNKNOWN as _EPISTEMIC_UNKNOWN
from redis_intel.ir.builder_shared import _METHOD_OP_KINDS as _METHOD_OP_KINDS
from redis_intel.ir.builder_shared import _PROVENANCE as _PROVENANCE
from redis_intel.ir.builder_shared import (
    _SIGNATURE_HASH_SALT as _SIGNATURE_HASH_SALT,
)
from redis_intel.ir.builder_shared import (
    _TEMPLATE_SLOT_PATTERN as _TEMPLATE_SLOT_PATTERN,
)
from redis_intel.ir.builder_shared import (
    _TTL_BEARING_METHODS as _TTL_BEARING_METHODS,
)
from redis_intel.ir.builder_shared import _classify_key_expr as _classify_key_expr
from redis_intel.ir.builder_shared import _classify_serializer as _classify_serializer
from redis_intel.ir.builder_shared import (
    _derive_namespace_prefix as _derive_namespace_prefix,
)
from redis_intel.ir.builder_shared import _extract_slot_name as _extract_slot_name
from redis_intel.ir.builder_shared import _is_concatenation as _is_concatenation
from redis_intel.ir.builder_shared import _is_string_literal as _is_string_literal
from redis_intel.ir.builder_shared import _is_template as _is_template
from redis_intel.ir.builder_shared import _key_sort_slots as _key_sort_slots
from redis_intel.ir.builder_shared import (
    _resolve_ttl_seconds as _resolve_ttl_seconds,
)
from redis_intel.ir.builder_shared import _signature_hash as _signature_hash
from redis_intel.ir.builder_shared import _span_to_tuple as _span_to_tuple
from redis_intel.ir.builder_shared import (
    _ttl_argument_index as _ttl_argument_index,
)
from redis_intel.ir.builder_ttl import _TtlSerializerMixin
from redis_intel.ir.models import IR_SCHEMA_VERSION as IR_SCHEMA_VERSION
from redis_intel.ir.models import Client as Client
from redis_intel.ir.models import Edge as Edge
from redis_intel.ir.models import FileRow as FileRow
from redis_intel.ir.models import IrDelta as IrDelta
from redis_intel.ir.models import KeyExpr as KeyExpr
from redis_intel.ir.models import Namespace as Namespace
from redis_intel.ir.models import Op as Op
from redis_intel.ir.models import Revision as Revision
from redis_intel.ir.models import Scope as Scope
from redis_intel.ir.models import Serializer as Serializer
from redis_intel.ir.models import Symbol as Symbol
from redis_intel.ir.models import TtlSource as TtlSource
from redis_intel.ir.models import UnknownEntry as UnknownEntry
from redis_intel.ir.resolution import (
    ClientChainResolver as ClientChainResolver,
)
from redis_intel.ir.resolution import ResolvedClient as ResolvedClient


class IrBuilder:
    """Build an :class:`IrDelta` from ParseResults (contract §4.1)."""

    @staticmethod
    def ingest(
        parse_results: Iterable[ParseResult],
        *,
        redactor: Callable[[Mapping[str, Any]], Mapping[str, Any]] = redact_conn_config,
    ) -> IrDelta:
        return _Ingestion(parse_results, redactor).build()


class _Ingestion(
    _OrderingMixin,
    _IngestMixin,
    _ClientMixin,
    _OpEmitterMixin,
    _TtlSerializerMixin,
):
    """One ingestion pass; holds the mutable build state for one IrDelta."""

    def __init__(
        self,
        parse_results: Iterable[ParseResult],
        redactor: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> None:
        self._parse_results = list(parse_results)
        self._redactor = redactor
        self._revisions: list[Revision] = []
        self._files: list[FileRow] = []
        self._scopes: list[Scope] = []
        self._symbols: list[Symbol] = []
        self._clients: list[Client] = []
        self._operations: list[Op] = []
        self._key_expressions: list[KeyExpr] = []
        self._namespaces: list[Namespace] = []
        self._serializers: list[Serializer] = []
        self._ttl_sources: list[TtlSource] = []
        self._edges: list[Edge] = []
        self._unknowns: list[UnknownEntry] = []
        # Natural-key fields declared by contract §4.5 that the frozen row
        # schemas do not carry (scope start column, client call span, the file
        # path of path-less rows) are captured at ingestion time in parallel
        # lists so §4.2 ordering-before-id-assignment can be honoured.
        self._scope_start_columns: list[int] = []
        self._client_call_spans: list[tuple[int, int, int, int]] = []
        self._unknown_file_paths: list[str] = []
        self._ttl_source_file_paths: list[str] = []

    def build(self) -> IrDelta:
        for parse_result in self._parse_results:
            self._ingest_one(parse_result)
        self._revisions.append(
            Revision(
                git_ref="unversioned",
                parent_revision_id=None,
                kind="full",
                file_count=len(self._files),
            )
        )
        return self._order_by_natural_key()
