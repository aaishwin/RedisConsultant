"""Enforce rule 8: a Python module holds at most 250 lines of code.

Blank lines and comment-only lines are not code and are not counted. Lines
inside docstrings and multi-line strings are code and are counted.

Why this module exists: neither Ruff, Biome nor pi-lens has a
maximum-module-lines rule, and pi-lens only dispatches linter diagnostics from
Ruff / Biome / ast-grep, so rule 8 needs its own runnable check.

Usage
-----
    python -m tools.check_module_length            # the whole repository
    python -m tools.check_module_length path ...   # explicit files/directories

Exits 0 when compliant, 1 when at least one module exceeds the limit.
"""

import sys
from collections.abc import Iterable
from pathlib import Path

MAX_MODULE_CODE_LINES = 250

# Generated or third-party trees are not hand-written source.
SKIPPED_DIRECTORIES = frozenset({
    ".git",
    ".mypy_cache",
    ".pi",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "corpora",
    "__pycache__",
    "node_modules",
    "upstream",
})

REPO_ROOT = Path(__file__).resolve().parents[1]


def is_code_line(line: str) -> bool:
    """Return True when the line is neither blank nor a comment-only line."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def count_code_lines(text: str) -> int:
    """Count code lines in ``text``, excluding blank and comment-only lines."""
    return sum(1 for line in text.splitlines() if is_code_line(line))


def check_text(text: str, path: Path, limit: int = MAX_MODULE_CODE_LINES) -> int | None:
    """Return the code-line count when it exceeds ``limit``, else None."""
    count = count_code_lines(text)
    if count > limit:
        return count
    return None


def check_file(path: Path, limit: int = MAX_MODULE_CODE_LINES) -> str | None:
    """Return a violation message for one module, or None when it complies."""
    count = check_text(path.read_text(encoding="utf-8"), path, limit)
    if count is None:
        return None
    return (
        f"{path}: [rule-8-max-module-lines] {count} code lines > {limit} "
        "(blank lines and comment-only lines excluded)"
    )


def iter_python_files(paths: Iterable[Path]) -> Iterable[Path]:
    """Yield distinct Python files under ``paths``, skipping generated trees."""
    seen: set[Path] = set()
    for path in paths:
        candidates = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix != ".py":
                continue
            if SKIPPED_DIRECTORIES.intersection(candidate.parts):
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield candidate


def run(paths: Iterable[Path], limit: int = MAX_MODULE_CODE_LINES) -> list[str]:
    """Return one violation message per module that exceeds ``limit``."""
    messages: list[str] = []
    for path in iter_python_files(paths):
        message = check_file(path, limit)
        if message is not None:
            messages.append(message)
    return messages


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: print violations and return the process exit code."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    targets = [Path(item) for item in arguments] or [REPO_ROOT]
    messages = run(targets)
    for message in messages:
        print(message)
    if messages:
        print(f"\n{len(messages)} module(s) exceed the limit", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
