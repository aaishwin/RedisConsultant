"""Grammar registry: the single extension-to-grammar_id classification point.

Implements contract ``ir-boundary`` rev 2 section 3.1 (FR-14, AC-11): the
whole mapping lives here and nowhere else, so a ``.tsx`` path can never
resolve to the ``typescript`` grammar. Grammar objects are constructed
lazily from the pinned local wheels and cached — nothing is ever downloaded
at runtime (AC-18), and ``tree-sitter-language-pack`` never appears in the
dependency tree.

Verified against the pinned wheels: ``tree-sitter-javascript`` 0.23.1 exposes
the callable ``language`` (there is no ``language_javascript`` attribute),
while ``tree-sitter-typescript`` 0.23.2 exposes ``language_typescript`` and
``language_tsx``. This wheel-fact intentionally overrides the contract
table's ``language_javascript`` wording (recorded by the leader).
"""

import functools
import importlib.metadata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

import tree_sitter
import tree_sitter_javascript
import tree_sitter_typescript

GRAMMAR_ID_TYPESCRIPT = "typescript"
GRAMMAR_ID_TSX = "tsx"
GRAMMAR_ID_JAVASCRIPT = "javascript"
GRAMMAR_ID_UNSUPPORTED = "unsupported"

EXTENSION_TO_GRAMMAR_ID: dict[str, str] = {
    ".ts": GRAMMAR_ID_TYPESCRIPT,
    ".mts": GRAMMAR_ID_TYPESCRIPT,
    ".cts": GRAMMAR_ID_TYPESCRIPT,
    ".tsx": GRAMMAR_ID_TSX,
    ".js": GRAMMAR_ID_JAVASCRIPT,
    ".jsx": GRAMMAR_ID_JAVASCRIPT,
    ".mjs": GRAMMAR_ID_JAVASCRIPT,
    ".cjs": GRAMMAR_ID_JAVASCRIPT,
}

# One wheel supplies both the `typescript` and the `tsx` grammar ids; the
# javascript wheel exposes a single `language` callable.
_LANGUAGE_CALLABLES: dict[str, Callable[[], object]] = {
    GRAMMAR_ID_TYPESCRIPT: tree_sitter_typescript.language_typescript,
    GRAMMAR_ID_TSX: tree_sitter_typescript.language_tsx,
    GRAMMAR_ID_JAVASCRIPT: tree_sitter_javascript.language,
}


@dataclass(frozen=True)
class GrammarBinding:
    """Static classification outcome for one source path (contract section 3.1)."""

    grammar_id: str
    language_callable: Callable[[], object] | None
    grammar_version: str


@functools.cache
def resolved_core_grammar_version() -> str:
    """Return the resolved core ``tree-sitter`` wheel version, e.g. ``"0.23.2"``.

    Read from installed package metadata (not from PLAN prose), so the
    reported ``grammar_version`` is always the actually resolved core wheel.
    """
    return importlib.metadata.version("tree-sitter")


def grammar_binding_for_path(path: str) -> GrammarBinding:
    """Classify one source path into its :class:`GrammarBinding` per section 3.1.

    An extension outside the mapping classifies as ``unsupported`` and keeps
    the resolved core version, because ``ParseResult.grammar_version`` is
    non-null even when no grammar applies.
    """
    extension = PurePosixPath(path).suffix.lower()
    grammar_id = EXTENSION_TO_GRAMMAR_ID.get(extension, GRAMMAR_ID_UNSUPPORTED)
    return GrammarBinding(
        grammar_id=grammar_id,
        language_callable=_LANGUAGE_CALLABLES.get(grammar_id),
        grammar_version=resolved_core_grammar_version(),
    )


@functools.cache
def language_for_grammar_id(grammar_id: str) -> tree_sitter.Language:
    """Return the cached :class:`tree_sitter.Language` for a supported grammar id.

    Constructs the grammar lazily from the wheel bundled inside the installed
    package — pure in-memory loading, no network access (AC-18).
    """
    language_callable = _LANGUAGE_CALLABLES.get(grammar_id)
    if language_callable is None:
        raise ValueError(
            f"no grammar callable is registered for grammar_id {grammar_id!r}"
        )
    return tree_sitter.Language(language_callable())
