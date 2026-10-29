"""Client-row emission, including the single governance redaction seam."""

from collections.abc import Mapping
from typing import Any

from redis_intel.frontend import ParseResult, RawRedisCallsite
from redis_intel.ir.builder_shared import (
    _CLIENT_LIBRARIES_BY_HINT,
    _EPISTEMIC_STATIC_INFERENCE,
    _PROVENANCE,
    _span_to_tuple,
)
from redis_intel.ir.builder_state import _IngestionState
from redis_intel.ir.models import Client, Edge
from redis_intel.ir.resolution import ResolvedClient


class _ClientMixin(_IngestionState):
    """Emit the redacted clients row and its CALLS edge for one callsite."""

    def _emit_client_row(
        self,
        parse_result: ParseResult,
        file_id: int,
        scope_id: int | None,
        callsite: RawRedisCallsite,
        callsite_index: int,
        resolved_client: ResolvedClient | None,
    ) -> int | None:
        if resolved_client is not None:
            construction = resolved_client.construction
        elif callsite.client_hint is not None:
            construction = f"alias:{callsite.receiver_text}"
        else:
            construction = f"receiver:{callsite.receiver_text}"
        raw_config = self._raw_conn_config(
            parse_result, callsite, callsite_index, resolved_client
        )
        redacted_config = self._redactor(raw_config)
        client_library = (
            resolved_client.client_library
            if resolved_client is not None
            else _CLIENT_LIBRARIES_BY_HINT.get(callsite.client_hint or "", "unknown")
        )
        epistemic = (
            resolved_client.epistemic
            if resolved_client is not None
            else _EPISTEMIC_STATIC_INFERENCE
        )
        wrapper_depth = (
            resolved_client.wrapper_depth if resolved_client is not None else 0
        )
        evidence_json: dict[str, Any] = {
            "provenance": _PROVENANCE,
            "redaction": {"callsite_index": callsite_index},
        }
        if resolved_client is not None:
            evidence_json.update(resolved_client.evidence_json)
        else:
            evidence_json["unresolved_reason"] = "dynamic_construction"
            evidence_json["model_hypothesis_candidate"] = True
            evidence_json["DEPTH"] = 0
        client = Client(
            file_id=file_id,
            scope_id=scope_id,
            client_library=client_library,
            construction=construction,
            conn_config=redacted_config,
            wrapper_depth=wrapper_depth,
            epistemic=epistemic,
            evidence_json=evidence_json,
        )
        self._clients.append(client)
        self._client_call_spans.append(_span_to_tuple(callsite.span))
        client_id = len(self._clients)
        # A callsite outside every scope binds at file level; emit the edge
        # from the file node so the endpoint kind always matches the id space
        # of its id (needed for the §4.5 natural-key remap of edge endpoints).
        edge_source_kind = "scope" if scope_id is not None else "file"
        self._edges.append(
            Edge(
                source_kind=edge_source_kind,
                source_id=scope_id if scope_id is not None else file_id,
                edge_type="CALLS",
                target_kind="client",
                target_id=client_id,
                evidence_json=evidence_json,
                epistemic=epistemic,
            )
        )
        return client_id

    def _raw_conn_config(
        self,
        parse_result: ParseResult,
        callsite: RawRedisCallsite,
        callsite_index: int,
        resolved_client: ResolvedClient | None,
    ) -> Mapping[str, Any]:
        if resolved_client is not None and resolved_client.conn_config:
            return resolved_client.conn_config
        return {
            "receiver_text": callsite.receiver_text,
            "callsite_index": callsite_index,
        }
