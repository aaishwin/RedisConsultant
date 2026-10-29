"""pytest fixtures and helpers shared by the qa Phase-0/1 fixture suite."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import qa_support

from redis_intel.frontend import LanguageFrontend, ParseResult
from redis_intel.ir import IrBuilder, IrDelta


@pytest.fixture(scope="session")
def frontend() -> LanguageFrontend:
    """One shared C-1 frontend instance (stateless parse entry point)."""
    return LanguageFrontend()


def parse_sources(
    frontend: LanguageFrontend, sources: dict[str, str]
) -> list[ParseResult]:
    """Parse an in-memory fixture corpus in the given path order (hermetic)."""
    return [
        frontend.parse(path, source.encode("utf-8")) for path, source in sources.items()
    ]


def ingest_sources(
    frontend: LanguageFrontend, sources: dict[str, str]
) -> tuple[list[ParseResult], IrDelta]:
    """Parse and ingest a fixture corpus, returning both stages for inspection."""
    parse_results = parse_sources(frontend, sources)
    return parse_results, IrBuilder.ingest(parse_results)


def count_silent_drops(parse_results: list[ParseResult], delta: IrDelta) -> list[str]:
    """Count §5.3 silent drops: constructs mapping to no row and no unknowns entry.

    Every scope must map to ≥1 ``scopes`` row (matched by name + start line),
    every callsite to ≥1 ``ops`` row (matched by method + start line) or an
    ``unknowns`` entry, and every unresolved node to ≥1 ``unknowns`` entry with
    the same reason. Returns human-readable descriptions of every drop found;
    the suite asserts the list stays empty (AC-12, NFR-5).
    """
    drops: list[str] = []
    file_path_by_id = {
        file_id: file_row.path for file_id, file_row in enumerate(delta.files, start=1)
    }
    for parse_result in parse_results:
        file_id = next(
            (
                candidate_id
                for candidate_id, candidate_path in file_path_by_id.items()
                if candidate_path == parse_result.path
            ),
            None,
        )
        if file_id is None:
            drops.append(f"{parse_result.path}: no files row for the parsed file")
            continue
        scope_rows = [scope for scope in delta.scopes if scope.file_id == file_id]
        op_rows = [operation for operation in delta.ops if operation.file_id == file_id]
        unknown_rows = [
            unknown
            for unknown in delta.unknowns
            if unknown.reason in {"unresolvable_expression", "dynamic_construction"}
        ]
        for raw_scope in parse_result.scopes:
            scope_matched = any(
                scope.name == raw_scope.name
                and scope.start_line == raw_scope.span.start_line
                for scope in scope_rows
            )
            if not scope_matched:
                drops.append(
                    f"{parse_result.path}: scope {raw_scope.name!r} at line "
                    f"{raw_scope.span.start_line} has no scopes row"
                )
        for callsite in parse_result.redis_callsites:
            callsite_matched = any(
                operation.method == callsite.method
                and operation.line == callsite.span.start_line
                for operation in op_rows
            )
            if not callsite_matched:
                drops.append(
                    f"{parse_result.path}: callsite {callsite.receiver_text!r}."
                    f"{callsite.method} at line {callsite.span.start_line} has no "
                    "ops row"
                )
        for unresolved_node in parse_result.unresolved:
            unresolved_matched = any(
                unknown.reason == unresolved_node.reason for unknown in unknown_rows
            ) or any(
                unknown.reason == unresolved_node.reason for unknown in delta.unknowns
            )
            if not unresolved_matched:
                drops.append(
                    f"{parse_result.path}: unresolved entry "
                    f"{unresolved_node.reason!r} ({unresolved_node.detail[:60]!r}) "
                    "has no unknowns entry"
                )
    return drops


@pytest.fixture(scope="session")
def checkout_root() -> Path:
    """The pinned bullmq checkout; skips the requesting test when unavailable."""
    if not qa_support.checkout_present():
        pytest.skip(
            "pinned bullmq checkout corpora/upstream/bullmq is not present on "
            "this machine; the checkout-based check cannot execute (recorded "
            "honestly as skipped, never as a pass)"
        )
    return qa_support.CHECKOUT_ROOT
