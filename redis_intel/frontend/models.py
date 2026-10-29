"""Frozen dataclasses of the C-1 frontend surface.

Mirrors contract ``ir-boundary`` rev 2, sections 1 and 3.2 exactly: field
names, field order, types and nullability are binding for the C-2 IR builder
(B3), so change them only together with a contract revision bump. The
dataclass field order below is the B3-relied-on declaration order.
"""

import re
from dataclasses import dataclass

from tree_sitter import Tree

GRAMMAR_IDS: tuple[str, ...] = ("typescript", "tsx", "javascript", "unsupported")

UNRESOLVED_REASONS: tuple[str, ...] = (
    "unsupported_syntax",
    "unresolvable_expression",
    "node_budget_exceeded",
    "file_too_large",
    "parse_error",
)

SCOPE_KINDS: tuple[str, ...] = (
    "module",
    "function",
    "method",
    "class",
    "lambda",
    "arrow",
    "script",
)

_CONTENT_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _require_enum_value(
    value: str, allowed_values: tuple[str, ...], field_name: str
) -> None:
    if value not in allowed_values:
        raise ValueError(f"{field_name} must be one of {allowed_values}, got {value!r}")


def _require_non_empty_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class Span:
    """1-based, both-ends-inclusive source span (contract section 1)."""

    start_line: int
    start_col: int
    end_line: int
    end_col: int

    def __post_init__(self) -> None:
        if self.start_line < 1 or self.start_col < 1:
            raise ValueError(
                f"span start must be line >= 1 and col >= 1, got "
                f"line {self.start_line}, col {self.start_col}"
            )
        if self.end_line < self.start_line:
            raise ValueError(
                f"span end_line {self.end_line} is before start_line {self.start_line}"
            )
        if self.end_line == self.start_line and self.end_col < self.start_col:
            raise ValueError(
                f"span end_col {self.end_col} is before start_col {self.start_col} "
                "on the same line"
            )


@dataclass(frozen=True)
class RawRedisCallsite:
    """One Redis client call recognized per contract section 3.4."""

    receiver_text: str
    method: str
    argument_texts: tuple[str, ...]
    span: Span
    client_hint: str | None

    def __post_init__(self) -> None:
        _require_non_empty_text(self.receiver_text, "receiver_text")
        _require_non_empty_text(self.method, "method")


@dataclass(frozen=True)
class RawScope:
    """One scope (module/function/method/class/arrow) per contract section 3.2."""

    kind: str
    name: str
    signature_text: str
    span: Span

    def __post_init__(self) -> None:
        _require_enum_value(self.kind, SCOPE_KINDS, "kind")
        _require_non_empty_text(self.name, "name")
        # Contract section 3.2: signature_text is the empty string exactly for
        # the file-level `module` scope, so only other kinds require text.
        if self.kind != "module":
            _require_non_empty_text(self.signature_text, "signature_text")


@dataclass(frozen=True)
class UnresolvedNode:
    """One unresolved construct per contract section 3.2 (never a silent drop)."""

    reason: str
    span: Span | None
    detail: str

    def __post_init__(self) -> None:
        _require_enum_value(self.reason, UNRESOLVED_REASONS, "reason")
        _require_non_empty_text(self.detail, "detail")


@dataclass(frozen=True)
class ParseResult:
    """The complete parse outcome for one file (contract section 3.2)."""

    path: str
    content_hash: str
    grammar_id: str
    grammar_version: str
    size_bytes: int
    loc: int
    tree: Tree | None
    redis_callsites: tuple[RawRedisCallsite, ...]
    scopes: tuple[RawScope, ...]
    unresolved: tuple[UnresolvedNode, ...]

    def __post_init__(self) -> None:
        _require_enum_value(self.grammar_id, GRAMMAR_IDS, "grammar_id")
        if not isinstance(self.path, str) or not 1 <= len(self.path) <= 4096:
            raise ValueError(f"path must be a 1..4096 char string, got {self.path!r}")
        if _CONTENT_HASH_PATTERN.fullmatch(self.content_hash) is None:
            raise ValueError(

                    f"content_hash must be 64 lowercase hex chars, got"
                    f" {self.content_hash!r}"

            )
        if not isinstance(self.grammar_version, str) or not self.grammar_version:
            raise ValueError("grammar_version must be a non-empty version string")
        if self.size_bytes < 0 or self.loc < 0:
            raise ValueError("size_bytes and loc must be >= 0")
        if (
            self.redis_callsites is None
            or self.scopes is None
            or self.unresolved is None
        ):
            raise ValueError(
                "redis_callsites, scopes and unresolved must be tuples, not None"
            )
