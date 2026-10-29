"""Public surface of the C-1 frontend (contract ``ir-boundary`` rev 2, section 3).

B3 (the IR builder, assignment t4) should import from here:

    from redis_intel.frontend import (
        LanguageFrontend,
        ParseResult,
        RawRedisCallsite,
        RawScope,
        Span,
        UnresolvedNode,
        iter_redis_callsites,
        iter_scopes,
        iter_unresolved_redis_method_calls,
    )
"""

from redis_intel.frontend.frontend import (
    MAX_PARSED_FILE_SIZE_BYTES,
    LanguageFrontend,
)
from redis_intel.frontend.iterators import (
    MAX_AST_NODE_BUDGET,
    iter_redis_callsites,
    iter_scopes,
    iter_unresolved_redis_method_calls,
)
from redis_intel.frontend.models import (
    GRAMMAR_IDS,
    SCOPE_KINDS,
    UNRESOLVED_REASONS,
    ParseResult,
    RawRedisCallsite,
    RawScope,
    Span,
    UnresolvedNode,
)

__all__ = [
    "GRAMMAR_IDS",
    "MAX_AST_NODE_BUDGET",
    "MAX_PARSED_FILE_SIZE_BYTES",
    "SCOPE_KINDS",
    "UNRESOLVED_REASONS",
    "LanguageFrontend",
    "ParseResult",
    "RawRedisCallsite",
    "RawScope",
    "Span",
    "UnresolvedNode",
    "iter_redis_callsites",
    "iter_scopes",
    "iter_unresolved_redis_method_calls",
]
