"""Bounded tree-sitter tree iterators for the C-1 frontend surface.

Implements contract ``ir-boundary`` rev 3 section 3.4: ``iter_redis_callsites``
and ``iter_scopes`` yield exactly the tuples that ``LanguageFrontend.parse``
embeds in its ``ParseResult`` — same spans, same source order. Receiver
recognition applies the five resolution rules in order (first match wins):
R1 same-class member binding (field initializer is the construction), R2
constructor-parameter injection (fixed Redis client type-annotation set), R3
same-file factory returns, R4 dynamic ``require`` module acquisition, and R5
negatives (unresolvable receivers are never callsites).
``iter_unresolved_redis_method_calls`` accounts for Redis-shaped member calls
whose receiver does not resolve, so the callsite stream stays receiver-gated
without silently dropping dynamic-receiver Redis calls (AC-12). Every text
comes from the tree itself (``node.text``), so the iterators need the parsed
tree only, never the source file. Traversal uses an explicit stack rather
than recursion and is bounded by the AST node budget of PLAN section 4.11,
so extraction can neither blow the call stack nor hang.
"""

from collections.abc import Iterator
from typing import Self

from tree_sitter import Node, Tree

from redis_intel.frontend.bindings_factories import _FactoryRecordingMixin
from redis_intel.frontend.bindings_fields import _ClassFieldsMixin
from redis_intel.frontend.bindings_imports import _ImportRecordingMixin
from redis_intel.frontend.bindings_packages import _PackageResolutionMixin
from redis_intel.frontend.bindings_resolution import _ResolutionMixin
from redis_intel.frontend.bindings_types import (
    _CLASS_FIELD_KIND_ALIAS,
    _CLASS_FIELD_KIND_CONSTRUCTION,
    _CLASS_FIELD_KIND_FACTORY,
    _CLASS_FIELD_KIND_INJECTION,
    _ClassFieldBinding,
    _FactoryDefinition,
)
from redis_intel.frontend.method_names import (
    IOREDIS_CONSTRUCTOR_NAMES,
    IOREDIS_PACKAGE_NAME,
    NODE_REDIS_FACTORY_NAMES,
    NODE_REDIS_PACKAGE_NAME,
    REDIS_CLIENT_TYPE_ANNOTATIONS,
    REDIS_METHOD_NAMES,
    REQUIRE_ACQUIRED_PACKAGES,
)
from redis_intel.frontend.models import (
    RawRedisCallsite,
    RawScope,
    Span,
    UnresolvedNode,
)
from redis_intel.frontend.node_structure import (
    _CLASS_NODE_KINDS,
    _FUNCTION_FACTORY_NODE_KINDS,
    _TRANSPARENT_VALUE_NODE_TYPES,
    MAX_AST_NODE_BUDGET,
    _annotation_base_name,
    _argument_texts,
    _class_key,
    _enclosing_class,
    _enclosing_constructor_class,
    _unquote_module_name,
    _unwrap_expression,
    iter_preorder_nodes_bounded,
    node_text,
    span_from_node,
)
from redis_intel.frontend.scope_naming import (
    _SCOPE_NODE_KINDS,
    _container_label,
    _qualified_scope_name,
    _scope_own_name,
    _signature_text,
    iter_scopes,
)

