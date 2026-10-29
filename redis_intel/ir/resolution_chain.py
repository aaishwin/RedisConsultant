"""New-call and call-binding chain resolution (R1/R3/R4)."""

from typing import Any

from redis_intel.ir.resolution_shared import (
    _HARD_MAX_CHAIN_DEPTH,
    _RESOLUTION_DIRECT_CONSTRUCTION,
    _RESOLUTION_DYNAMIC_REQUIRE,
    _RESOLUTION_FACTORY_RETURN,
    NODE_REDIS_FACTORY_NAMES,
    ResolvedClient,
    _Binding,
    _FunctionDefinition,
    _unwrap_constructor_node,
)
from redis_intel.ir.resolution_state import _ResolverState
from redis_intel.ir.tree_utils import (
    node_text,
)


class ChainResolutionMixin(_ResolverState):
    """New-call and call-binding chain resolution (R1/R3/R4)."""

    def _resolve_new_call(
        self,
        binding: _Binding,
        depth: int,
        visited: frozenset[str],
        param_scope: dict[str, Any],
        resolution: str | None,
    ) -> ResolvedClient:
        new_node = binding.node
        constructor_node = new_node.child_by_field_name("constructor")
        if constructor_node is None:
            return self._dynamic_unknown_client(
                binding.name, binding.span, "new <unresolved>", depth
            )
        library, via_require = self._constructor_library(constructor_node)
        if library is not None:
            if resolution is None:
                resolution = (
                    _RESOLUTION_DYNAMIC_REQUIRE
                    if via_require
                    else _RESOLUTION_DIRECT_CONSTRUCTION
                )
            return self._concrete_client_from_new(
                binding,
                new_node,
                node_text(_unwrap_constructor_node(constructor_node)),
                library,
                depth,
                resolution,
            )
        # Unknown constructor: wrapper-style hop through the first argument.
        arguments_node = new_node.child_by_field_name("arguments")
        first_argument = (
            arguments_node.named_children[0]
            if arguments_node is not None and arguments_node.named_children
            else None
        )
        if first_argument is None:
            return self._dynamic_unknown_client(
                binding.name, binding.span, f"new {node_text(constructor_node)}", depth
            )
        next_depth = depth + 1
        if next_depth > _HARD_MAX_CHAIN_DEPTH:
            return self._wrapper_depth_exceeded_client(
                binding.name, binding.span, next_depth
            )
        resolved = self._resolve_expression_node(
            first_argument, next_depth, visited, param_scope, resolution
        )
        if resolved is not None:
            return resolved
        return self._dynamic_unknown_client(
            binding.name, binding.span, f"new {node_text(constructor_node)}", next_depth
        )

    def _resolve_call_binding(
        self,
        binding: _Binding,
        depth: int,
        visited: frozenset[str],
        param_scope: dict[str, Any],
        resolution: str | None,
    ) -> ResolvedClient:
        call_node = binding.node
        function_node = call_node.child_by_field_name("function")
        if function_node is None:
            return self._dynamic_unknown_client(
                binding.name, binding.span, "call <unresolved>", depth + 1
            )
        if function_node.type == "identifier":
            callee_name = node_text(function_node)
            function_definition = self._functions.get(callee_name)
            if (
                function_definition is not None
                and function_definition.return_node is not None
            ):
                # R3: receiver bound to an in-file factory call.
                if resolution is None:
                    resolution = _RESOLUTION_FACTORY_RETURN
                return self._resolve_through_function(
                    binding,
                    function_definition,
                    depth,
                    visited,
                    param_scope,
                    resolution,
                )
            if callee_name in NODE_REDIS_FACTORY_NAMES:
                if resolution is None:
                    resolution = _RESOLUTION_DIRECT_CONSTRUCTION
                return self._concrete_client_from_factory(
                    binding, call_node, callee_name, depth, resolution
                )
            return self._dynamic_unknown_client(
                binding.name, binding.span, node_text(call_node), depth + 1
            )
        if function_node.type == "member_expression":
            object_node = function_node.child_by_field_name("object")
            property_node = function_node.child_by_field_name("property")
            if object_node is not None and property_node is not None:
                method_definition = self._this_method_definition(
                    object_node, property_node, call_node
                )
                if (
                    method_definition is not None
                    and method_definition.return_node is not None
                ):
                    # R3 through a class method factory: `this.makeClient()`.
                    if resolution is None:
                        resolution = _RESOLUTION_FACTORY_RETURN
                    return self._resolve_through_function(
                        binding,
                        method_definition,
                        depth,
                        visited,
                        param_scope,
                        resolution,
                    )
                if node_text(property_node) in NODE_REDIS_FACTORY_NAMES:
                    if resolution is None:
                        resolution = (
                            _RESOLUTION_DYNAMIC_REQUIRE
                            if self._require_package(object_node) is not None
                            else _RESOLUTION_DIRECT_CONSTRUCTION
                        )
                    return self._concrete_client_from_factory(
                        binding, call_node, node_text(property_node), depth, resolution
                    )
        return self._dynamic_unknown_client(
            binding.name, binding.span, node_text(call_node), depth + 1
        )

    def _this_method_definition(
        self, object_node: Any, property_node: Any, call_node: Any
    ) -> _FunctionDefinition | None:
        """Return the method definition when ``call_node`` is ``this.<method>(...)``."""
        if object_node.type != "this":
            return None
        return self._methods.get(node_text(property_node))
