"""UNKNOWN row builders for dynamic and over-deep chains."""

from typing import Any

from redis_intel.ir.resolution_shared import (
    _EPISTEMIC_UNKNOWN,
    _MODEL_HYPOTHESIS_CANDIDATE_FLAG,
    _PROVENANCE_ATTRIBUTE,
    _REASON_DYNAMIC_CONSTRUCTION,
    _REASON_WRAPPER_DEPTH_EXCEEDED,
    _RESOLVER_PROVENANCE,
    _WRAPPER_DEPTH_ATTRIBUTE,
    ResolvedClient,
)
from redis_intel.ir.resolution_state import _ResolverState


class EscalationMixin(_ResolverState):
    """UNKNOWN row builders for dynamic and over-deep chains."""

    def _dynamic_unknown_client(
        self,
        receiver_name: str,
        span: tuple[int, int, int, int],
        construction: str,
        depth: int,
        conn_config: dict[str, Any] | None = None,
    ) -> ResolvedClient:
        evidence_json = {
            _WRAPPER_DEPTH_ATTRIBUTE: depth,
            "unresolved_reason": _REASON_DYNAMIC_CONSTRUCTION,
            _MODEL_HYPOTHESIS_CANDIDATE_FLAG: True,
            _PROVENANCE_ATTRIBUTE: _RESOLVER_PROVENANCE,
        }
        return ResolvedClient(
            receiver_name=receiver_name,
            client_library="unknown",
            construction=construction,
            conn_config=conn_config if conn_config is not None else {},
            wrapper_depth=depth,
            epistemic=_EPISTEMIC_UNKNOWN,
            evidence_json=evidence_json,
            span=span,
        )

    def _wrapper_depth_exceeded_client(
        self,
        receiver_name: str,
        span: tuple[int, int, int, int],
        observed_depth: int,
    ) -> ResolvedClient:
        evidence_json = {
            _WRAPPER_DEPTH_ATTRIBUTE: observed_depth,
            "unresolved_reason": _REASON_WRAPPER_DEPTH_EXCEEDED,
            _MODEL_HYPOTHESIS_CANDIDATE_FLAG: True,
            _PROVENANCE_ATTRIBUTE: _RESOLVER_PROVENANCE,
        }
        return ResolvedClient(
            receiver_name=receiver_name,
            client_library="unknown",
            construction=f"wrapper_depth_{observed_depth}",
            conn_config={},
            wrapper_depth=observed_depth,
            epistemic=_EPISTEMIC_UNKNOWN,
            evidence_json=evidence_json,
            span=span,
        )
