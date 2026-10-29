"""Typed shared state for the split mixins (style contract rule 8).

Pyright analyses each mixin in isolation; declaring the state and the
cross-mixin members here makes the inherited surface explicit without
changing any runtime behaviour."""

from collections.abc import Callable
from typing import Any


class _IngestionState:
    _client_call_spans: Any
    _clients: Any
    _edges: Any
    _redactor: Any
    _files: Any
    _scope_start_columns: Any
    _scopes: Any
    _symbols: Any
    _unknown_file_paths: Any
    _unknowns: Any
    _key_expressions: Any
    _namespaces: Any
    _operations: Any
    _revisions: Any
    _serializers: Any
    _ttl_source_file_paths: Any
    _ttl_sources: Any

    _emit_client_row: Callable[..., Any]
    _emit_op_and_key_expr: Callable[..., Any]
    _emit_serializer: Callable[..., Any]
    _emit_ttl_source: Callable[..., Any]
