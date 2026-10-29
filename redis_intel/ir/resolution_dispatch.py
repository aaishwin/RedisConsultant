"""Top-level receiver dispatch and binding/injection resolution (R2)."""

from typing import Any

from redis_intel.ir.resolution_shared import (
    _BINDING_KIND_CALL,
    _BINDING_KIND_IDENTIFIER,
    _BINDING_KIND_INJECTION,
    _BINDING_KIND_NEW_CALL,
    _CLIENT_LIBRARY_BY_ANNOTATION,
    _EPISTEMIC_STATIC_INFERENCE,
    _HARD_MAX_CHAIN_DEPTH,
    _PROVENANCE_ATTRIBUTE,
    _RESOLUTION_ALIAS_BINDING,
    _RESOLUTION_ATTRIBUTE,
    _RESOLUTION_CLASS_FIELD_INITIALIZER,
    _RESOLUTION_CONSTRUCTOR_INJECTION,
    _RESOLUTION_FACTORY_RETURN,
    _RESOLVER_PROVENANCE,
    _WRAPPER_DEPTH_ATTRIBUTE,
    MAX_WRAPPER_DEPTH,
    ResolvedClient,
    _Binding,
)
from redis_intel.ir.resolution_state import _ResolverState
from redis_intel.ir.tree_utils import (
    node_text,
)


class DispatchResolutionMixin(_ResolverState):
    """Top-level receiver dispatch and binding/injection resolution (R2)."""

    def _resolve_zero_argument_call_receiver(
        self, receiver_name: str
    ) -> ResolvedClient | None:
        """Resolve a ``name()``/``this.method()`` receiver through its factory."""
        if not receiver_name.endswith("()"):
            return None
        stem = receiver_name[:-2]
        if stem.startswith("this."):
            method_definition = self._methods.get(stem[len("this.") :])
            if method_definition is None or method_definition.return_node is None:
                return None
            synthetic_binding = _Binding(
                name=receiver_name,
                kind=_BINDING_KIND_CALL,
                node=None,
                span=(0, 0, 0, 0),
            )
            return self._resolve_through_function(
                synthetic_binding,
                method_definition,
                depth=0,
                visited=frozenset(),
                param_scope={},
                resolution=_RESOLUTION_FACTORY_RETURN,
            )
        function_definition = self._functions.get(stem)
        if function_definition is None or function_definition.return_node is None:
            return None
        synthetic_binding = _Binding(
            name=receiver_name,
            kind=_BINDING_KIND_CALL,
            node=None,
            span=(0, 0, 0, 0),
        )
        return self._resolve_through_function(
            synthetic_binding,
            function_definition,
            depth=0,
            visited=frozenset(),
            param_scope={},
            resolution=_RESOLUTION_FACTORY_RETURN,
        )

    def _resolve_binding(
        self,
        name: str,
        depth: int,
        visited: frozenset[str],
        param_scope: dict[str, Any],
        resolution: str | None = None,
    ) -> ResolvedClient | None:
        if depth > _HARD_MAX_CHAIN_DEPTH:
            binding = self._bindings.get(name)
            span = binding.span if binding is not None else (0, 0, 0, 0)
            return self._wrapper_depth_exceeded_client(name, span, depth)
        if name in visited:
            return None
        if name in param_scope:
            return self._resolve_expression_node(
                param_scope[name], depth, visited | {name}, param_scope, resolution
            )
        binding = self._bindings.get(name)
        if binding is None:
            return None
        if resolution is None:
            # Classify the rule that resolved the receiver at its outermost
            # binding (contract rev 3 §3.4); inner hops keep the classification.
            if name.startswith("this.") and binding.kind == _BINDING_KIND_INJECTION:
                resolution = _RESOLUTION_CONSTRUCTOR_INJECTION
            elif name.startswith("this.") and binding.kind == _BINDING_KIND_NEW_CALL:
                resolution = _RESOLUTION_CLASS_FIELD_INITIALIZER
            elif binding.kind == _BINDING_KIND_IDENTIFIER:
                resolution = _RESOLUTION_ALIAS_BINDING
        if binding.kind == _BINDING_KIND_INJECTION:
            return self._resolve_injection(binding, depth, resolution)
        next_visited = visited | {name}
        if binding.kind == _BINDING_KIND_NEW_CALL:
            return self._resolve_new_call(
                binding, depth, next_visited, param_scope, resolution
            )
        if binding.kind == _BINDING_KIND_CALL:
            return self._resolve_call_binding(
                binding, depth, next_visited, param_scope, resolution
            )
        if binding.kind == _BINDING_KIND_IDENTIFIER:
            resolved_target = self._resolve_binding(
                node_text(binding.node),
                depth + 1,
                next_visited,
                param_scope,
                resolution,
            )
            if resolved_target is not None:
                return resolved_target
            return self._dynamic_unknown_client(
                name, binding.span, f"alias:{node_text(binding.node)}", depth + 1
            )
        return self._dynamic_unknown_client(
            name, binding.span, f"expr:{node_text(binding.node)}", depth + 1
        )

    def _resolve_injection(
        self, binding: _Binding, depth: int, resolution: str | None = None
    ) -> ResolvedClient:
        """Resolve an R2 constructor-parameter injection (contract §3.4 R2).

        The concrete construction is outside the file, so this is one
        inferential hop: DEPTH = arrival depth + 1, epistemic
        ``STATIC_INFERENCE``, the annotation name as ``construction`` and an
        empty ``conn_config`` — the unresolvable connection configuration is
        represented, never fabricated.
        """
        total_depth = depth + 1
        if total_depth > MAX_WRAPPER_DEPTH:
            return self._wrapper_depth_exceeded_client(
                binding.name, binding.span, total_depth
            )
        annotation = binding.annotation or ""
        library = _CLIENT_LIBRARY_BY_ANNOTATION.get(annotation, "unknown")
        resolution_name = resolution or _RESOLUTION_CONSTRUCTOR_INJECTION
        evidence_json = {
            _WRAPPER_DEPTH_ATTRIBUTE: total_depth,
            _RESOLUTION_ATTRIBUTE: resolution_name,
            _PROVENANCE_ATTRIBUTE: _RESOLVER_PROVENANCE,
        }
        return ResolvedClient(
            receiver_name=binding.name,
            client_library=library,
            construction=annotation,
            conn_config={},
            wrapper_depth=total_depth,
            epistemic=_EPISTEMIC_STATIC_INFERENCE,
            evidence_json=evidence_json,
            span=binding.span,
            resolution=resolution_name,
        )
