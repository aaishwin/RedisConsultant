"""Scope iteration and naming for the frontend (contract section 3.2/3.4).

``iter_scopes`` yields the file-level ``module`` scope first and then every
named declaration in source order with its dotted qualified name. The scope
kind map and the qualified-name/signature helpers it needs live beside it, so
``iterators.py`` keeps only the receiver-gated callsite iterators and the
``_ClientBindings`` that feeds them.
"""

from collections.abc import Iterator

from tree_sitter import Node, Tree

from redis_intel.frontend.models import RawScope
from redis_intel.frontend.node_structure import (
    _TRANSPARENT_VALUE_NODE_TYPES,
    MAX_AST_NODE_BUDGET,
    iter_preorder_nodes_bounded,
    node_text,
    span_from_node,
)

_SCOPE_NODE_KINDS: dict[str, str] = {
    "function_declaration": "function",
    "function_expression": "function",
    "generator_function_declaration": "function",
    "generator_function": "function",
    "method_definition": "method",
    "class_declaration": "class",
    "class_expression": "class",
    "arrow_function": "arrow",
}


def _scope_own_name(node: Node) -> str:
    """Return the declaration's own (unqualified) name."""
    if node.type in {"function_declaration", "generator_function_declaration"}:
        name_node = node.child_by_field_name("name")
        return node_text(name_node) if name_node is not None else "<function>"
    if node.type in {"class_declaration", "class_expression"}:
        name_node = node.child_by_field_name("name")
        return node_text(name_node) if name_node is not None else "<class>"
    if node.type == "method_definition":
        name_node = node.child_by_field_name("name")
        return node_text(name_node) if name_node is not None else "<method>"
    # function/generator/arrow expressions take their name from the
    # enclosing variable declarator, like `const load = () => ...`.
    current_node = node.parent
    while (
        current_node is not None and current_node.type in _TRANSPARENT_VALUE_NODE_TYPES
    ):
        current_node = current_node.parent
    if current_node is not None and current_node.type == "variable_declarator":
        bound_name_node = current_node.child_by_field_name("name")
        if bound_name_node is not None:
            return node_text(bound_name_node)
    return "<arrow>" if node.type == "arrow_function" else "<function>"


def _qualified_scope_name(node: Node, own_name: str) -> str:
    """Build the dotted qualified name from the enclosing containers."""
    container_labels: list[str] = []
    current_node = node.parent
    while current_node is not None:
        container_label = _container_label(current_node)
        if container_label is not None:
            container_labels.append(container_label)
        current_node = current_node.parent
    return ".".join(container_labels[::-1] + [own_name])


def _container_label(node: Node) -> str | None:
    """Return the qualified-name fragment a container node contributes."""
    if node.type in {"class_declaration", "class_expression"}:
        name_node = node.child_by_field_name("name")
        return node_text(name_node) if name_node is not None else None
    if node.type == "method_definition":
        name_node = node.child_by_field_name("name")
        return node_text(name_node) if name_node is not None else None
    if node.type in {"function_declaration", "generator_function_declaration"}:
        name_node = node.child_by_field_name("name")
        return node_text(name_node) if name_node is not None else None
    if node.type in {"function_expression", "generator_function", "arrow_function"}:
        return _scope_own_name(node)
    return None


def _signature_text(node: Node) -> str:
    """Return the declaration's signature: everything before its body."""
    body_node = node.child_by_field_name("body")
    node_source = node.text
    if body_node is None or node_source is None:
        return node_text(node)
    signature_bytes = node_source[: body_node.start_byte - node.start_byte]
    return signature_bytes.decode("utf-8", errors="replace").rstrip()


def iter_scopes(tree: Tree) -> Iterator[RawScope]:
    """Yield every scope in source order (contract section 3.2/3.4).

    The first yield is always the file-level ``module`` scope with an empty
    signature text; every named declaration follows in source order with its
    dotted qualified name.
    """
    root_node = tree.root_node
    yield RawScope(
        kind="module",
        name="<module>",
        signature_text="",
        span=span_from_node(root_node),
    )
    for node in iter_preorder_nodes_bounded(root_node, MAX_AST_NODE_BUDGET):
        scope_kind = _SCOPE_NODE_KINDS.get(node.type)
        if scope_kind is None:
            continue
        own_name = _scope_own_name(node)
        yield RawScope(
            kind=scope_kind,
            name=_qualified_scope_name(node, own_name),
            signature_text=_signature_text(node),
            span=span_from_node(node),
        )
