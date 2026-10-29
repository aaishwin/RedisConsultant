"""Binding-table collection and import/require/parameter recording."""

from typing import Any

from redis_intel.ir.resolution_shared import (
    _BINDING_KIND_INJECTION,
    IOREDIS_PACKAGE_NAME,
    REDIS_CLIENT_TYPE_ANNOTATIONS,
    _Binding,
)
from redis_intel.ir.resolution_state import _ResolverState
from redis_intel.ir.tree_utils import (
    MAX_AST_NODE_BUDGET,
    iter_preorder_nodes_bounded,
    node_text,
    span_from_node,
    unwrap_transparent_expression,
)


class CollectionMixin(_ResolverState):
    """Binding-table collection and import/require/parameter recording."""

    def _collect_bindings(self) -> None:
        for node in iter_preorder_nodes_bounded(
            self._tree.root_node, MAX_AST_NODE_BUDGET
        ):
            if node.type == "variable_declarator":
                self._record_variable_declarator(node)
            elif node.type in {"function_declaration", "function_expression"}:
                self._record_function_declaration(node)
            elif node.type == "import_statement":
                self._record_import_statement(node)
            elif node.type == "assignment_expression":
                self._record_require_assignment(node)
                self._record_this_assignment(node)
            elif node.type in {"required_parameter", "optional_parameter"}:
                self._record_parameter_property(node)
            elif node.type == "method_definition":
                self._record_method_definition(node)
            elif node.type == "class_declaration":
                self._record_class_field_initializers(node)

    def _record_import_statement(self, node: Any) -> None:
        """Record aliased ioredis imports so renamed defaults resolve."""
        source_node = node.child_by_field_name("source")
        if source_node is None:
            return
        package = node_text(source_node).strip("\"'")
        if package != IOREDIS_PACKAGE_NAME:
            return
        for child in node.children:
            if child.type == "import_clause":
                for clause_child in child.children:
                    if clause_child.type == "identifier":
                        self._import_aliases[node_text(clause_child)] = (
                            IOREDIS_PACKAGE_NAME,
                            "default",
                        )
                    elif clause_child.type == "import_specifier":
                        imported_node = clause_child.child_by_field_name("name")
                        alias_node = clause_child.child_by_field_name("alias")
                        if imported_node is None:
                            continue
                        local_name = (
                            node_text(alias_node)
                            if alias_node is not None
                            else node_text(imported_node)
                        )
                        self._import_aliases[local_name] = (
                            IOREDIS_PACKAGE_NAME,
                            node_text(imported_node),
                        )

    def _record_require_declarator(self, node: Any, value_node: Any) -> bool:
        """Record an R4 require binding; return True when the value is one."""
        require_package = self._require_package(value_node)
        if require_package is None:
            return False
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return False
        if name_node.type == "identifier":
            self._require_aliases[node_text(name_node)] = require_package
            return True
        if name_node.type == "object_pattern":
            for child in name_node.named_children:
                if child.type == "shorthand_property_identifier_pattern":
                    self._require_aliases[node_text(child)] = require_package
        return True

    def _record_require_assignment(self, node: Any) -> None:
        """Record a guarded ``Redis = require('ioredis')`` alias (R4)."""
        target_node = node.child_by_field_name("left")
        value_node = unwrap_transparent_expression(node.child_by_field_name("right"))
        if target_node is None or value_node is None:
            return
        if target_node.type != "identifier" or value_node.type != "call_expression":
            return
        require_package = self._require_package(value_node)
        if require_package is not None:
            self._require_aliases[node_text(target_node)] = require_package

    def _record_parameter_property(self, node: Any) -> None:
        """Record an R2 TS parameter property.

        Example: ``constructor(private client: Redis)``.
        """
        modifiers = any(
            child.type == "accessibility_modifier" for child in node.children
        )
        if not modifiers:
            return
        parameters_node = node.parent
        constructor_node = (
            parameters_node.parent if parameters_node is not None else None
        )
        if constructor_node is None or constructor_node.type != "method_definition":
            return
        constructor_name_node = constructor_node.child_by_field_name("name")
        if (
            constructor_name_node is None
            or node_text(constructor_name_node) != "constructor"
        ):
            return
        pattern_node = node.child_by_field_name("pattern")
        annotation = self._annotation_base_name(node.child_by_field_name("type"))
        if pattern_node is None or pattern_node.type != "identifier":
            return
        if annotation is None or annotation not in REDIS_CLIENT_TYPE_ANNOTATIONS:
            return
        self._bindings[f"this.{node_text(pattern_node)}"] = _Binding(
            name=f"this.{node_text(pattern_node)}",
            kind=_BINDING_KIND_INJECTION,
            node=None,
            span=span_from_node(node),
            annotation=annotation,
        )
