"""Frozen dataclasses of the C-2 IR surface.

Contract ``ir-boundary`` rev 2, sections 4.2/4.3.

Mirrors the storage-normative DDL of PLAN section 2.4 column-for-column: same
field names, same enums, six-tier epistemic on every claim-bearing row. The
dataclass field order below is the serialization-relied-on declaration order;
change it only together with a contract revision bump (IR_SCHEMA_VERSION).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from redis_intel.ir.model_edges import Edge, Serializer, TtlSource
from redis_intel.ir.model_schema import (
    CLIENT_LIBRARIES,
    EDGE_TYPES,
    EPISTEMIC_TIERS,
    GRAMMAR_IDS,
    IR_SCHEMA_VERSION,
    KEY_EXPR_KINDS,
    NODE_KINDS,
    OP_KINDS,
    REVISION_KINDS,
    SCOPE_KINDS,
    SERIALIZER_METHODS,
    SUBJECT_KINDS,
    SYMBOL_KINDS,
    UNKNOWN_REASONS,
    Revision,
)
from redis_intel.ir.model_schema import (
    require_enum_value as _require_enum_value,
)
from redis_intel.ir.model_schema import (
    require_evidence_json as _require_evidence_json,
)
from redis_intel.ir.model_schema import (
    require_non_negative_int as _require_non_negative_int,
)
from redis_intel.ir.model_schema import (
    require_type as _require_type,
)
from redis_intel.ir.model_schema import (
    sorted_json_value as _sorted_json_value,
)

__all__ = [
    "CLIENT_LIBRARIES",
    "EDGE_TYPES",
    "Edge",
    "EPISTEMIC_TIERS",
    "GRAMMAR_IDS",
    "IR_SCHEMA_VERSION",
    "KEY_EXPR_KINDS",
    "NODE_KINDS",
    "OP_KINDS",
    "REVISION_KINDS",
    "SCOPE_KINDS",
    "SERIALIZER_METHODS",
    "Serializer",
    "SUBJECT_KINDS",
    "SYMBOL_KINDS",
    "TtlSource",
    "UNKNOWN_REASONS",
    "Revision",
]


@dataclass(frozen=True)
class FileRow:
    path: str
    content_hash: str
    grammar_id: str
    grammar_version: str
    size_bytes: int
    loc: int

    def __post_init__(self) -> None:
        _require_type(self.path, str, "path")
        _require_type(self.content_hash, str, "content_hash")
        if len(self.content_hash) != 64 or any(
            char not in "0123456789abcdef" for char in self.content_hash
        ):
            raise ValueError(
                f"content_hash must be lowercase hex sha256 (64 chars), got"
                f" {self.content_hash!r}"
            )
        _require_enum_value(self.grammar_id, GRAMMAR_IDS, "grammar_id")
        _require_type(self.grammar_version, str, "grammar_version")
        _require_non_negative_int(self.size_bytes, "size_bytes")
        _require_non_negative_int(self.loc, "loc")


@dataclass(frozen=True)
class Scope:
    file_id: int
    kind: str
    name: str
    signature_hash: str
    start_line: int
    end_line: int
    epistemic: str
    evidence_json: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_enum_value(self.kind, SCOPE_KINDS, "kind")
        _require_type(self.name, str, "name")
        _require_type(self.signature_hash, str, "signature_hash")
        _require_non_negative_int(self.start_line, "start_line")
        if self.start_line < 1:
            raise ValueError(f"start_line must be >= 1, got {self.start_line}")
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line {self.end_line} must be >= start_line {self.start_line}"
            )
        _require_enum_value(self.epistemic, EPISTEMIC_TIERS, "epistemic")
        object.__setattr__(
            self,
            "evidence_json",
            _require_evidence_json(self.evidence_json, "evidence_json"),
        )


@dataclass(frozen=True)
class Symbol:
    file_id: int
    scope_id: int | None
    kind: str
    name: str
    epistemic: str
    evidence_json: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_enum_value(self.kind, SYMBOL_KINDS, "kind")
        _require_type(self.name, str, "name")
        _require_enum_value(self.epistemic, EPISTEMIC_TIERS, "epistemic")
        object.__setattr__(
            self,
            "evidence_json",
            _require_evidence_json(self.evidence_json, "evidence_json"),
        )


@dataclass(frozen=True)
class Client:
    file_id: int
    scope_id: int | None
    client_library: str
    construction: str
    conn_config: Mapping[str, Any]
    wrapper_depth: int
    epistemic: str
    evidence_json: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_enum_value(self.client_library, CLIENT_LIBRARIES, "client_library")
        _require_type(self.construction, str, "construction")
        _require_type(self.conn_config, dict, "conn_config")
        _require_non_negative_int(self.wrapper_depth, "wrapper_depth")
        _require_enum_value(self.epistemic, EPISTEMIC_TIERS, "epistemic")
        object.__setattr__(
            self,
            "evidence_json",
            _require_evidence_json(self.evidence_json, "evidence_json"),
        )


@dataclass(frozen=True)
class Op:
    file_id: int
    scope_id: int
    client_id: int | None
    kind: str
    method: str
    key_expr_id: int | None
    args: tuple[str, ...]
    ttl_source_id: int | None
    line: int
    epistemic: str
    evidence_json: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_enum_value(self.kind, OP_KINDS, "kind")
        _require_type(self.method, str, "method")
        _require_non_negative_int(self.line, "line")
        if self.line < 1:
            raise ValueError(f"line must be >= 1, got {self.line}")
        _require_enum_value(self.epistemic, EPISTEMIC_TIERS, "epistemic")
        object.__setattr__(
            self,
            "evidence_json",
            _require_evidence_json(self.evidence_json, "evidence_json"),
        )


@dataclass(frozen=True)
class KeyExpr:
    file_id: int
    scope_id: int
    kind: str
    template: str
    slots: tuple[Mapping[str, Any], ...]
    line: int
    epistemic: str
    evidence_json: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_enum_value(self.kind, KEY_EXPR_KINDS, "kind")
        _require_type(self.template, str, "template")
        _require_non_negative_int(self.line, "line")
        if self.line < 1:
            raise ValueError(f"line must be >= 1, got {self.line}")
        _require_enum_value(self.epistemic, EPISTEMIC_TIERS, "epistemic")
        object.__setattr__(
            self, "slots", tuple(_sorted_json_value(dict(slot)) for slot in self.slots)
        )
        object.__setattr__(
            self,
            "evidence_json",
            _require_evidence_json(self.evidence_json, "evidence_json"),
        )


@dataclass(frozen=True)
class Namespace:
    prefix: str
    epistemic: str
    evidence_json: Mapping[str, Any]

    def __post_init__(self) -> None:
        _require_type(self.prefix, str, "prefix")
        _require_enum_value(self.epistemic, EPISTEMIC_TIERS, "epistemic")
        object.__setattr__(
            self,
            "evidence_json",
            _require_evidence_json(self.evidence_json, "evidence_json"),
        )


@dataclass(frozen=True)
class UnknownEntry:
    subject_kind: str
    reason: str
    span: tuple[int, int, int, int] | None
    detail: str

    def __post_init__(self) -> None:
        _require_enum_value(self.subject_kind, SUBJECT_KINDS, "subject_kind")
        _require_enum_value(self.reason, UNKNOWN_REASONS, "reason")
        _require_type(self.detail, str, "detail")
        if not self.detail:
            raise ValueError("detail must be non-empty")


@dataclass(frozen=True)
class Tombstone:
    entity_kind: str
    logical_id: int
    reason: str


@dataclass(frozen=True)
class IrDelta:
    """The versioned 14-entity IR delta (contract section 4.2)."""

    schema_version: str
    revisions: tuple[Revision, ...]
    files: tuple[FileRow, ...]
    scopes: tuple[Scope, ...]
    symbols: tuple[Symbol, ...]
    clients: tuple[Client, ...]
    ops: tuple[Op, ...]
    key_exprs: tuple[KeyExpr, ...]
    namespaces: tuple[Namespace, ...]
    serializers: tuple[Serializer, ...]
    ttl_sources: tuple[TtlSource, ...]
    edges: tuple[Edge, ...]
    unknowns: tuple[UnknownEntry, ...]
    tombstones: tuple[Tombstone, ...]

    def __post_init__(self) -> None:
        _require_type(self.schema_version, str, "schema_version")
