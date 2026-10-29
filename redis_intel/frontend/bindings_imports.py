"""Import and variable binding recording for ``_ClientBindings`` (R4).

Static imports, default imports, ``require(...)`` acquisition, wrapper aliases
and direct client locals are all unary facts about one declarator or one
import, so they are recorded by one mixin of the binding pass.
"""

from tree_sitter import Node

from redis_intel.frontend.bindings_state import _BindingsState
from redis_intel.frontend.node_structure import (
    _unquote_module_name,
    _unwrap_expression,
    node_text,
)


class _ImportRecordingMixin(_BindingsState):
    """Record import aliases, wrapper aliases and direct client locals."""

    def _record_import_specifier(self, node: Node) -> None:
        imported_name_node = node.child_by_field_name("name")
        alias_node = node.child_by_field_name("alias")
        if imported_name_node is None or alias_node is None:
            return
        package = self._package_of_enclosing_import(node)
        if package is not None:
            self.import_aliases[node_text(alias_node)] = (
                package,
                node_text(imported_name_node),
            )

    def _record_default_import(self, node: Node) -> None:
        for child in node.named_children:
            if child.type != "identifier":
                continue
            package = self._package_of_enclosing_import(node)
            if package is not None:
                self.import_aliases[node_text(child)] = (package, "default")

    def _record_variable_declarator(self, node: Node) -> None:
        bound_name_node = node.child_by_field_name("name")
        value_node = _unwrap_expression(node.child_by_field_name("value"))
        if bound_name_node is None or value_node is None:
            return
        bound_name = node_text(bound_name_node)
        require_package = self._require_package(value_node)
        if require_package is not None:
            # R4: a `require('ioredis')`/`require('redis')` result is an import
            # binding equivalent to a static import.
            self._record_require_names(bound_name_node, require_package)
            return
        if value_node.type == "identifier":
            self.alias_bindings[bound_name] = node_text(value_node)
            return
        if value_node.type == "new_expression":
            constructor_node = value_node.child_by_field_name("constructor")
            if constructor_node is not None and self._constructor_package(
                constructor_node
            ):
                self.direct_client_names.add(bound_name)
            return
        if value_node.type == "call_expression":
            function_node = value_node.child_by_field_name("function")
            if function_node is not None and self._factory_package(function_node):
                self.direct_client_names.add(bound_name)
                return
            # Potential R3 binding: the local is bound to a call whose callee
            # may be an in-file factory; resolution is deferred to after the
            # full collection pass (function declarations may come later).
            if function_node is not None:
                self.call_bindings[bound_name] = value_node

    def _record_require_names(self, name_node: Node, package: str) -> None:
        """Record a require binding's local names as import aliases (R4)."""
        if name_node.type == "identifier":
            self.import_aliases[node_text(name_node)] = (package, "default")
            return
        if name_node.type != "object_pattern":
            return
        for child in name_node.named_children:
            if child.type == "shorthand_property_identifier_pattern":
                self.import_aliases[node_text(child)] = (package, node_text(child))
            elif child.type == "pair":
                imported_node = child.child_by_field_name("key")
                alias_node = child.child_by_field_name("value")
                if imported_node is not None and alias_node is not None:
                    self.import_aliases[node_text(alias_node)] = (
                        package,
                        node_text(imported_node),
                    )

    def _record_require_assignment(self, node: Node) -> None:
        """Record a guarded/conditional `Redis = require('ioredis')` alias (R4)."""
        target_node = node.child_by_field_name("left")
        value_node = _unwrap_expression(node.child_by_field_name("right"))
        if target_node is None or value_node is None:
            return
        if target_node.type != "identifier" or value_node.type != "call_expression":
            return
        require_package = self._require_package(value_node)
        if require_package is not None:
            self.import_aliases[node_text(target_node)] = (require_package, "default")

    def _package_of_enclosing_import(self, node: Node) -> str | None:
        current_node: Node | None = node
        while current_node is not None:
            if current_node.type == "import_statement":
                source_node = current_node.child_by_field_name("source")
                if source_node is None:
                    return None
                return _unquote_module_name(node_text(source_node))
            current_node = current_node.parent
        return None
