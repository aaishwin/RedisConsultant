"""Seed-derived randomness: SHA-256 in counter mode, no global RNG state.

Every content decision in the corpus generator is derived from
``(seed, stream, counter)`` triples through SHA-256, so two runs with the same
seed produce identical bytes whatever the platform or Python-version random
implementation happens to be (Contract 2 §1 determinism; NFR-3).
"""

import hashlib
from collections.abc import Sequence


def derive_bytes(seed: int, stream: str, counter: int = 0) -> bytes:
    """Return 32 deterministic bytes unique to ``(seed, stream, counter)``."""
    material = f"{seed}:{stream}:{counter}".encode()
    return hashlib.sha256(material).digest()


def derive_int(seed: int, stream: str, counter: int, modulus: int) -> int:
    """Return a deterministic integer in ``[0, modulus)``."""
    if modulus <= 0:
        raise ValueError(f"modulus must be positive, got {modulus}")
    return int.from_bytes(derive_bytes(seed, stream, counter)[:4], "big") % modulus


def derive_pick(
    seed: int, stream: str, options: Sequence[str], counter: int = 0
) -> str:
    """Return one deterministic element from ``options``."""
    if not options:
        raise ValueError("derive_pick requires a non-empty options sequence")
    return options[derive_int(seed, stream, counter, len(options))]
