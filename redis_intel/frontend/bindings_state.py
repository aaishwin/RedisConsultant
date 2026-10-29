"""Typed shared state for the split mixins (style contract rule 8).

Pyright analyses each mixin in isolation; declaring the state and the
cross-mixin members here makes the inherited surface explicit without
changing any runtime behaviour."""

from collections.abc import Callable
from typing import Any


class _BindingsState:
    class_fields: Any
    class_methods: Any
    factories: Any
    import_aliases: Any
    alias_bindings: Any
    call_bindings: Any
    direct_client_names: Any

    resolve_construction_client_hint: Callable[..., Any]
    resolve_local_name: Callable[..., Any]
    _constructor_package: Callable[..., Any]
    _factory_package: Callable[..., Any]
    _require_package: Callable[..., Any]
    _factory_hint_by_name: Callable[..., Any]
    _factory_return_hint_from_call: Callable[..., Any]
