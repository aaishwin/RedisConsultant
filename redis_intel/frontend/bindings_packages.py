"""Package resolution for constructors, factories and ``require`` (R4).

Every rule that has to decide whether an expression names the ioredis or the
node-redis package lives here, so the resolution and recording mixins can ask
one question each instead of repeating the package vocabulary.
"""

from tree_sitter import Node

from redis_intel.frontend.bindings_state import _BindingsState
from redis_intel.frontend.method_names import (
    IOREDIS_CONSTRUCTOR_NAMES,
    IOREDIS_PACKAGE_NAME,
    NODE_REDIS_FACTORY_NAMES,
    NODE_REDIS_PACKAGE_NAME,
    REQUIRE_ACQUIRED_PACKAGES,
)
from redis_intel.frontend.node_structure import (
    _unquote_module_name,
    _unwrap_expression,
    node_text,
)


class _PackageResolutionMixin(_BindingsState):
    """Resolve constructor, factory and ``require`` expressions to a package."""

    def _constructor_package(self, constructor_node: Node) -> str | None:
        """Resolve a ``new <name>(...)`` constructor name to a client package.

        Handles static imports, ``require``-acquired classes (R4, including
        ``new (require('ioredis'))(...)`` and ``new require('ioredis').Redis``
        member forms) and the known ioredis constructor names.
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
            if object_node is None or property_node is None:
                return None
            require_package = self._require_package(_unwrap_expression(object_node))
            if require_package == IOREDIS_PACKAGE_NAME and (
                node_text(property_node) in IOREDIS_CONSTRUCTOR_NAMES
            ):
                return IOREDIS_PACKAGE_NAME
            return None
        constructor_name = node_text(unwrapped_node)
        if constructor_name in IOREDIS_CONSTRUCTOR_NAMES:
            return IOREDIS_PACKAGE_NAME
        imported = self.import_aliases.get(constructor_name)
        if imported is None:
            return None
        package, imported_name = imported
        if package == IOREDIS_PACKAGE_NAME and (
            imported_name in IOREDIS_CONSTRUCTOR_NAMES or imported_name == "default"
        ):
            return IOREDIS_PACKAGE_NAME
        return None

    def _require_package(self, value_node: Node | None) -> str | None:
        """Return the acquired package when ``value_node`` is ``require('<pkg>')``."""
        if value_node is None or value_node.type != "call_expression":
            return None
        function_node = value_node.child_by_field_name("function")
        if function_node is None or node_text(function_node) != "require":
            return None
        arguments_node = value_node.child_by_field_name("arguments")
        if arguments_node is None or not arguments_node.named_children:
            return None
        first_argument = arguments_node.named_children[0]
        if first_argument.type != "string":
            return None
        module_name = _unquote_module_name(node_text(first_argument))
        if module_name not in REQUIRE_ACQUIRED_PACKAGES:
            return None
        return module_name

    def _factory_package(self, function_node: Node) -> str | None:
        """Resolve a call's function node to a node-redis package, if it is one."""
        if function_node.type == "member_expression":
            property_node = function_node.child_by_field_name("property")
            if (
                property_node is not None
                and node_text(property_node) in NODE_REDIS_FACTORY_NAMES
            ):
                return NODE_REDIS_PACKAGE_NAME
            return None
        if function_node.type != "identifier":
            return None
        function_name = node_text(function_node)
        if function_name in NODE_REDIS_FACTORY_NAMES:
            return NODE_REDIS_PACKAGE_NAME
        imported = self.import_aliases.get(function_name)
        if imported is None:
            return None
        package, imported_name = imported
        if (
            package == NODE_REDIS_PACKAGE_NAME
            and imported_name in NODE_REDIS_FACTORY_NAMES
        ):
            return NODE_REDIS_PACKAGE_NAME
        return None
