"""ttl_sources and serializers emission for one callsite."""

from redis_intel.frontend import RawRedisCallsite
from redis_intel.ir.builder_shared import (
    _EPISTEMIC_DETERMINISTIC_FACT,
    _EPISTEMIC_STATIC_INFERENCE,
    _EPISTEMIC_UNKNOWN,
    _PROVENANCE,
    _classify_serializer,
    _resolve_ttl_seconds,
    _ttl_argument_index,
)
from redis_intel.ir.builder_state import _IngestionState
from redis_intel.ir.models import Serializer, TtlSource


class _TtlSerializerMixin(_IngestionState):
    """Emit the ttl_sources and serializers rows for one callsite."""

    def _emit_ttl_source(
        self, callsite: RawRedisCallsite, file_path: str
    ) -> int | None:
        ttl_argument_index = _ttl_argument_index(callsite)
        if ttl_argument_index is None or ttl_argument_index >= len(
            callsite.argument_texts
        ):
            return None
        expression = callsite.argument_texts[ttl_argument_index]
        resolved_seconds = _resolve_ttl_seconds(expression)
        epistemic = (
            _EPISTEMIC_DETERMINISTIC_FACT
            if resolved_seconds is not None
            else _EPISTEMIC_UNKNOWN
        )
        self._ttl_source_file_paths.append(file_path)
        self._ttl_sources.append(
            TtlSource(
                expression=expression,
                resolved_seconds=resolved_seconds,
                epistemic=epistemic,
                evidence_json={
                    "provenance": _PROVENANCE,
                    "method": callsite.method,
                },
            )
        )
        return len(self._ttl_sources)

    def _emit_serializer(self, operation_id: int, callsite: RawRedisCallsite) -> None:
        serializer_method = _classify_serializer(callsite.method)
        self._serializers.append(
            Serializer(
                op_id=operation_id,
                method=serializer_method,
                epistemic=_EPISTEMIC_STATIC_INFERENCE,
                evidence_json={
                    "provenance": _PROVENANCE,
                    "method": callsite.method,
                },
            )
        )
