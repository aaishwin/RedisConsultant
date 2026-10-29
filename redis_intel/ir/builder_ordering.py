"""Natural-key ordering and logical-id assignment for one ingestion pass."""

from dataclasses import replace
from typing import Any

from redis_intel.ir.builder_state import _IngestionState
from redis_intel.ir.models import IR_SCHEMA_VERSION, IrDelta


class _OrderingMixin(_IngestionState):
    """Sort each collection by its §4.5 natural key, then assign ids 1..n."""

    def _order_by_natural_key(self) -> IrDelta:
        """Order every collection by its §4.5 natural key, then assign ids 1..n.

        Rows are ingested in source order; contract §4.2/§4.5 requires rows of
        each kind ordered by the kind's natural key *before* ids are assigned,
        with every cross-reference (file_id, scope_id, client_id,
        key_expr_id, ttl_source_id, op_id, edge endpoints) using those final
        logical ids. Fields the frozen row schemas do not carry but the
        natural keys declare (scope start column, client call span, the file
        path of path-less rows) are read from the parallel lists captured at
        ingestion time. Sorting is stable, so rows whose full natural key
        ties keep their deterministic ingestion order.
        """
        file_paths = {id_: row.path for id_, row in enumerate(self._files, start=1)}
        scope_names = {id_: row.name for id_, row in enumerate(self._scopes, start=1)}
        file_keys = {id_: (path,) for id_, path in file_paths.items()}
        scope_keys = {
            id_: (
                file_paths[row.file_id],
                row.name,
                row.start_line,
                self._scope_start_columns[id_ - 1],
            )
            for id_, row in enumerate(self._scopes, start=1)
        }
        symbol_keys = {
            id_: (
                file_paths[row.file_id],
                scope_names[row.scope_id] if row.scope_id is not None else "",
                row.name,
                row.kind,
            )
            for id_, row in enumerate(self._symbols, start=1)
        }
        client_keys = {
            id_: (
                file_paths[row.file_id],
                scope_names[row.scope_id] if row.scope_id is not None else "",
                row.construction,
                self._client_call_spans[id_ - 1],
            )
            for id_, row in enumerate(self._clients, start=1)
        }
        operation_keys = {
            id_: (file_paths[row.file_id], row.line, row.method, row.kind)
            for id_, row in enumerate(self._operations, start=1)
        }
        key_expr_keys = {
            id_: (file_paths[row.file_id], row.kind, row.template, row.line)
            for id_, row in enumerate(self._key_expressions, start=1)
        }
        serializer_keys = {
            id_: (operation_keys[row.op_id], row.method)
            for id_, row in enumerate(self._serializers, start=1)
        }
        ttl_source_keys = {
            id_: (
                self._ttl_source_file_paths[id_ - 1],
                row.expression,
                -1 if row.resolved_seconds is None else row.resolved_seconds,
            )
            for id_, row in enumerate(self._ttl_sources, start=1)
        }
        node_keys_by_kind: dict[str, dict[int, tuple[Any, ...]]] = {
            "file": file_keys,
            "scope": scope_keys,
            "symbol": symbol_keys,
            "client": client_keys,
            "op": operation_keys,
            "key_expr": key_expr_keys,
        }

        def order_collection(
            rows: list[Any], keys_by_id: dict[int, tuple[Any, ...]]
        ) -> tuple[list[Any], dict[int, int]]:
            ordered = sorted(
                ((keys_by_id[id_], id_, row) for id_, row in enumerate(rows, start=1)),
                key=lambda entry: entry[0],
            )
            id_map = {
                old_id: new_id for new_id, (_, old_id, _) in enumerate(ordered, start=1)
            }
            return [entry[2] for entry in ordered], id_map

        ordered_files, file_id_map = order_collection(self._files, file_keys)
        ordered_scope_rows, scope_id_map = order_collection(self._scopes, scope_keys)
        ordered_symbol_rows, _ = order_collection(self._symbols, symbol_keys)
        ordered_client_rows, client_id_map = order_collection(
            self._clients, client_keys
        )
        ordered_operation_rows, operation_id_map = order_collection(
            self._operations, operation_keys
        )
        ordered_key_expression_rows, key_expr_id_map = order_collection(
            self._key_expressions, key_expr_keys
        )
        ordered_serializer_rows, _ = order_collection(
            self._serializers, serializer_keys
        )
        ordered_ttl_source_rows, ttl_source_id_map = order_collection(
            self._ttl_sources, ttl_source_keys
        )
        ordered_namespaces, _ = order_collection(
            self._namespaces,
            {id_: (row.prefix,) for id_, row in enumerate(self._namespaces, start=1)},
        )
        ordered_revisions, _ = order_collection(
            self._revisions,
            {id_: (row.git_ref,) for id_, row in enumerate(self._revisions, start=1)},
        )

        def node_natural_key(kind: str, temp_id: int) -> tuple[Any, ...]:
            table = node_keys_by_kind.get(kind)
            if table is None:
                return ()
            return table[temp_id]

        def remap_node_id(kind: str, temp_id: int) -> int:
            id_map_by_kind = {
                "file": file_id_map,
                "scope": scope_id_map,
                "client": client_id_map,
                "op": operation_id_map,
                "key_expr": key_expr_id_map,
            }
            id_map = id_map_by_kind.get(kind)
            if id_map is None:
                return temp_id
            return id_map.get(temp_id, temp_id)

        edge_pairs = sorted(
            (
                (
                    (
                        row.source_kind,
                        node_natural_key(row.source_kind, row.source_id),
                        row.edge_type,
                        row.target_kind,
                        node_natural_key(row.target_kind, row.target_id),
                    ),
                    row,
                )
                for row in self._edges
            ),
            key=lambda entry: entry[0],
        )
        ordered_edges = [
            replace(
                row,
                source_id=remap_node_id(row.source_kind, row.source_id),
                target_id=remap_node_id(row.target_kind, row.target_id),
            )
            for _, row in edge_pairs
        ]

        def remap_file_id(row: Any) -> Any:
            return replace(row, file_id=file_id_map.get(row.file_id, row.file_id))

        def remap_file_and_scope(rows: list[Any]) -> list[Any]:
            # Symbol, Client and KeyExpr carry exactly a file_id plus an
            # optional scope_id, so one remap serves all three kinds.
            # (Scope carries only a file_id — handled by remap_file_id.)
            return [
                replace(
                    row,
                    file_id=file_id_map.get(row.file_id, row.file_id),
                    scope_id=(
                        scope_id_map.get(row.scope_id, row.scope_id)
                        if row.scope_id is not None
                        else None
                    ),
                )
                for row in rows
            ]

        ordered_scopes = [remap_file_id(row) for row in ordered_scope_rows]
        ordered_symbols = remap_file_and_scope(ordered_symbol_rows)
        ordered_clients = remap_file_and_scope(ordered_client_rows)
        ordered_key_expressions = remap_file_and_scope(ordered_key_expression_rows)
        ordered_operations = [
            replace(
                row,
                file_id=file_id_map.get(row.file_id, row.file_id),
                scope_id=scope_id_map.get(row.scope_id, row.scope_id),
                client_id=(
                    client_id_map.get(row.client_id, row.client_id)
                    if row.client_id is not None
                    else None
                ),
                key_expr_id=(
                    key_expr_id_map.get(row.key_expr_id, row.key_expr_id)
                    if row.key_expr_id is not None
                    else None
                ),
                ttl_source_id=(
                    ttl_source_id_map.get(row.ttl_source_id, row.ttl_source_id)
                    if row.ttl_source_id is not None
                    else None
                ),
            )
            for row in ordered_operation_rows
        ]
        ordered_serializers = [
            replace(row, op_id=operation_id_map.get(row.op_id, row.op_id))
            for row in ordered_serializer_rows
        ]
        unknown_pairs = sorted(
            (
                (
                    (
                        row.subject_kind,
                        row.reason,
                        self._unknown_file_paths[index],
                        row.span if row.span is not None else (),
                    ),
                    row,
                )
                for index, row in enumerate(self._unknowns)
            ),
            key=lambda entry: entry[0],
        )
        ordered_unknowns = [row for _, row in unknown_pairs]
        return IrDelta(
            schema_version=IR_SCHEMA_VERSION,
            revisions=tuple(ordered_revisions),
            files=tuple(ordered_files),
            scopes=tuple(ordered_scopes),
            symbols=tuple(ordered_symbols),
            clients=tuple(ordered_clients),
            ops=tuple(ordered_operations),
            key_exprs=tuple(ordered_key_expressions),
            namespaces=tuple(ordered_namespaces),
            serializers=tuple(ordered_serializers),
            ttl_sources=tuple(ordered_ttl_source_rows),
            edges=tuple(ordered_edges),
            unknowns=tuple(ordered_unknowns),
            tombstones=(),
        )
