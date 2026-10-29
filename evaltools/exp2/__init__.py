"""EXP-2 extraction-precision pilot (task t9 / assignment EXP-2).

Measures C-1's Redis-callsite detection against 52 independently
hand-labelled callsites in the pinned bullmq snapshot and writes
``results/exp2.json`` with a code-computed verdict (Contract
``corpus-and-experiments`` sections 3.7 and 4; FR-8, FR-18, NFR-2, AC-7,
AC-15).

Modules:
- ``evaltools/exp2/labels.json``: the frozen hand-label set (authored from
  source reading only, never from extractor output; spans verified against
  the checkout).
- ``harness``: loads the labels, runs the frontend over the labelled files,
  computes TP/FP/FN/TN, the headline precision, and the verdict.
- ``__main__``: CLI entry point (``python -m evaltools.exp2``).
"""
