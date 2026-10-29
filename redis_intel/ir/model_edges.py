"""Serializer, TTL-source and graph-edge dataclasses of the C-2 IR.

Split out of :mod:`redis_intel.ir.models` so that module stays inside the
repository's 250-code-line limit (style contract rule 8). ``models`` re-exports
these classes, so external imports are unchanged.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from redis_intel.ir.model_schema import (
    EDGE_TYPES,
    EPISTEMIC_TIERS,
    NODE_KINDS,
    SERIALIZER_METHODS,
    require_enum_value,
    require_evidence_json,
    require_type,
)


@dataclass(frozen=True)
class Serializer:
    op_id: int
    method: str
    epistemic: str
    evidence_json: Mapping[str, Any]

    def __post_init__(self) -> None:
        require_type(self.op_id, int, "op_id")
        require_enum_value(self.method, SERIALIZER_METHODS, "method")
        require_enum_value(self.epistemic, EPISTEMIC_TIERS, "epistemic")
        object.__setattr__(
            self,
            "evidence_json",
            require_evidence_json(self.evidence_json, "evidence_json"),
        )


@dataclass(frozen=True)
class TtlSource:
    expression: str
    resolved_seconds: int | None
    epistemic: str
    evidence_json: Mapping[str, Any]

    def __post_init__(self) -> None:
        require_type(self.expression, str, "expression")
        require_enum_value(self.epistemic, EPISTEMIC_TIERS, "epistemic")
        object.__setattr__(
            self,
            "evidence_json",
            require_evidence_json(self.evidence_json, "evidence_json"),
        )


@dataclass(frozen=True)
class Edge:
    source_kind: str
    source_id: int
    edge_type: str
    target_kind: str
    target_id: int
    evidence_json: Mapping[str, Any]
    epistemic: str

    def __post_init__(self) -> None:
        require_enum_value(self.source_kind, NODE_KINDS, "source_kind")
        require_enum_value(self.edge_type, EDGE_TYPES, "edge_type")
        require_enum_value(self.target_kind, NODE_KINDS, "target_kind")
        require_enum_value(self.epistemic, EPISTEMIC_TIERS, "epistemic")
        object.__setattr__(
            self,
            "evidence_json",
            require_evidence_json(self.evidence_json, "evidence_json"),
        )
