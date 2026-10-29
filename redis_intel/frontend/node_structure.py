"""Tree-sitter node helpers shared by the frontend iterators.

Bounded traversal (an explicit stack, capped by the AST node budget of PLAN
section 4.11), span/text conversion and the small structural predicates the
receiver resolution rules need. Nothing here imports ``iterators.py``, so the
iterators and the binding mixins can both use these helpers without a circular
import.
"""

from collections.abc import Iterator

from tree_sitter import Node

from redis_intel.frontend.models import Span

MAX_AST_NODE_BUDGET = 500_000

# Wrapper variabledeclarator values may hide the construction behind these
# transparent expression nodes; unwrapping stays one-hop by construction.
_TRANSPARENT_VALUE_NODE_TYPES = frozenset({
    "await_expression",
    "parenthesized_expression",
})


_CLASS_NODE_KINDS = frozenset({"class_declaration", "class_expression"})
_FUNCTION_FACTORY_NODE_KINDS = frozenset({
    "function_declaration",
    "generator_function_declaration",
    "function_expression",
    "generator_function",
    "arrow_function",
})


def _class_key(class_node: Node) -> tuple[int, int]:
    """Stable identity for a class node across tree-sitter node accesses.

    tree-sitter creates fresh node objects on every child/parent access, so
    ``id()`` is not stable; a node's ``(start_byte, end_byte)`` span is.
    """
    return (class_node.start_byte, class_node.end_byte)


def iter_preorder_nodes_bounded(root_node: Node, node_limit: int) -> Iterator[Node]:
    """Yield ``root_node`` and its descendants in pre-order, capped at ``node_limit``.

    Uses an explicit stack instead of recursion, so deeply nested trees
    cannot exhaust the Python call stack. Stops after exactly ``node_limit``
    nodes when the tree is larger.
    """
    if node_limit < 1:
        raise ValueError(f"node_limit must be >= 1, got {node_limit}")
    pending_nodes = [root_node]
    visited_node_count = 0
    while pending_nodes:
        if visited_node_count >= node_limit:
            return
        node = pending_nodes.pop()
        yield node
        visited_node_count += 1
        # Children are pushed in reverse so the leftmost child pops first,
        # keeping the yield order a true pre-order (source order).
        pending_nodes.extend(reversed(node.children))


def span_from_node(node: Node) -> Span:
    """Convert a tree-sitter node into a 1-based inclusive Span (contract section 1)."""
    start_line = node.start_point.row + 1
    start_col = node.start_point.column + 1
    end_line = node.end_point.row + 1
    if end_line == start_line:
        # An exclusive end column equal to the start column marks an empty
        # node: both ends point at the same character position.
        end_col = (
            node.end_point.column
            if node.end_point.column > node.start_point.column
            else start_col
        )
    else:
        end_col = max(node.end_point.column, 1)
    return Span(
        start_line=start_line, start_col=start_col, end_line=end_line, end_col=end_col
    )


def node_text(node: Node) -> str:
    """Return the node's verbatim source text, decoded leniently."""
    node_source = node.text
    if node_source is None:
        return ""
    return node_source.decode("utf-8", errors="replace")


def _enclosing_class(node: Node) -> Node | None:
    """Return the nearest enclosing class declaration/expression node, if any."""
    current_node: Node | None = node.parent
    while current_node is not None:
        if current_node.type in _CLASS_NODE_KINDS:
            return current_node
        current_node = current_node.parent
    return None


def _enclosing_constructor_class(node: Node) -> Node | None:
    """Return the enclosing class when ``node`` sits inside a constructor body.

    R2 constructor-parameter injection only applies to assignments inside a
    constructor, so assignments in other methods are ignored.
    """
    current_node: Node | None = node.parent
    while current_node is not None:
        if current_node.type == "method_definition":
            name_node = current_node.child_by_field_name("name")
            if name_node is None or node_text(name_node) != "constructor":
                return None
            return _enclosing_class(current_node)
        if current_node.type in _CLASS_NODE_KINDS:
            return None
        current_node = current_node.parent
    return None


def _annotation_base_name(type_node: Node | None) -> str | None:
    """Return the base type name of a type annotation, ignoring generic args.

    ``RedisClientType<...>`` and plain ``RedisClientType`` both resolve to the
    base name ``RedisClientType`` (contract rev 3 section 3.4 R2 "equivalent
    generic forms"). Union types (``A | B``) and anything that is not a plain
    type name resolve to ``None`` — a union never names a Redis client type
    from the fixed set.
    """
    if type_node is None or type_node.type != "type_annotation":
        return None
    named_children = type_node.named_children
    if not named_children:
        return None
    type_expression = named_children[0]
    if type_expression.type == "generic_type":
        name_node = type_expression.child_by_field_name("name")
        return node_text(name_node) if name_node is not None else None
    if type_expression.type == "type_identifier":
        return node_text(type_expression)
    return None


def _unwrap_expression(value_node: Node | None) -> Node | None:
    """Peel transparent wrappers (await, parens) off a declarator value."""
    while value_node is not None and value_node.type in _TRANSPARENT_VALUE_NODE_TYPES:
        value_node = value_node.named_children[0] if value_node.named_children else None
    return value_node


def _unquote_module_name(source_text: str) -> str:
    if (
        len(source_text) >= 2
        and source_text[0] in {"'", '"'}
        and source_text[-1] == source_text[0]
    ):
        return source_text[1:-1]
    return source_text


def _argument_texts(call_node: Node) -> tuple[str, ...]:
    arguments_node = call_node.child_by_field_name("arguments")
    if arguments_node is None:
        return ()
    return tuple(node_text(child) for child in arguments_node.named_children)
