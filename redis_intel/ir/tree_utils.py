"""Shared tree-sitter traversal utilities for the C-2 IR builder.

Implemented inside ``redis_intel.ir`` (not imported from the frontend's
private ``iterators`` module) so the IR builder owns its own bounded
traversal: an explicit stack instead of recursion, capped at the PLAN
section 4.11 AST node budget so traversal can neither blow the call stack
nor hang. Text is decoded leniently from ``node.text``.
"""

from collections.abc import Iterator
from typing import Any

MAX_AST_NODE_BUDGET = 500_000

_TRANSPARENT_EXPRESSION_NODE_TYPES = frozenset({
    "await_expression",
    "parenthesized_expression",
})


def iter_preorder_nodes_bounded(root_node: Any, node_limit: int) -> Iterator[Any]:
    """Yield ``root_node`` and descendants in pre-order, capped by ``node_limit``."""
    if node_limit < 1:
        raise ValueError(f"node_limit must be >= 1, got {node_limit}")
    pending_nodes: list[Any] = [root_node]
    visited_node_count = 0
    while pending_nodes:
        if visited_node_count >= node_limit:
            return
        node = pending_nodes.pop()
        yield node
        visited_node_count += 1
        pending_nodes.extend(reversed(node.children))


def node_text(node: Any) -> str:
    """Return the node's verbatim source text, decoded leniently."""
    source_text = getattr(node, "text", None)
    if source_text is None:
        return ""
    return source_text.decode("utf-8", errors="replace")


def span_from_node(node: Any) -> tuple[int, int, int, int]:
    """Convert a tree-sitter node into a 1-based inclusive span tuple.

    Returns ``(start_line, start_col, end_line, end_col)``.
    """
    start_line = node.start_point.row + 1
    start_col = node.start_point.column + 1
    end_line = node.end_point.row + 1
    end_col = max(node.end_point.column, 1)
    return (start_line, start_col, end_line, end_col)


def unwrap_transparent_expression(value_node: Any) -> Any:
    """Peel transparent wrappers (``await``, parentheses) off a declarator value."""
    while (
        value_node is not None and value_node.type in _TRANSPARENT_EXPRESSION_NODE_TYPES
    ):
        named_children = value_node.named_children
        value_node = named_children[0] if named_children else None
    return value_node
