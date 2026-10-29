"""Shared content-building primitives for the bilingual corpus emitters.

Both language emitters produce :class:`FileContent` objects: the raw source
lines plus the exact ground-truth spans for any planted defect or escalation
construct. Spans are 1-based lines and 1-based columns, inclusive on both ends
(Contract 2 §1), and are located by searching the generated lines themselves,
so a manifest span can never drift from the emitted bytes.
"""

from dataclasses import dataclass

# Shared vocabulary so both languages draw entity names from one fixed list.
ENTITIES = (
    "user",
    "session",
    "cart",
    "product",
    "order",
    "profile",
    "token",
    "invoice",
    "quota",
    "preference",
)


@dataclass(frozen=True)
class DefectSpec:
    """One planted defect: rule id plus the located ground-truth span."""

    rule_id: str
    span: dict[str, int]


@dataclass(frozen=True)
class EscalationSpec:
    """One escalation construct: reason code plus the located span."""

    reason_code: str
    span: dict[str, int]


@dataclass(frozen=True)
class FileContent:
    """Generated file bytes in line form plus its embedded ground truth."""

    lines: list[str]
    defects: list[DefectSpec]
    escalations: list[EscalationSpec]


def shift_span(span: dict[str, int], line_offset: int) -> dict[str, int]:
    """Convert a block-relative span into file-absolute lines.

    Special blocks (defects, escalations) locate their spans inside their own
    block first; the file assembler then shifts them by the number of lines
    already emitted above the block.
    """
    return {
        "start_line": span["start_line"] + line_offset,
        "start_col": span["start_col"],
        "end_line": span["end_line"] + line_offset,
        "end_col": span["end_col"],
    }


def locate_span(
    lines: list[str],
    start_index: int,
    start_substring: str,
    end_index: int | None = None,
    end_substring: str | None = None,
) -> dict[str, int]:
    """Locate a 1-based inclusive span for a substring inside ``lines``.

    ``start_substring`` must occur on ``lines[start_index]``; the optional
    ``end_index``/``end_substring`` pair extends the span across multiple
    lines (used by multi-statement constructs such as read-modify-write).
    ``ValueError`` propagates when a substring is absent, so a template edit
    that moves a construct fails the run rather than writing a wrong span.
    """
    resolved_end_index = start_index if end_index is None else end_index
    resolved_end_substring = start_substring if end_substring is None else end_substring
    start_col = lines[start_index].index(start_substring) + 1
    end_col = lines[resolved_end_index].index(resolved_end_substring) + len(
        resolved_end_substring
    )
    return {
        "start_line": start_index + 1,
        "start_col": start_col,
        "end_line": resolved_end_index + 1,
        "end_col": end_col,
    }
