"""C-2 IR package: ParseResults → versioned 14-entity IrDelta.

Contract ``ir-boundary`` rev 2. Public surface: :class:`IrBuilder`,
:class:`IrDelta`, ``IR_SCHEMA_VERSION``, :func:`serialize`,
:func:`deserialize`.
"""

from redis_intel.ir.builder import IrBuilder
from redis_intel.ir.models import IR_SCHEMA_VERSION, IrDelta
from redis_intel.ir.serialization import deserialize, serialize

__all__ = [
    "IR_SCHEMA_VERSION",
    "IrBuilder",
    "IrDelta",
    "deserialize",
    "serialize",
]
