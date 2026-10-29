"""Class-field binding recording for ``_ClientBindings`` (R1/R2/R3).

Recording ``this.<field>`` bindings off class bodies and constructors is one
group of the binding pass; it lives in a mixin so ``_ClientBindings`` keeps its
single ``from_tree`` dispatch while this module stays inside the rule-8 module
length.
"""

from tree_sitter import Node

from redis_intel.frontend.bindings_state import _BindingsState
from redis_intel.frontend.bindings_types import (
    _CLASS_FIELD_KIND_ALIAS,
    _CLASS_FIELD_KIND_CONSTRUCTION,
    _CLASS_FIELD_KIND_FACTORY,
    _CLASS_FIELD_KIND_INJECTION,
    _ClassFieldBinding,
)
from redis_intel.frontend.method_names import REDIS_CLIENT_TYPE_ANNOTATIONS
from redis_intel.frontend.node_structure import (
    _annotation_base_name,
    _class_key,
    _enclosing_constructor_class,
    _unwrap_expression,
    node_text,
)


class _ClassFieldsMixin(_BindingsState):
    """Record the ``this.<field>`` bindings of each class in the tree."""

    def _record_class(self, class_node: Node) -> None:
        """Collect R1 field-initializer constructions of one class body."""
        body_node = class_node.child_by_field_name("body")
        if body_node is None:
            return
        fields = self.class_fields.setdefault(_class_key(class_node), {})
        for child in body_node.named_children:
            if child.type == "public_field_definition":
                self._record_class_field_initializer(fields, child)

    def _record_class_field_initializer(
        self, fields: dict[str, _ClassFieldBinding], field_node: Node
    ) -> None:
        name_node = field_node.child_by_field_name("name")
        value_node = _unwrap_expression(field_node.child_by_field_name("value"))
        if name_node is None or value_node is None:
            return
        construction_hint = self.resolve_construction_client_hint(value_node)
        if construction_hint is not None:
            # R1: the field initializer is itself the client construction.
            fields[node_text(name_node)] = _ClassFieldBinding(
                kind=_CLASS_FIELD_KIND_CONSTRUCTION,
                construction_hint=construction_hint,
            )
            return
        if value_node.type == "identifier":
            fields[node_text(name_node)] = _ClassFieldBinding(
                kind=_CLASS_FIELD_KIND_ALIAS, alias_target=node_text(value_node)
            )
            return
        if value_node.type == "call_expression":
            function_node = value_node.child_by_field_name("function")
            if function_node is not None and function_node.type == "identifier":
                # Potential R3: field bound to an in-file factory call.
                fields[node_text(name_node)] = _ClassFieldBinding(
                    kind=_CLASS_FIELD_KIND_FACTORY,
                    factory_name=node_text(function_node),
                )

    def _record_this_assignment(self, node: Node) -> None:
        """Record `this.<field> = ...` bindings from constructors (R1/R2/R3)."""
        left_node = node.child_by_field_name("left")
        right_node = _unwrap_expression(node.child_by_field_name("right"))
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
        class_node = _enclosing_constructor_class(node)
        if class_node is None:
            return
        fields = self.class_fields.setdefault(_class_key(class_node), {})
        field_name = node_text(property_node)
        if right_node.type == "identifier":
            parameter_annotation = self._constructor_parameter_annotation(
                node, right_node
            )
            if parameter_annotation is not None:
                # R2: the parameter's type annotation names a Redis client type
                # from the fixed set.
                fields[field_name] = _ClassFieldBinding(
                    kind=_CLASS_FIELD_KIND_INJECTION,
                    construction_hint=parameter_annotation,
                )
            else:
                fields.setdefault(
                    field_name,
                    _ClassFieldBinding(
                        kind=_CLASS_FIELD_KIND_ALIAS, alias_target=node_text(right_node)
                    ),
                )
            return
        construction_hint = self.resolve_construction_client_hint(right_node)
        if construction_hint is not None:
            # Direct construction assigned to the field: same DEPTH-0 binding
            # semantics as an R1 property initializer.
            fields[field_name] = _ClassFieldBinding(
                kind=_CLASS_FIELD_KIND_CONSTRUCTION,
                construction_hint=construction_hint,
            )
            return
        if right_node.type == "call_expression":
            function_node = right_node.child_by_field_name("function")
            if function_node is not None and function_node.type == "identifier":
                fields[field_name] = _ClassFieldBinding(
                    kind=_CLASS_FIELD_KIND_FACTORY,
                    factory_name=node_text(function_node),
                )

    def _constructor_parameter_annotation(
        self, assignment_node: Node, parameter_node: Node
    ) -> str | None:
        """Return the Redis client type annotation of a constructor parameter.

        ``parameter_node`` is the identifier assigned on the right side of a
        ``this.<field> = <param>`` constructor assignment; the parameter must
        belong to the enclosing constructor's formal parameters.
        """
        constructor_node: Node | None = None
        current_node: Node | None = assignment_node.parent
        while current_node is not None:
            if current_node.type == "method_definition":
                name_node = current_node.child_by_field_name("name")
                if name_node is not None and node_text(name_node) == "constructor":
                    constructor_node = current_node
                break
            current_node = current_node.parent
        if constructor_node is None:
            return None
        parameters_node = constructor_node.child_by_field_name("parameters")
        if parameters_node is None:
            return None
        parameter_name = node_text(parameter_node)
        for parameter in parameters_node.named_children:
            if parameter.type not in {"required_parameter", "optional_parameter"}:
                continue
            pattern_node = parameter.child_by_field_name("pattern")
            if pattern_node is None or node_text(pattern_node) != parameter_name:
                continue
            annotation = _annotation_base_name(parameter.child_by_field_name("type"))
            if annotation is not None and annotation in REDIS_CLIENT_TYPE_ANNOTATIONS:
                return annotation
            return None
        return None