__all__ = [
    "MAX_AST_NODE_BUDGET",
    "REDIS_METHOD_NAMES",
    "IOREDIS_CONSTRUCTOR_NAMES",
    "REDIS_CLIENT_TYPE_ANNOTATIONS",
    "NODE_REDIS_FACTORY_NAMES",
    "IOREDIS_PACKAGE_NAME",
    "NODE_REDIS_PACKAGE_NAME",
    "REQUIRE_ACQUIRED_PACKAGES",
    "_TRANSPARENT_VALUE_NODE_TYPES",
    "_CLASS_FIELD_KIND_CONSTRUCTION",
    "_CLASS_FIELD_KIND_INJECTION",
    "_CLASS_FIELD_KIND_FACTORY",
    "_CLASS_FIELD_KIND_ALIAS",
    "_CLASS_NODE_KINDS",
    "_FUNCTION_FACTORY_NODE_KINDS",
    "_ClassFieldBinding",
    "_FactoryDefinition",
    "_class_key",
    "_SCOPE_NODE_KINDS",
    "iter_preorder_nodes_bounded",
    "span_from_node",
    "node_text",
    "iter_redis_callsites",
    "iter_unresolved_redis_method_calls",
    "iter_scopes",
    "_ClientBindings",
    "_enclosing_class",
    "_enclosing_constructor_class",
    "_annotation_base_name",
    "_unwrap_expression",
    "_unquote_module_name",
    "_argument_texts",
    "_scope_own_name",
    "_qualified_scope_name",
    "_container_label",
    "_signature_text",
    "Iterator",
    "Node",
    "Tree",
    "Span",
    "RawRedisCallsite",
    "RawScope",
    "UnresolvedNode",
]


def iter_redis_callsites(tree: Tree) -> Iterator[RawRedisCallsite]:
    """Yield every recognized Redis callsite in source order (contract section 3.4).

    Recognition is receiver-based with one-hop import/alias tracking: a
    member call whose receiver statically resolves to a known client
    construction — or to a name bound to one — yields a callsite with
    ``client_hint`` carrying that name. Client constructions themselves
    (``new Redis(...)`` and node-redis factory calls like ``createClient()``)
    also yield callsites with method ``"new"``. A member call on a receiver
    that does not statically resolve to a client construction is never a
    callsite: Redis-plausible methods on unresolvable receivers are recorded
    instead by ``iter_unresolved_redis_method_calls`` (never dropped).
    """
    root_node = tree.root_node
    bindings = _ClientBindings.from_tree(root_node)
    for node in iter_preorder_nodes_bounded(root_node, MAX_AST_NODE_BUDGET):
        if node.type == "new_expression":
            client_hint = bindings.resolve_construction_client_hint(node)
            if client_hint:
                constructor_node = node.child_by_field_name("constructor")
                yield RawRedisCallsite(
                    receiver_text=(
                        node_text(constructor_node) if constructor_node else ""
                    ),
                    method="new",
                    argument_texts=_argument_texts(node),
                    span=span_from_node(node),
                    client_hint=client_hint,
                )
            continue
        if node.type != "call_expression":
            continue
        function_node = node.child_by_field_name("function")
        if not function_node:
            continue
        client_hint = bindings.resolve_construction_client_hint(node)
        if client_hint:
            yield RawRedisCallsite(
                receiver_text=node_text(function_node),
                method="new",
                argument_texts=_argument_texts(node),
                span=span_from_node(node),
                client_hint=client_hint,
            )
            continue
        if function_node.type != "member_expression":
            continue
        receiver_node = function_node.child_by_field_name("object")
        method_node = function_node.child_by_field_name("property")
        if receiver_node is None or method_node is None:
            continue
        client_hint = bindings.resolve_receiver_client_hint(receiver_node)
        if not client_hint:
            # A member call on a receiver that does not statically resolve to
            # a client construction is not a callsite (contract section 3.4);
            # Redis-shaped ones are accounted for by
            # iter_unresolved_redis_method_calls so nothing is silently dropped.
            continue
        yield RawRedisCallsite(
            receiver_text=node_text(receiver_node),
            method=node_text(method_node),
            argument_texts=_argument_texts(node),
            span=span_from_node(node),
            client_hint=client_hint,
        )


