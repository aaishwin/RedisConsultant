"""Receiver resolution for ``_ClientBindings`` (contract section 3.4).

Resolving a receiver expression to a client hint is the whole point of the
binding pass: R1/R2 ``this.<field>`` bindings, R3 factory returns, R4
``require`` acquisition and R5 negatives are applied here in order, first
match wins.
"""

from tree_sitter import Node

from redis_intel.frontend.bindings_state import _BindingsState
from redis_intel.frontend.bindings_types import (
    _CLASS_FIELD_KIND_CONSTRUCTION,
    _CLASS_FIELD_KIND_FACTORY,
    _CLASS_FIELD_KIND_INJECTION,
)
from redis_intel.frontend.method_names import (
    IOREDIS_CONSTRUCTOR_NAMES,
    IOREDIS_PACKAGE_NAME,
)
from redis_intel.frontend.node_structure import (
    _class_key,
    _enclosing_class,
    _unwrap_expression,
    node_text,
)


class _ResolutionMixin(_BindingsState):
    """Resolve receivers and construction expressions to a client hint."""

    def resolve_receiver_client_hint(self, receiver_node: Node) -> str | None:
        """Return the client name/alias a receiver expression resolves to, else None.

        Transparent wrappers are peeled first, so ``(await createClient()).get``
        and ``(...).get`` resolve one hop to the inner construction. Contract
        rev 3 section 3.4 adds ``this.<field>`` receivers (R1 field-initializer
        constructions, R2 constructor-parameter injections), locals bound to
        same-file factory returns (R3) and ``require``-acquired constructors
        (R4); unresolvable receivers stay non-callsites (R5).
        """
        unwrapped_node = _unwrap_expression(receiver_node)
        if unwrapped_node is None:
            return None
        if unwrapped_node.type == "identifier":
            local_hint = self.resolve_local_name(node_text(unwrapped_node))
            if local_hint is not None:
                return local_hint
            bound_call_node = self.call_bindings.get(node_text(unwrapped_node))
            if bound_call_node is not None:
                return self._factory_return_hint_from_call(bound_call_node)
            return None
        if unwrapped_node.type == "member_expression":
            object_node = unwrapped_node.child_by_field_name("object")
            if object_node is not None and object_node.type == "this":
                return self._resolve_this_field_hint(unwrapped_node)
            return self.resolve_construction_client_hint(unwrapped_node)
        if unwrapped_node.type == "call_expression":
            factory_hint = self._factory_return_hint_from_call(unwrapped_node)
            if factory_hint is not None:
                return factory_hint
            return self.resolve_construction_client_hint(unwrapped_node)
        return self.resolve_construction_client_hint(unwrapped_node)

    def _resolve_this_field_hint(self, member_node: Node) -> str | None:
        """Resolve a ``this.<field>`` receiver against its enclosing class (R1/R2)."""
        property_node = member_node.child_by_field_name("property")
        if property_node is None:
            return None
        class_node = _enclosing_class(member_node)
        if class_node is None:
            return None
        field_binding = self.class_fields.get(_class_key(class_node), {}).get(
            node_text(property_node)
        )
        if field_binding is None:
            return None
        if field_binding.kind in {
            _CLASS_FIELD_KIND_CONSTRUCTION,
            _CLASS_FIELD_KIND_INJECTION,
        }:
            return field_binding.construction_hint
        if field_binding.kind == _CLASS_FIELD_KIND_FACTORY:
            return self._factory_hint_by_name(
                field_binding.factory_name, _class_key(class_node)
            )
        if field_binding.alias_target is not None:
            return self.resolve_local_name(field_binding.alias_target)
        return None

    def resolve_construction_client_hint(self, node: Node) -> str | None:
        """Return the client name a construction expression resolves to, else None.

        Handles both construction forms: ``new Redis(...)`` (canonical
        constructor hint, contract rev 3 §3.4 R4 including require forms) and
        node-redis factory calls like ``createClient(...)`` (function text).
        """
        if node.type == "new_expression":
            constructor_node = node.child_by_field_name("constructor")
            if constructor_node is None:
                return None
            return self._constructor_hint(constructor_node)
        if node.type == "call_expression":
            function_node = node.child_by_field_name("function")
            if function_node is not None and self._factory_package(function_node):
                return node_text(function_node)
            return None
        return None

    def _constructor_hint(self, constructor_node: Node) -> str | None:
        """Return the canonical client hint a ``new <expr>(...)`` constructor names.

        ``new (require('ioredis'))(...)`` hints ``ioredis`` (R4); an aliased
        default import of ioredis hints its imported name (``Redis``) so the
        IR builder maps it to the ioredis library.
        """
        unwrapped_node = _unwrap_expression(constructor_node)
        if unwrapped_node is None:
            return None
        if unwrapped_node.type == "call_expression":
            require_package = self._require_package(unwrapped_node)
            if require_package == IOREDIS_PACKAGE_NAME:
                return IOREDIS_PACKAGE_NAME
            return None
        if unwrapped_node.type == "member_expression":
            object_node = unwrapped_node.child_by_field_name("object")
            property_node = unwrapped_node.child_by_field_name("property")
            if (
                object_node is not None
                and property_node is not None
                and self._require_package(_unwrap_expression(object_node))
                == IOREDIS_PACKAGE_NAME
                and node_text(property_node) in IOREDIS_CONSTRUCTOR_NAMES
            ):
                return node_text(property_node)
            return None
        constructor_name = node_text(unwrapped_node)
        if self._constructor_package(constructor_node):
            imported = self.import_aliases.get(constructor_name)
            if imported is not None and imported[1] != "default":
                return imported[1]
            return constructor_name
        return None

    def resolve_local_name(self, local_name: str) -> str | None:
        """Resolve a local identifier to itself when it is bound to a known client.

        One hop only: ``local_name`` may be a direct client binding or an
        alias of one; aliases of aliases do not resolve (contract section 3.4).
        """
        if local_name in self.direct_client_names:
            return local_name
        aliased_target = self.alias_bindings.get(local_name)
        if aliased_target is not None and aliased_target in self.direct_client_names:
            return local_name
        return None
