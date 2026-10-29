"""Ingest one ParseResult into rows: files, scopes, symbols, callsites."""

from redis_intel.frontend import ParseResult, RawScope
from redis_intel.ir.builder_shared import (
    _EPISTEMIC_DETERMINISTIC_FACT,
    _PROVENANCE,
    _signature_hash,
    _span_to_tuple,
)
from redis_intel.ir.builder_state import _IngestionState
from redis_intel.ir.models import Edge, FileRow, Scope, Symbol, UnknownEntry
from redis_intel.ir.resolution import ClientChainResolver


class _IngestMixin(_IngestionState):
    """Turn each ParseResult into rows, deferring ordering to the build step."""

    def _ingest_one(self, parse_result: ParseResult) -> None:
        # Unresolved constructs are recorded before the grammar gate: an
        # unsupported-grammar file produces no files row (the files.grammar_id
        # enum has no "unsupported" member, contract §4.3) but its
        # unsupported_syntax entry must still be recorded (§5.3 — no silent
        # drops, no crash). C-1 §3.1 guarantees such a ParseResult carries no
        # tree, no callsites, and no scopes.
        for unresolved_node in parse_result.unresolved:
            unknown_span = (
                _span_to_tuple(unresolved_node.span)
                if unresolved_node.span is not None
                else None
            )
            # An unresolvable_expression is expression-level (it always carries
            # a span); file-level reasons (unsupported_syntax, file_too_large,
            # node_budget_exceeded, parse_error regions) stay subject_kind="file".
            subject_kind = (
                "callsite"
                if unresolved_node.reason == "unresolvable_expression"
                else "file"
            )
            self._unknown_file_paths.append(parse_result.path)
            self._unknowns.append(
                UnknownEntry(
                    subject_kind=subject_kind,
                    reason=unresolved_node.reason,
                    span=unknown_span,
                    detail=unresolved_node.detail,
                )
            )
        if parse_result.grammar_id == "unsupported":
            return
        file_id = len(self._files) + 1
        self._files.append(
            FileRow(
                path=parse_result.path,
                content_hash=parse_result.content_hash,
                grammar_id=parse_result.grammar_id,
                grammar_version=parse_result.grammar_version,
                size_bytes=parse_result.size_bytes,
                loc=parse_result.loc,
            )
        )
        scope_ids = self._ingest_scopes(parse_result, file_id)
        self._ingest_callsites(parse_result, file_id, scope_ids)

    def _ingest_scopes(self, parse_result: ParseResult, file_id: int) -> dict[int, int]:
        """Ingest scopes; map raw scope index to scope id."""
        scope_ids: dict[int, int] = {}
        for scope_index, raw_scope in enumerate(parse_result.scopes):
            scope_id = len(self._scopes) + 1
            scope_ids[scope_index] = scope_id
            raw_scope_span = _span_to_tuple(raw_scope.span)
            self._scopes.append(
                Scope(
                    file_id=file_id,
                    kind=raw_scope.kind,
                    name=raw_scope.name,
                    signature_hash=_signature_hash(raw_scope.signature_text),
                    start_line=raw_scope_span[0],
                    end_line=raw_scope_span[2],
                    epistemic=_EPISTEMIC_DETERMINISTIC_FACT,
                    evidence_json={
                        "provenance": _PROVENANCE,
                        "signature_text": raw_scope.signature_text,
                    },
                )
            )
            self._scope_start_columns.append(raw_scope_span[1])
            self._symbols.append(
                Symbol(
                    file_id=file_id,
                    scope_id=scope_id,
                    kind="unknown",
                    name=raw_scope.name,
                    epistemic=_EPISTEMIC_DETERMINISTIC_FACT,
                    evidence_json={
                        "provenance": _PROVENANCE,
                        "derived_from": "scope",
                    },
                )
            )
            self._edges.append(
                Edge(
                    source_kind="file",
                    source_id=file_id,
                    edge_type="CALLS",
                    target_kind="scope",
                    target_id=scope_id,
                    evidence_json={
                        "provenance": _PROVENANCE,
                        "signature_text": raw_scope.signature_text,
                    },
                    epistemic=_EPISTEMIC_DETERMINISTIC_FACT,
                )
            )
        return scope_ids

    def _ingest_callsites(
        self, parse_result: ParseResult, file_id: int, scope_ids: dict[int, int]
    ) -> None:
        resolver = (
            ClientChainResolver(parse_result.tree)
            if parse_result.tree is not None
            else None
        )
        for callsite_index, callsite in enumerate(parse_result.redis_callsites):
            scope_id = self._scope_for_callsite(
                _span_to_tuple(callsite.span), parse_result.scopes, scope_ids
            )
            # A construction callsite's receiver IS the construction itself;
            # asking the name resolver would let an unrelated local binding of
            # the same name (e.g. a factory handle) shadow the construction.
            resolved_client = (
                resolver.resolve(callsite.receiver_text)
                if resolver is not None and callsite.method != "new"
                else None
            )
            client_id = self._emit_client_row(
                parse_result,
                file_id,
                scope_id,
                callsite,
                callsite_index,
                resolved_client,
            )
            self._emit_op_and_key_expr(
                parse_result,
                file_id,
                scope_id,
                client_id,
                callsite,
                callsite_index,
                resolved_client.resolution if resolved_client is not None else None,
            )

    def _scope_for_callsite(
        self,
        span: tuple[int, int, int, int],
        raw_scopes: tuple[RawScope, ...],
        scope_ids: dict[int, int],
    ) -> int | None:
        """Find the innermost scope containing the callsite's start line."""
        best_scope_id: int | None = None
        best_end_line = -1
        for scope_index, raw_scope in enumerate(raw_scopes):
            raw_scope_span = _span_to_tuple(raw_scope.span)
            if (
                raw_scope_span[0] <= span[0] <= raw_scope_span[2]
                and raw_scope_span[2] >= best_end_line
            ):
                best_end_line = raw_scope_span[2]
                best_scope_id = scope_ids[scope_index]
        return best_scope_id
