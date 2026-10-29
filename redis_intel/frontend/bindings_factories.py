"""In-file factory recording and resolution for ``_ClientBindings`` (R3).

A same-file function whose returned expression is a client construction (or a
``this.<field>`` the class already binds) may bind a receiver, so factories are
both recorded and resolved in one place.
"""

from tree_sitter import Node

from redis_intel.frontend.bindings_state import _BindingsState
from redis_intel.frontend.bindings_types import (
    _CLASS_FIELD_KIND_CONSTRUCTION,
    _CLASS_FIELD_KIND_INJECTION,
    _FactoryDefinition,
)
from redis_intel.frontend.node_structure import (
    _TRANSPARENT_VALUE_NODE_TYPES,
    _class_key,
    _enclosing_class,
    _unwrap_expression,
    node_text,
)


class _FactoryRecordingMixin(_BindingsState):
    """Record in-file factories and resolve the receivers they bind."""

    def _factory_hint_by_name(
        self, factory_name: str | None, class_key: tuple[int, int] | None
    ) -> str | None:
        if factory_name is None:
            return None
        definition = self.factories.get(factory_name)
        if definition is None and class_key is not None:
            definition = self.class_methods.get(class_key, {}).get(factory_name)
        if definition is None:
            return None
        return self._factory_return_hint(definition, class_key)

    def _factory_return_hint_from_call(self, call_node: Node) -> str | None:
        """Resolve a receiver bound to an in-file factory call (R3)."""
        function_node = call_node.child_by_field_name("function")
        if function_node is None:
            return None
        if function_node.type == "identifier":
            definition = self.factories.get(node_text(function_node))
            if definition is not None:
                return self._factory_return_hint(definition, definition.class_key)
            return None
        if function_node.type == "member_expression":
            object_node = function_node.child_by_field_name("object")
            property_node = function_node.child_by_field_name("property")
            if (
                object_node is not None
                and object_node.type == "this"
                and property_node is not None
            ):
                class_node = _enclosing_class(call_node)
                if class_node is None:
                    return None
                method_definition = self.class_methods.get(
                    _class_key(class_node), {}
                ).get(node_text(property_node))
                if method_definition is not None:
                    return self._factory_return_hint(
                        method_definition, _class_key(class_node)
                    )
        return None

    def _factory_return_hint(
        self, definition: _FactoryDefinition, class_key: tuple[int, int] | None
    ) -> str | None:
        """Return the client hint a factory's returned expression binds to.

        Per contract rev 3 section 3.4 R3, only a returned client construction
        or a returned ``this.<field>`` receiver that resolves under R1/R2
        binds; factory-wrapping-factory chains do not resolve.
        """
        if definition.return_node is None:
            return None
        return_node = _unwrap_expression(definition.return_node)
        if return_node is None:
            return None
        construction_hint = self.resolve_construction_client_hint(return_node)
        if construction_hint is not None:
            return construction_hint
        if return_node.type == "member_expression":
            object_node = return_node.child_by_field_name("object")
            if object_node is not None and object_node.type == "this":
                property_node = return_node.child_by_field_name("property")
                if property_node is None or class_key is None:
                    return None
                field_binding = self.class_fields.get(class_key, {}).get(
                    node_text(property_node)
                )
                if field_binding is None:
                    return None
                if field_binding.kind in {
                    _CLASS_FIELD_KIND_CONSTRUCTION,
                    _CLASS_FIELD_KIND_INJECTION,
                }:
                    return field_binding.construction_hint
                if field_binding.alias_target is not None:
                    return self.resolve_local_name(field_binding.alias_target)
            return None
        if return_node.type == "identifier":
            return self.resolve_local_name(node_text(return_node))
        return None

    def _record_factory(self, node: Node, class_key: tuple[int, int] | None) -> None:
        """Record an in-file function whose return expression may bind (R3)."""
        name = self._factory_own_name(node)
        if name is None:
            return
        body_node = node.child_by_field_name("body")
        if body_node is None:
            return
        if body_node.type == "statement_block":
            return_node = None
            for child in body_node.children:
                if child.type == "return_statement":
                    named_children = child.named_children
                    return_node = named_children[0] if named_children else None
                    break
        else:
            return_node = body_node
        definition = _FactoryDefinition(return_node=return_node, class_key=class_key)
        if node.type == "method_definition":
            if class_key is not None:
                self.class_methods.setdefault(class_key, {})[name] = definition
            return
        self.factories[name] = definition

    def _factory_own_name(self, node: Node) -> str | None:
        if node.type == "method_definition":
            name_node = node.child_by_field_name("name")
            return node_text(name_node) if name_node is not None else None
        if node.type in {"function_declaration", "generator_function_declaration"}:
            name_node = node.child_by_field_name("name")
            return node_text(name_node) if name_node is not None else None
        current_node = node.parent
        while (
            current_node is not None
            and current_node.type in _TRANSPARENT_VALUE_NODE_TYPES
        ):
            current_node = current_node.parent
        if current_node is not None and current_node.type == "variable_declarator":
            bound_name_node = current_node.child_by_field_name("name")
            if bound_name_node is not None and bound_name_node.type == "identifier":
                return node_text(bound_name_node)
        return None
