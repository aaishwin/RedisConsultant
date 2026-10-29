"""Constructor/library detection (R1/R4 constructor resolution)."""

from typing import Any

from redis_intel.ir.resolution_shared import (
    IOREDIS_CONSTRUCTOR_NAMES,
    IOREDIS_PACKAGE_NAME,
    REQUIRE_ACQUIRED_PACKAGES,
    _unwrap_constructor_node,
)
from redis_intel.ir.resolution_state import _ResolverState
from redis_intel.ir.tree_utils import (
    node_text,
)


class LibraryDetectionMixin(_ResolverState):
    """Constructor/library detection (R1/R4 constructor resolution)."""

    def _constructor_library(self, constructor_node: Any) -> tuple[str | None, bool]:
        """Resolve a ``new <expr>(...)`` constructor to ``(library, via_require)``.

        Handles static imports (including aliased defaults), the known
        constructor names ``Redis``/``IORedis``, and the R4 require forms
        ``new (require('ioredis'))(...)`` and ``new require('ioredis').Redis``.
        ``via_require`` is true only when the constructor expression itself
        acquires the class through ``require(...)``.
        """
        unwrapped = _unwrap_constructor_node(constructor_node)
        if unwrapped is None:
            return None, False
        if unwrapped.type == "call_expression":
            package = self._require_package(unwrapped)
            if package == IOREDIS_PACKAGE_NAME:
                return IOREDIS_PACKAGE_NAME, True
            return None, False
        if unwrapped.type == "member_expression":
            object_node = unwrapped.child_by_field_name("object")
            property_node = unwrapped.child_by_field_name("property")
            if object_node is None or property_node is None:
                return None, False
            unwrapped_object = _unwrap_constructor_node(object_node)
            if (
                unwrapped_object is not None
                and self._require_package(unwrapped_object) == IOREDIS_PACKAGE_NAME
                and node_text(property_node) in IOREDIS_CONSTRUCTOR_NAMES
            ):
                return IOREDIS_PACKAGE_NAME, True
            return None, False
        if unwrapped.type != "identifier":
            return None, False
        constructor_name = node_text(unwrapped)
        if constructor_name in IOREDIS_CONSTRUCTOR_NAMES:
            return IOREDIS_PACKAGE_NAME, False
        imported = self._import_aliases.get(constructor_name)
        if imported is not None:
            package, imported_name = imported
            if package == IOREDIS_PACKAGE_NAME and (
                imported_name in IOREDIS_CONSTRUCTOR_NAMES or imported_name == "default"
            ):
                return IOREDIS_PACKAGE_NAME, False
        if self._require_aliases.get(constructor_name) == IOREDIS_PACKAGE_NAME:
            return IOREDIS_PACKAGE_NAME, True
        return None, False

    def _require_package(self, value_node: Any) -> str | None:
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
        module_name = node_text(first_argument).strip("\"'")
        if module_name not in REQUIRE_ACQUIRED_PACKAGES:
            return None
        return module_name
