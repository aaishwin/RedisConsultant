"""Op and key-expression emission plus their READ/WRITE/KEY_FLOW edges."""

from typing import Any

from redis_intel.frontend import ParseResult, RawRedisCallsite
from redis_intel.ir.builder_shared import (
    _EPISTEMIC_DETERMINISTIC_FACT,
    _EPISTEMIC_UNKNOWN,
    _METHOD_OP_KINDS,
    _PROVENANCE,
    _TTL_BEARING_METHODS,
    _classify_key_expr,
    _derive_namespace_prefix,
    _key_sort_slots,
    _span_to_tuple,
)
from redis_intel.ir.builder_state import _IngestionState
from redis_intel.ir.models import Edge, KeyExpr, Namespace, Op, UnknownEntry


class _OpEmitterMixin(_IngestionState):
    """Emit the ops row, its key expression, and the connecting edges."""

    def _emit_op_and_key_expr(
        self,
        parse_result: ParseResult,
        file_id: int,
        scope_id: int | None,
        client_id: int | None,
        callsite: RawRedisCallsite,
        callsite_index: int,
        resolution: str | None,
    ) -> None:
        op_kind = _METHOD_OP_KINDS.get(callsite.method.lower(), "READ")
        # A construction callsite ("new Redis(...)") takes connection config
        # as its arguments — connection config, not key space (contract §4.2:
        # conn_config is a clients field, redacted at the §6 seam). Mirroring
        # that argument into key_exprs/ops/namespaces/unknowns rows would
        # persist raw credentials (NFR-4), so a construction callsite is
        # represented only by its redacted clients row plus an op row with
        # empty args recording that the call exists. Not a sentinel-specific
        # filter: it applies to every construction form the frontend yields
        # with method="new" (§3.4).
        is_construction_callsite = callsite.method == "new"
        key_expr_id = (
            None
            if is_construction_callsite
            else self._emit_key_expr(
                parse_result, file_id, scope_id, callsite, callsite_index
            )
        )
        ttl_source_id = (
            self._emit_ttl_source(callsite, parse_result.path)
            if op_kind == "EXPIRE" or callsite.method.lower() in _TTL_BEARING_METHODS
            else None
        )
        op_evidence_json: dict[str, Any] = {
            "provenance": _PROVENANCE,
            "callsite_index": callsite_index,
        }
        if resolution is not None:
            # Additive contract rev 3 §8 metadata: which §3.4 rule resolved
            # the receiver of this callsite.
            op_evidence_json["resolution"] = resolution
        operation = Op(
            file_id=file_id,
            scope_id=scope_id if scope_id is not None else 0,
            client_id=client_id,
            kind=op_kind,
            method=callsite.method,
            key_expr_id=key_expr_id,
            args=() if is_construction_callsite else tuple(callsite.argument_texts),
            ttl_source_id=ttl_source_id,
            line=callsite.span.start_line,
            epistemic=_EPISTEMIC_DETERMINISTIC_FACT,
            evidence_json=op_evidence_json,
        )
        self._operations.append(operation)
        operation_id = len(self._operations)
        edge_type_by_kind = {
            "READ": "READS",
            "WRITE": "WRITES",
            "DELETE": "DELETES",
            "EXPIRE": "EXPIRES",
        }
        edge_type = edge_type_by_kind.get(op_kind)
        if edge_type is not None and key_expr_id is not None:
            self._edges.append(
                Edge(
                    source_kind="op",
                    source_id=operation_id,
                    edge_type=edge_type,
                    target_kind="key_expr",
                    target_id=key_expr_id,
                    evidence_json={
                        "provenance": _PROVENANCE,
                        "callsite_index": callsite_index,
                    },
                    epistemic=_EPISTEMIC_DETERMINISTIC_FACT,
                )
            )
        if client_id is not None and key_expr_id is not None:
            self._edges.append(
                Edge(
                    source_kind="client",
                    source_id=client_id,
                    edge_type="KEY_FLOW",
                    target_kind="key_expr",
                    target_id=key_expr_id,
                    evidence_json={
                        "provenance": _PROVENANCE,
                        "callsite_index": callsite_index,
                    },
                    epistemic=_EPISTEMIC_DETERMINISTIC_FACT,
                )
            )
        self._emit_serializer(operation_id, callsite)

    def _emit_key_expr(
        self,
        parse_result: ParseResult,
        file_id: int,
        scope_id: int | None,
        callsite: RawRedisCallsite,
        callsite_index: int,
    ) -> int | None:
        if not callsite.argument_texts:
            return None
        first_argument = callsite.argument_texts[0]
        key_kind, template, slots = _classify_key_expr(first_argument)
        epistemic = (
            _EPISTEMIC_DETERMINISTIC_FACT
            if key_kind in {"literal", "template"}
            else _EPISTEMIC_UNKNOWN
        )
        key_expr = KeyExpr(
            file_id=file_id,
            scope_id=scope_id if scope_id is not None else 0,
            kind=key_kind,
            template=template,
            slots=tuple(_key_sort_slots(slots)),
            line=callsite.span.start_line,
            epistemic=epistemic,
            evidence_json={
                "provenance": _PROVENANCE,
                "callsite_index": callsite_index,
            },
        )
        namespace_prefix = _derive_namespace_prefix(template)
        if namespace_prefix is not None:
            self._namespaces.append(
                Namespace(
                    prefix=namespace_prefix,
                    epistemic=_EPISTEMIC_DETERMINISTIC_FACT,
                    evidence_json={
                        "provenance": _PROVENANCE,
                        "template": template,
                    },
                )
            )
        self._key_expressions.append(key_expr)
        key_expr_id = len(self._key_expressions)
        if key_kind == "dynamic_unknown":
            self._edges.append(
                Edge(
                    source_kind="key_expr",
                    source_id=key_expr_id,
                    edge_type="DATA_FLOW",
                    target_kind="op",
                    target_id=len(self._operations) + 1,
                    evidence_json={
                        "provenance": _PROVENANCE,
                        "unresolved_reason": "dynamic_construction",
                        "callsite_index": callsite_index,
                    },
                    epistemic=_EPISTEMIC_UNKNOWN,
                )
            )
            self._unknown_file_paths.append(parse_result.path)
            self._unknowns.append(
                UnknownEntry(
                    subject_kind="key_expr",
                    reason="dynamic_construction",
                    span=_span_to_tuple(callsite.span),
                    detail=f"key argument built dynamically: {first_argument}",
                )
            )
        return key_expr_id
