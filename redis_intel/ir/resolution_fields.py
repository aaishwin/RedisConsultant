"""Class-field and this-assignment recording (R1/R2/R3)."""

from typing import Any

from redis_intel.ir.resolution_shared import (
    _BINDING_KIND_CALL,
    _BINDING_KIND_IDENTIFIER,
    _BINDING_KIND_INJECTION,
    _BINDING_KIND_NEW_CALL,
    NODE_REDIS_FACTORY_NAMES,
    REDIS_CLIENT_TYPE_ANNOTATIONS,
    _Binding,
)
from redis_intel.ir.resolution_state import _ResolverState
from redis_intel.ir.tree_utils import (
    node_text,
    span_from_node,
    unwrap_transparent_expression,
)


class FieldRecordingMixin(_ResolverState):
    """Class-field and this-assignment recording (R1/R2/R3)."""

    def _record_class_field_initializers(self, class_node: Any) -> None:
        """Record R1 class property initializers that are client constructions."""
        body_node = class_node.child_by_field_name("body")
        if body_node is None:
            return
        for child in body_node.named_children:
            if child.type != "public_field_definition":
                continue
            name_node = child.child_by_field_name("name")
            value_node = unwrap_transparent_expression(
                child.child_by_field_name("value")
            )
            if name_node is None or value_node is None:
                continue
            field_name = f"this.{node_text(name_node)}"
            if value_node.type == "new_expression":
                constructor_node = value_node.child_by_field_name("constructor")
                library, _via_require = (
                    self._constructor_library(constructor_node)
                    if constructor_node is not None
                    else (None, False)
                )
                if library is not None:
                    self._bindings[field_name] = _Binding(
                        name=field_name,
                        kind=_BINDING_KIND_NEW_CALL,
                        node=value_node,
                        span=span_from_node(child),
                    )
            elif value_node.type == "call_expression":
                function_node = value_node.child_by_field_name("function")
                if (
                    function_node is not None
                    and node_text(function_node) in NODE_REDIS_FACTORY_NAMES
                ):
                    self._bindings[field_name] = _Binding(
                        name=field_name,
                        kind=_BINDING_KIND_CALL,
                        node=value_node,
                        span=span_from_node(child),
                    )

    def _record_this_assignment(self, node: Any) -> None:
        """Record ``this.<field> = ...`` constructor assignments (R1/R2/R3)."""
        left_node = node.child_by_field_name("left")
        right_node = unwrap_transparent_expression(node.child_by_field_name("right"))
        if left_node is None or right_node is None:
            return
        if (
            left_node.type != "member_expression"
            or right_node.type == "member_expression"
        ):
            return
        object_node = left_node.child_by_field_name("object")
        property_node = left_node.child_by_field_name("property")
        if object_node is None or object_node.type != "this" or property_node is None:
            return
        constructor_node = self._enclosing_constructor(node)
        if constructor_node is None:
            return
        field_name = f"this.{node_text(property_node)}"
        if right_node.type == "identifier":
            annotation = self._constructor_parameter_annotation(
                constructor_node, node_text(right_node)
            )
            if annotation is not None:
                # R2: the parameter's type annotation names a Redis client type.
                self._bindings[field_name] = _Binding(
                    name=field_name,
                    kind=_BINDING_KIND_INJECTION,
                    node=None,
                    span=span_from_node(node),
                    annotation=annotation,
                )
            else:
                self._bindings.setdefault(
                    field_name,
                    _Binding(
                        name=field_name,
                        kind=_BINDING_KIND_IDENTIFIER,
                        node=right_node,
                        span=span_from_node(node),
                    ),
                )
            return
        if right_node.type == "new_expression":
            constructor_node_of_value = right_node.child_by_field_name("constructor")
            library, _via_require = (
                self._constructor_library(constructor_node_of_value)
                if constructor_node_of_value is not None
                else (None, False)
            )
            if library is not None:
                # A construction assigned to the field overrides any earlier
                # alias binding (same precedence as the frontend gate).
                self._bindings[field_name] = _Binding(
                    name=field_name,
                    kind=_BINDING_KIND_NEW_CALL,
                    node=right_node,
                    span=span_from_node(node),
                )
            return
        if right_node.type == "call_expression":
            function_node = right_node.child_by_field_name("function")
            if (
                function_node is not None
                and node_text(function_node) in NODE_REDIS_FACTORY_NAMES
            ):
                self._bindings[field_name] = _Binding(
                    name=field_name,
                    kind=_BINDING_KIND_CALL,
                    node=right_node,
                    span=span_from_node(node),
                )
            elif function_node is not None and function_node.type == "identifier":
                # Potential R3: field bound to an in-file factory call.
                self._bindings[field_name] = _Binding(
                    name=field_name,
                    kind=_BINDING_KIND_CALL,
                    node=right_node,
                    span=span_from_node(node),
                )

    def _enclosing_constructor(self, node: Any) -> Any | None:
        """Return the constructor method_definition enclosing ``node``, if any."""
        current_node: Any | None = node.parent
        while current_node is not None:
            if current_node.type == "method_definition":
                name_node = current_node.child_by_field_name("name")
                if name_node is not None and node_text(name_node) == "constructor":
                    return current_node
                return None
            if current_node.type == "class_declaration":
                return None
            current_node = current_node.parent
        return None

    def _constructor_parameter_annotation(
        self, constructor_node: Any, parameter_name: str
    ) -> str | None:
        """Return the Redis client type annotation of a named constructor parameter."""
        parameters_node = constructor_node.child_by_field_name("parameters")
        if parameters_node is None:
            return None
        for parameter in parameters_node.named_children:
            if parameter.type not in {"required_parameter", "optional_parameter"}:
                continue
            pattern_node = parameter.child_by_field_name("pattern")
            if pattern_node is None or node_text(pattern_node) != parameter_name:
                continue
            annotation = self._annotation_base_name(
                parameter.child_by_field_name("type")
            )
            if annotation is not None and annotation in REDIS_CLIENT_TYPE_ANNOTATIONS:
                return annotation
            return None
        return None
