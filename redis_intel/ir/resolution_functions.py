"""Function/method definitions and type-annotation helpers."""

from typing import Any

from redis_intel.ir.resolution_shared import (
    _Binding,
    _binding_kind_for_expression,
    _FunctionDefinition,
)
from redis_intel.ir.resolution_state import _ResolverState
from redis_intel.ir.tree_utils import (
    node_text,
    span_from_node,
    unwrap_transparent_expression,
)


class FunctionRecordingMixin(_ResolverState):
    """Function/method definitions and type-annotation helpers."""

    def _record_method_definition(self, node: Any) -> None:
        """Record class methods as candidate R3 factories (``this.make()``)."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        method_name = node_text(name_node)
        parameters_node = node.child_by_field_name("parameters")
        body_node = node.child_by_field_name("body")
        if body_node is None:
            return
        if body_node.type == "statement_block":
            return_node = self._find_return_statement(body_node)
        else:
            return_node = body_node
        self._methods[method_name] = _FunctionDefinition(
            parameters=self._parameter_names(parameters_node),
            return_node=return_node,
        )

    def _annotation_base_name(self, type_node: Any) -> str | None:
        """Base type name of a type annotation, ignoring generic arguments.

        ``RedisClientType<...>`` and plain ``RedisClientType`` both resolve to
        the base name; union types resolve to ``None`` — a union never names a
        Redis client type from the contract §3.4 R2 fixed set.
        """
        if type_node is None or type_node.type != "type_annotation":
            return None
        named_children = type_node.named_children
        if not named_children:
            return None
        type_expression = named_children[0]
        if type_expression.type == "generic_type":
            name_node = type_expression.child_by_field_name("name")
            return node_text(name_node) if name_node is not None else None
        if type_expression.type == "type_identifier":
            return node_text(type_expression)
        return None

    def _record_variable_declarator(self, node: Any) -> None:
        bound_name_node = node.child_by_field_name("name")
        value_node = unwrap_transparent_expression(node.child_by_field_name("value"))
        if bound_name_node is None or value_node is None:
            return
        bound_name = node_text(bound_name_node)
        if value_node.type in {"function_expression", "arrow_function"}:
            self._record_function_value(bound_name, value_node)
            return
        if self._record_require_declarator(node, value_node):
            return
        self._bindings[bound_name] = _Binding(
            name=bound_name,
            kind=_binding_kind_for_expression(value_node),
            node=value_node,
            span=span_from_node(node),
        )

    def _record_function_declaration(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            parent_node = node.parent
            if parent_node is not None and parent_node.type == "variable_declarator":
                name_node = parent_node.child_by_field_name("name")
        if name_node is None:
            return
        self._record_function_value(node_text(name_node), node)

    def _record_function_value(self, function_name: str, function_node: Any) -> None:
        parameters_node = function_node.child_by_field_name("parameters")
        body_node = function_node.child_by_field_name("body")
        if body_node is None:
            return
        if body_node.type == "statement_block":
            return_node = self._find_return_statement(body_node)
        else:
            return_node = body_node
        self._functions[function_name] = _FunctionDefinition(
            parameters=self._parameter_names(parameters_node),
            return_node=return_node,
        )

    def _find_return_statement(self, body_node: Any) -> Any | None:
        for child in body_node.children:
            if child.type == "return_statement":
                named_children = child.named_children
                if named_children:
                    return named_children[0]
        return None

    def _parameter_names(self, parameters_node: Any) -> tuple[str, ...]:
        if parameters_node is None:
            return ()
        names: list[str] = []
        for child in parameters_node.named_children:
            if child.type == "identifier":
                names.append(node_text(child))
                continue
            pattern_node = child.child_by_field_name("pattern")
            if pattern_node is not None and pattern_node.type == "identifier":
                names.append(node_text(pattern_node))
                continue
            for sub_node in child.children:
                if sub_node.type == "identifier":
                    names.append(node_text(sub_node))
                    break
        return tuple(names)
