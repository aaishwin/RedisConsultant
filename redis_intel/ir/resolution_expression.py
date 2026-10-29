"""Expression-node and through-function resolution (R3)."""

from typing import Any

from redis_intel.ir.resolution_shared import (
    _BINDING_KIND_CALL,
    _BINDING_KIND_NEW_CALL,
    _HARD_MAX_CHAIN_DEPTH,
    ResolvedClient,
    _Binding,
    _FunctionDefinition,
)
from redis_intel.ir.resolution_state import _ResolverState
from redis_intel.ir.tree_utils import (
    node_text,
    span_from_node,
    unwrap_transparent_expression,
)


class ExpressionResolutionMixin(_ResolverState):
    """Expression-node and through-function resolution (R3)."""

    def _resolve_through_function(
        self,
        binding: _Binding,
        function_definition: _FunctionDefinition,
        depth: int,
        visited: frozenset[str],
        param_scope: dict[str, Any],
        resolution: str | None,
    ) -> ResolvedClient:
        call_node = binding.node
        next_depth = depth + 1
        if next_depth > _HARD_MAX_CHAIN_DEPTH:
            return self._wrapper_depth_exceeded_client(
                binding.name, binding.span, next_depth
            )
        next_param_scope = dict(param_scope)
        arguments_node = (
            call_node.child_by_field_name("arguments")
            if call_node is not None
            else None
        )
        argument_nodes = (
            list(arguments_node.named_children) if arguments_node is not None else []
        )
        for parameter_name, argument_node in zip(
            function_definition.parameters, argument_nodes, strict=False
        ):
            next_param_scope[parameter_name] = argument_node
        resolved = self._resolve_expression_node(
            function_definition.return_node,
            next_depth,
            visited,
            next_param_scope,
            resolution,
        )
        if resolved is not None:
            return resolved
        return self._dynamic_unknown_client(
            binding.name, binding.span, f"call:{node_text(call_node)}", next_depth
        )

    def _resolve_expression_node(
        self,
        node: Any,
        depth: int,
        visited: frozenset[str],
        param_scope: dict[str, Any],
        resolution: str | None,
    ) -> ResolvedClient | None:
        unwrapped = unwrap_transparent_expression(node)
        if unwrapped is None:
            return None
        if depth > _HARD_MAX_CHAIN_DEPTH:
            return self._wrapper_depth_exceeded_client(
                node_text(unwrapped), span_from_node(unwrapped), depth
            )
        node_type = unwrapped.type
        if node_type == "new_expression":
            expression_binding = _Binding(
                name=node_text(unwrapped),
                kind=_BINDING_KIND_NEW_CALL,
                node=unwrapped,
                span=span_from_node(unwrapped),
            )
            return self._resolve_new_call(
                expression_binding, depth, visited, param_scope, resolution
            )
        if node_type == "identifier":
            return self._resolve_binding(
                node_text(unwrapped), depth, visited, param_scope, resolution
            )
        if node_type == "call_expression":
            expression_binding = _Binding(
                name=node_text(unwrapped),
                kind=_BINDING_KIND_CALL,
                node=unwrapped,
                span=span_from_node(unwrapped),
            )
            return self._resolve_call_binding(
                expression_binding, depth, visited, param_scope, resolution
            )
        if node_type == "member_expression":
            object_node = unwrapped.child_by_field_name("object")
            property_node = unwrapped.child_by_field_name("property")
            if (
                object_node is not None
                and object_node.type == "this"
                and property_node is not None
            ):
                # A factory returning `this.<field>`: resolve the field binding
                # at the current depth (R1 field = DEPTH 1 total; R2 injection
                # = DEPTH 2 total, contract §5.2).
                return self._resolve_binding(
                    f"this.{node_text(property_node)}",
                    depth,
                    visited,
                    param_scope,
                    resolution,
                )
        return self._dynamic_unknown_client(
            node_text(unwrapped), span_from_node(unwrapped), node_text(unwrapped), depth
        )
