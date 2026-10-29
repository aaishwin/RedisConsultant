"""Constructor argument / object-literal conn_config parsing."""

from typing import Any

from redis_intel.ir.resolution_shared import (
    _string_literal_text,
)
from redis_intel.ir.resolution_state import _ResolverState
from redis_intel.ir.tree_utils import (
    node_text,
)


class ConnConfigMixin(_ResolverState):
    """Constructor argument / object-literal conn_config parsing."""

    def _extract_conn_config(self, arguments_node: Any) -> tuple[dict[str, Any], bool]:
        """Extract constructor arguments into a raw conn_config mapping.

        Returns ``(mapping, has_dynamic)``. A string-literal first argument
        becomes ``{"url": <string>}``; an object-literal first argument becomes
        a mapping of its literal keys to literal values. Non-constant
        arguments mark the construction as dynamic. No arguments means an
        empty mapping, never a fabricated one.
        """
        if arguments_node is None or not arguments_node.named_children:
            return {}, False
        first_argument = arguments_node.named_children[0]
        if first_argument.type == "string":
            return {"url": _string_literal_text(first_argument)}, False
        if first_argument.type == "object":
            return self._parse_object_literal(first_argument)
        return {}, True

    def _parse_object_literal(self, object_node: Any) -> tuple[dict[str, Any], bool]:
        parsed: dict[str, Any] = {}
        has_dynamic = False
        for child in object_node.named_children:
            if child.type == "pair":
                key_node = child.child_by_field_name("key")
                value_node = child.child_by_field_name("value")
                if key_node is None or value_node is None:
                    has_dynamic = True
                    continue
                key = self._parse_key(key_node)
                value, value_dynamic = self._parse_object_value(value_node)
                parsed[key] = value
                has_dynamic = has_dynamic or value_dynamic
            else:
                # spread / shorthand / methods: non-literal content.
                has_dynamic = True
        return parsed, has_dynamic

    def _parse_key(self, key_node: Any) -> str:
        if key_node.type == "string":
            return _string_literal_text(key_node)
        return node_text(key_node)

    def _parse_object_value(self, value_node: Any) -> tuple[Any, bool]:
        node_type = value_node.type
        if node_type == "string":
            return _string_literal_text(value_node), False
        if node_type == "number":
            number_text = node_text(value_node)
            try:
                return int(number_text), False
            except ValueError:
                try:
                    return int(number_text, 0), False
                except ValueError as exc:
                    raise ValueError(
                        "malformed numeric literal in conn_config at a trust boundary: "
                        f"{number_text!r}"
                    ) from exc
        if node_type == "true":
            return True, False
        if node_type == "false":
            return False, False
        if node_type == "null":
            return None, False
        if node_type == "object":
            return self._parse_object_literal(value_node)
        # Non-constant value (identifier, member expression, template, call):
        # preserve the source text as a marker and mark the construction dynamic.
        return node_text(value_node), True
