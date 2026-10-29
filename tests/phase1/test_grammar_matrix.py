"""AC-11 (FR-13, FR-14): grammar_id matrix; TSX never via the TypeScript grammar."""

import os

from qa_support import GRAMMAR_MATRIX_SOURCES
from tree_sitter import Node, Parser

from redis_intel.frontend import LanguageFrontend
from redis_intel.frontend.grammar_registry import (
    EXTENSION_TO_GRAMMAR_ID,
    grammar_binding_for_path,
    language_for_grammar_id,
    resolved_core_grammar_version,
)

CONTRACT_GRAMMAR_MATRIX = {
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}


def test_registry_matches_the_contract_matrix() -> None:
    assert EXTENSION_TO_GRAMMAR_ID == CONTRACT_GRAMMAR_MATRIX


def test_tsx_is_never_the_typescript_grammar() -> None:
    binding = grammar_binding_for_path("component.tsx")
    assert binding.grammar_id == "tsx"
    assert binding.grammar_id != "typescript"
    # The two grammar ids are distinct grammar objects from the same wheel.
    assert language_for_grammar_id("tsx") is not language_for_grammar_id("typescript")


def _tree_contains_error(root_node: Node) -> bool:
    if root_node.is_error:
        return True
    return any(_tree_contains_error(child) for child in root_node.named_children)


def test_tsx_source_parses_cleanly_only_under_the_tsx_grammar() -> None:
    """Structural proof that TSX must not be parsed with the TypeScript grammar."""
    tsx_source = GRAMMAR_MATRIX_SOURCES["plain.tsx"].encode()
    tsx_tree = Parser(language_for_grammar_id("tsx")).parse(tsx_source)
    typescript_tree = Parser(language_for_grammar_id("typescript")).parse(tsx_source)
    assert not _tree_contains_error(tsx_tree.root_node)
    assert _tree_contains_error(typescript_tree.root_node), (
        "the TSX fixture parses without ERROR under the TypeScript grammar, so "
        "this fixture cannot distinguish the two grammars"
    )


def test_every_extension_yields_the_contract_grammar_id() -> None:
    frontend = LanguageFrontend()
    expected_core_version = resolved_core_grammar_version()
    for path, source in GRAMMAR_MATRIX_SOURCES.items():
        parse_result = frontend.parse(path, source.encode())
        extension = os.path.splitext(path)[1]
        expected_grammar_id = CONTRACT_GRAMMAR_MATRIX[extension]
        assert parse_result.grammar_id == expected_grammar_id, (
            f"{path}: grammar_id {parse_result.grammar_id!r} != {expected_grammar_id!r}"
        )
        assert parse_result.grammar_version == expected_core_version
        assert parse_result.tree is not None
        assert not parse_result.unresolved


def test_unsupported_extension_is_recorded_not_dropped() -> None:
    frontend = LanguageFrontend()
    parse_result = frontend.parse("plain.py", b"x = 1\n")
    assert parse_result.grammar_id == "unsupported"
    assert parse_result.tree is None
    assert not parse_result.redis_callsites
    assert not parse_result.scopes
    assert [entry.reason for entry in parse_result.unresolved] == ["unsupported_syntax"]
    assert len(parse_result.unresolved) == 1
