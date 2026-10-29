"""Typed shared state for the split mixins (style contract rule 8).

Pyright analyses each mixin in isolation; declaring the state and the
cross-mixin members here makes the inherited surface explicit without
changing any runtime behaviour."""

from collections.abc import Callable
from typing import Any


class _ResolverState:
    _functions: Any
    _methods: Any
    _bindings: Any
    _import_aliases: Any
    _require_aliases: Any
    _tree: Any

    _concrete_client_from_factory: Callable[..., Any]
    _concrete_client_from_new: Callable[..., Any]
    _constructor_library: Callable[..., Any]
    _dynamic_unknown_client: Callable[..., Any]
    _require_package: Callable[..., Any]
    _resolve_expression_node: Callable[..., Any]
    _resolve_through_function: Callable[..., Any]
    _wrapper_depth_exceeded_client: Callable[..., Any]
    _annotation_base_name: Callable[..., Any]
    _record_class_field_initializers: Callable[..., Any]
    _record_function_declaration: Callable[..., Any]
    _record_method_definition: Callable[..., Any]
    _record_this_assignment: Callable[..., Any]
    _record_variable_declarator: Callable[..., Any]
    _extract_conn_config: Callable[..., Any]
    _resolve_binding: Callable[..., Any]
    _resolve_call_binding: Callable[..., Any]
    _resolve_new_call: Callable[..., Any]
    _record_require_declarator: Callable[..., Any]
    _resolve_injection: Callable[..., Any]
