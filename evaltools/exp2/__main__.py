"""Run entry point for the EXP-2 extraction-precision harness.

``uv run python -m evaltools.exp2`` parses every labelled file, matches
predictions to the frozen labels, and writes ``results/exp2.json``.
"""

from evaltools.exp2.harness import main

if __name__ == "__main__":
    raise SystemExit(main())