def iter_unresolved_redis_method_calls(tree: Tree) -> Iterator[UnresolvedNode]:
    """Account for Redis-shaped member calls on unresolvable receivers (AC-12).

    ``iter_redis_callsites`` only recognizes calls whose receiver statically
    resolves to a client construction. Without this accounting a dynamic
    receiver Redis call (for example ``clients[k].get(key)``) would be
    silently dropped: it is neither a recognized callsite nor a known
    non-Redis construct. Every member call is accounted for exactly once:
    resolved receivers yield callsites from ``iter_redis_callsites`` for any
    method name, unresolvable receivers yield one of these unresolved entries
    when the method plausibly names a Redis command, and everything else is
    not a Redis construct.
    """
    root_node = tree.root_node
    bindings = _ClientBindings.from_tree(root_node)
    for node in iter_preorder_nodes_bounded(root_node, MAX_AST_NODE_BUDGET):
        if node.type != "call_expression":
            continue
        function_node = node.child_by_field_name("function")
        if function_node is None or function_node.type != "member_expression":
            continue
        receiver_node = function_node.child_by_field_name("object")
        method_node = function_node.child_by_field_name("property")
        if receiver_node is None or method_node is None:
            continue
        if bindings.resolve_receiver_client_hint(receiver_node) is not None:
            continue
        method = node_text(method_node)
        if method.lower() not in REDIS_METHOD_NAMES:
            continue
        receiver_text = node_text(receiver_node)
        yield UnresolvedNode(
            reason="unresolvable_expression",
            span=span_from_node(node),
            detail=(
                f'member call "{receiver_text}.{method}" does not statically resolve '
                "to a known Redis client construction (contract ir-boundary section "
                "3.4); recorded for accounting, not recognized as a callsite"
            ),
        )


class _ClientBindings(
    _ResolutionMixin,
    _FactoryRecordingMixin,
    _ImportRecordingMixin,
    _PackageResolutionMixin,
    _ClassFieldsMixin,
):
    """Import aliases and variable bindings collected from one tree.

    ``import_aliases`` maps a local name to ``(package, imported_name)``;
    ``direct_client_names`` are locals whose initializer statically
    constructs a known client; ``alias_bindings`` map a local to another
    local it was copied from (the one hop of wrapper tracking).

    Contract rev 3 section 3.4 additions: ``class_fields`` maps
    ``_class_key(class_node)`` to that class's field bindings (R1 field-initializer
    constructions, R2 constructor-parameter injections, R3 factory-bound
    fields); ``factories``/``class_methods`` hold in-file functions whose
    returned expression may bind a receiver (R3); ``call_bindings`` map a
    local to the call expression it was bound from (R3 receiver lookup);
    R4 ``require('ioredis')``/``require('redis')`` results are recorded as
    ``import_aliases`` entries equivalent to static imports.
    """

    def __init__(self) -> None:
        self.import_aliases: dict[str, tuple[str, str]] = {}
        self.direct_client_names: set[str] = set()
        self.alias_bindings: dict[str, str] = {}
        self.class_fields: dict[tuple[int, int], dict[str, _ClassFieldBinding]] = {}
        self.factories: dict[str, _FactoryDefinition] = {}
        self.class_methods: dict[tuple[int, int], dict[str, _FactoryDefinition]] = {}
        self.call_bindings: dict[str, Node] = {}

    @classmethod
    def from_tree(cls, root_node: Node) -> Self:
        bindings = cls()
        for node in iter_preorder_nodes_bounded(root_node, MAX_AST_NODE_BUDGET):
            if node.type == "import_specifier":
                bindings._record_import_specifier(node)
            elif node.type == "import_clause":
                bindings._record_default_import(node)
            elif node.type == "variable_declarator":
                bindings._record_variable_declarator(node)
            elif node.type == "assignment_expression":
                bindings._record_require_assignment(node)
                bindings._record_this_assignment(node)
            elif node.type in _CLASS_NODE_KINDS:
                bindings._record_class(node)
            elif node.type in _FUNCTION_FACTORY_NODE_KINDS:
                bindings._record_factory(node, class_key=None)
            elif node.type == "method_definition":
                enclosing_class = _enclosing_class(node)
                if enclosing_class is not None:
                    bindings._record_factory(
                        node, class_key=_class_key(enclosing_class)
                    )
        return bindings
