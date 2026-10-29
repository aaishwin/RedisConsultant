"""Computed ``measurement_environment`` block shared by every experiment result file.

Contract 2 §3.8 (FR-11, AC-9): every artifact carries a
``measurement_environment`` block whose ``label`` is ``reference`` only when the
machine matches the approved reference profile and ``advisory`` otherwise. The
label and ``is_reference_profile`` are derived exclusively from the profile
constant table in this module — never hand-written — so an 8 GB host can never
certify the 32 GB reference profile.

``build_measurement_environment()`` detects the real machine with the standard
library only (darwin via ``sysctl`` and ``mount``, linux via ``/proc`` and GNU
``stat``) and fails explicitly on any other platform instead of guessing. QA
injects a mapping to simulate both profiles deterministically.
"""

import json
from collections.abc import Mapping

from evaltools.envreport_probe import (
    REFERENCE_PROFILE,
    detect_environment,
    matches_reference_profile,
)

_LABEL_REFERENCE = "reference"
_LABEL_ADVISORY = "advisory"

# Detected/injected fields of the §3.8 block; ``label`` and
# ``is_reference_profile`` are always computed here, never accepted from input.
_DETECTED_FIELDS: tuple[str, ...] = (
    "cpu_model",
    "os",
    "os_version",
    "filesystem",
    "cpu_cores",
    "ram_gb",
    "python_version",
)
_TEXT_FIELDS: tuple[str, ...] = (
    "cpu_model",
    "os",
    "os_version",
    "filesystem",
    "python_version",
)

_ARTIFACT_NAME = "measurement_environment"


def measurement_environment_label(ram_gb: int, cpu_cores: int) -> str:
    """Return the profile-table label for a RAM/CPU pair.

    Only the exact reference pair (32 GB, 8 cores) qualifies; every other
    combination — above all ``ram_gb == 8`` — is ``advisory`` (FR-11, AC-9).
    """
    checked_ram_gb = _require_positive_int(ram_gb, "ram_gb", _ARTIFACT_NAME)
    checked_cpu_cores = _require_positive_int(cpu_cores, "cpu_cores", _ARTIFACT_NAME)
    if (
        checked_ram_gb == REFERENCE_PROFILE["ram_gb"]
        and checked_cpu_cores == REFERENCE_PROFILE["cpu_cores"]
    ):
        return _LABEL_REFERENCE
    return _LABEL_ADVISORY


def build_measurement_environment(
    environment: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the complete §3.8 block, either from the detected machine or from
    an injected mapping (QA uses injection to simulate both profiles).

    An injected mapping must supply exactly the seven detected fields; the
    ``label``/``is_reference_profile`` pair is always computed here. A mapping
    that matches the reference RAM/CPU pair but diverges from any other
    constrained profile constant (OS, filesystem, Apple-Silicon CPU, Python
    3.12) is downgraded to ``advisory`` — FR-11 requires the full profile.
    """
    if environment is None:
        detected: Mapping[str, object] = detect_environment()
    else:
        if not isinstance(environment, Mapping):
            raise ValueError(
                f"{_ARTIFACT_NAME}: injected environment must be a Mapping, "
                f"found {type(environment).__name__}"
            )
        unknown_fields = sorted(set(environment) - set(_DETECTED_FIELDS))
        if unknown_fields:
            raise ValueError(
                f"{_ARTIFACT_NAME}: unknown injected fields {unknown_fields}; "
                f"expected exactly {list(_DETECTED_FIELDS)}"
            )
        missing_fields = [name for name in _DETECTED_FIELDS if name not in environment]
        if missing_fields:
            raise ValueError(
                f"{_ARTIFACT_NAME}: missing injected fields {missing_fields}; "
                f"expected exactly {list(_DETECTED_FIELDS)}"
            )
        detected = environment
    cpu_cores = _require_positive_int(
        detected["cpu_cores"], "cpu_cores", _ARTIFACT_NAME
    )
    ram_gb = _require_positive_int(detected["ram_gb"], "ram_gb", _ARTIFACT_NAME)
    text_values = {
        name: _require_non_empty_str(detected[name], name, _ARTIFACT_NAME)
        for name in _TEXT_FIELDS
    }
    label = measurement_environment_label(ram_gb, cpu_cores)
    is_reference_profile = label == _LABEL_REFERENCE and matches_reference_profile(
        text_values["cpu_model"],
        text_values["os"],
        text_values["filesystem"],
        text_values["python_version"],
    )
    if not is_reference_profile:
        label = _LABEL_ADVISORY
    return {
        "cpu_model": text_values["cpu_model"],
        "os": text_values["os"],
        "os_version": text_values["os_version"],
        "filesystem": text_values["filesystem"],
        "cpu_cores": cpu_cores,
        "ram_gb": ram_gb,
        "python_version": text_values["python_version"],
        "is_reference_profile": is_reference_profile,
        "label": label,
    }


def _require_positive_int(value: object, field: str, artifact: str) -> int:
    """Strictly convert a boundary value to a positive int (bools rejected)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{artifact}.{field} must be an int, found {value!r}"
            f" ({type(value).__name__})"
        )
    if value <= 0:
        raise ValueError(f"{artifact}.{field} must be positive, found {value!r}")
    return value


def _require_non_empty_str(value: object, field: str, artifact: str) -> str:
    """Strictly require a non-empty string at the boundary (no coercion)."""
    if not isinstance(value, str):
        raise ValueError(
            f"{artifact}.{field} must be a string, found {value!r}"
            f" ({type(value).__name__})"
        )
    if not value.strip():
        raise ValueError(f"{artifact}.{field} must be non-empty, found {value!r}")
    return value


if __name__ == "__main__":
    print(json.dumps(build_measurement_environment(), indent=2, sort_keys=True))
