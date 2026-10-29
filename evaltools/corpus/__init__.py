"""Deterministic bilingual synthetic-corpus generator (FR-1..FR-5).

Pure seed-to-bytes generation: no wall-clock reads, no unseeded randomness, no
network access, and every emitted list is sorted before writing. The generated
trees land under the gitignored ``corpora/`` directory; the committed evidence
is the three manifests (Contract 2 §3.1-§3.3) plus ``results/determinism.json``.
"""
