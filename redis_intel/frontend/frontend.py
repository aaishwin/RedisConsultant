"""C-1 frontend: ``LanguageFrontend.parse`` producing ``ParseResult``.

Implements contract ``ir-boundary`` rev 2 sections 3.2 and 3.3. Parsing
never raises on target-repo content: unresolvable input is recorded in
``ParseResult.unresolved`` (never thrown, never dropped), while malformed
caller inputs (paths violating the contract) fail fast.
"""

import hashlib

from tree_sitter import Node, Parser, Tree

from redis_intel.frontend import iterators
from redis_intel.frontend.grammar_registry import (
    GRAMMAR_ID_UNSUPPORTED,
    GrammarBinding,
    grammar_binding_for_path,
    language_for_grammar_id,
)
from redis_intel.frontend.models import ParseResult, Span, UnresolvedNode

MAX_PARSED_FILE_SIZE_BYTES = 1_000_000
MAX_PATH_LENGTH_CHARS = 4096
MAX_ERROR_FRAGMENT_CHARS = 60


class LanguageFrontend:
    """Parse one TypeScript/TSX/JavaScript file into a :class:`ParseResult`."""

    def parse(self, path: str, source: bytes) -> ParseResult:
        """Parse ``source`` bytes found at repo-relative ``path`` (contract §3.2).

        Caps per contract section 3.3: a source above 1 MB yields
        ``file_too_large`` with ``tree=None`` and no extraction; a tree above
        the 500,000 node budget yields ``node_budget_exceeded`` with
        extraction stopped at the budget boundary. Tree-sitter ERROR regions
        become one ``parse_error`` entry each while the tree is still
        returned. An unsupported extension yields exactly one
        ``unsupported_syntax`` entry with no tree, callsites or scopes.
        """
        _validate_path(path)
        binding = grammar_binding_for_path(path)
        content_hash = hashlib.sha256(source).hexdigest()
        decoded_source = source.decode("utf-8", errors="replace")
        loc = len(decoded_source.splitlines())
        unresolved, tree = self._resolve_tree_and_unresolved(path, binding, source)
        redis_callsites: tuple = ()
        scopes: tuple = ()
        if tree is not None:
            redis_callsites = tuple(iterators.iter_redis_callsites(tree))
            scopes = tuple(iterators.iter_scopes(tree))
            unresolved = unresolved + tuple(
                iterators.iter_unresolved_redis_method_calls(tree)
            )
        return ParseResult(
            path=path,
            content_hash=content_hash,
            grammar_id=binding.grammar_id,
            grammar_version=binding.grammar_version,
            size_bytes=len(source),
            loc=loc,
            tree=tree,
            redis_callsites=redis_callsites,
            scopes=scopes,
            unresolved=unresolved,
        )

    def _resolve_tree_and_unresolved(
        self, path: str, binding: GrammarBinding, source: bytes
    ) -> tuple[tuple[UnresolvedNode, ...], Tree | None]:
        """Parse the source and produce the file's unresolved entries, or None tree.

        The three terminal outcomes (unsupported extension, over-size source)
        produce no tree and exactly one file-level unresolved entry; a parsed
        tree carries parse_error entries per ERROR region plus the
        node_budget_exceeded entry when the tree overflows the node budget.
        """
        if binding.grammar_id == GRAMMAR_ID_UNSUPPORTED:
            return (
                UnresolvedNode(
                    reason="unsupported_syntax",
                    span=None,
                    detail=(
                        f"no grammar is registered for the extension of path "
                        f"{path!r} (contract ir-boundary section 3.1)"
                    ),
                ),
            ), None
        if len(source) > MAX_PARSED_FILE_SIZE_BYTES:
            return (
                UnresolvedNode(
                    reason="file_too_large",
                    span=None,
                    detail=(
                        f"source is {len(source)} bytes, above the "
                        f"{MAX_PARSED_FILE_SIZE_BYTES} byte parse cap; not parsed"
                    ),
                ),
            ), None
        language = language_for_grammar_id(binding.grammar_id)
        tree = Parser(language).parse(source)
        return self._unresolved_entries_for_tree(tree), tree

    def _unresolved_entries_for_tree(self, tree: Tree) -> tuple[UnresolvedNode, ...]:
        error_spans, node_budget_exceeded = self._collect_error_spans_and_budget_flag(
            tree
        )
        unresolved_entries: list[UnresolvedNode] = []
        if node_budget_exceeded:
            unresolved_entries.append(
                UnresolvedNode(
                    reason="node_budget_exceeded",
                    span=None,
                    detail=(
                        f"tree exceeds the {iterators.MAX_AST_NODE_BUDGET} node "
                        "budget; extraction stopped at the budget boundary"
                    ),
                )
            )
        unresolved_entries.extend(
            UnresolvedNode(
                reason="parse_error",
                span=error_span,
                detail=self._parse_error_detail(tree, error_span),
            )
            for error_span in error_spans
        )
        return tuple(unresolved_entries)

    def _collect_error_spans_and_budget_flag(
        self, tree: Tree
    ) -> tuple[list[Span], bool]:
        """Walk the tree once for ERROR regions and the node-budget flag.

        The walk is bounded at budget+1 nodes: one past the budget answers
        the exceedance question, so this pass can never hang on huge trees.
        """
        error_spans: list[Span] = []
        visited_node_count = 0
        for node in iterators.iter_preorder_nodes_bounded(
            tree.root_node, iterators.MAX_AST_NODE_BUDGET + 1
        ):
            visited_node_count += 1
            if node.is_error:
                error_spans.append(iterators.span_from_node(node))
        return error_spans, visited_node_count > iterators.MAX_AST_NODE_BUDGET

    def _parse_error_detail(self, tree: Tree, error_span: Span) -> str:
        fragment = self._short_error_fragment(tree, error_span)
        if fragment:
            return (
                f"tree-sitter reported an ERROR region covering lines "
                f"{error_span.start_line}-{error_span.end_line} with fragment "
                f'"{fragment}"'
            )
        return (
            f"tree-sitter reported an ERROR region covering lines "
            f"{error_span.start_line}-{error_span.end_line}"
        )

    def _short_error_fragment(self, tree: Tree, error_span: Span) -> str:
        """Return one short single-line fragment quoted from the ERROR region."""
        error_node = self._error_node_for_span(tree, error_span)
        if error_node is None:
            return ""
        fragment = iterators.node_text(error_node)
        if "\n" in fragment:
            fragment = " ".join(fragment.splitlines())
        if len(fragment) > MAX_ERROR_FRAGMENT_CHARS:
            fragment = fragment[: MAX_ERROR_FRAGMENT_CHARS - 3] + "..."
        return fragment

    def _error_node_for_span(self, tree: Tree, error_span: Span) -> Node | None:
        """Re-find the ERROR node for a span, keeping only spans across passes."""
        for node in iterators.iter_preorder_nodes_bounded(
            tree.root_node, iterators.MAX_AST_NODE_BUDGET + 1
        ):
            if node.is_error and iterators.span_from_node(node) == error_span:
                return node
        return None


def _validate_path(path: str) -> None:
    """Fail fast on contract misuse of the path argument (never on content)."""
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty repo-relative POSIX path string")
    if len(path) > MAX_PATH_LENGTH_CHARS:
        raise ValueError(f"path exceeds {MAX_PATH_LENGTH_CHARS} characters")
    if "\\" in path or path.startswith("/"):
        raise ValueError(
            f"path must be repo-relative with POSIX separators, got {path!r}"
        )
