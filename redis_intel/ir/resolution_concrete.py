"""Concrete client construction row builders."""

from typing import Any

from redis_intel.ir.resolution_shared import (
    _EPISTEMIC_DETERMINISTIC_FACT,
    _EPISTEMIC_STATIC_INFERENCE,
    _PROVENANCE_ATTRIBUTE,
    _RESOLUTION_ATTRIBUTE,
    _RESOLUTION_DIRECT_CONSTRUCTION,
    _RESOLVER_PROVENANCE,
    _WRAPPER_DEPTH_ATTRIBUTE,
    MAX_WRAPPER_DEPTH,
    NODE_REDIS_LIBRARY_NAME,
    ResolvedClient,
    _Binding,
)
from redis_intel.ir.resolution_state import _ResolverState


class ConcreteClientMixin(_ResolverState):
    """Concrete client construction row builders."""

    def _concrete_client_from_new(
        self,
        binding: _Binding,
        new_node: Any,
        constructor_name: str,
        library: str,
        depth: int,
        resolution: str | None,
    ) -> ResolvedClient:
        arguments_node = new_node.child_by_field_name("arguments")
        conn_config, has_dynamic = self._extract_conn_config(arguments_node)
        if has_dynamic:
            return self._dynamic_unknown_client(
                binding.name,
                binding.span,
                f"new {constructor_name}",
                depth,
                conn_config,
            )
        if depth > MAX_WRAPPER_DEPTH:
            return self._wrapper_depth_exceeded_client(
                binding.name, binding.span, depth
            )
        evidence_json = {
            _WRAPPER_DEPTH_ATTRIBUTE: depth,
            _RESOLUTION_ATTRIBUTE: resolution or _RESOLUTION_DIRECT_CONSTRUCTION,
            _PROVENANCE_ATTRIBUTE: _RESOLVER_PROVENANCE,
        }
        return ResolvedClient(
            receiver_name=binding.name,
            client_library=library,
            construction=f"new {constructor_name}",
            conn_config=conn_config,
            wrapper_depth=depth,
            epistemic=(
                _EPISTEMIC_DETERMINISTIC_FACT
                if depth == 0
                else _EPISTEMIC_STATIC_INFERENCE
            ),
            evidence_json=evidence_json,
            span=binding.span,
            resolution=resolution or _RESOLUTION_DIRECT_CONSTRUCTION,
        )

    def _concrete_client_from_factory(
        self,
        binding: _Binding,
        call_node: Any,
        factory_name: str,
        depth: int,
        resolution: str | None,
    ) -> ResolvedClient:
        arguments_node = call_node.child_by_field_name("arguments")
        conn_config, has_dynamic = self._extract_conn_config(arguments_node)
        if has_dynamic:
            return self._dynamic_unknown_client(
                binding.name, binding.span, factory_name, depth, conn_config
            )
        if depth > MAX_WRAPPER_DEPTH:
            return self._wrapper_depth_exceeded_client(
                binding.name, binding.span, depth
            )
        evidence_json = {
            _WRAPPER_DEPTH_ATTRIBUTE: depth,
            _RESOLUTION_ATTRIBUTE: resolution or _RESOLUTION_DIRECT_CONSTRUCTION,
            _PROVENANCE_ATTRIBUTE: _RESOLVER_PROVENANCE,
        }
        return ResolvedClient(
            receiver_name=binding.name,
            client_library=NODE_REDIS_LIBRARY_NAME,
            construction=factory_name,
            conn_config=conn_config,
            wrapper_depth=depth,
            epistemic=(
                _EPISTEMIC_DETERMINISTIC_FACT
                if depth == 0
                else _EPISTEMIC_STATIC_INFERENCE
            ),
            evidence_json=evidence_json,
            span=binding.span,
            resolution=resolution or _RESOLUTION_DIRECT_CONSTRUCTION,
        )
