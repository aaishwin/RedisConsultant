"""Platform probes backing the computed ``measurement_environment`` block.

Kept separate from :mod:`evaltools.envreport` so each module stays inside the
repository's 250-code-line limit (style contract rule 8). Detection is
standard-library only: darwin via ``sysctl``/``mount``, linux via ``/proc`` and
GNU ``stat``; unsupported platforms fail explicitly instead of guessing.
"""

import os
import platform
import subprocess  # noqa: S404  (reads host facts for the environment block)

# Approved reference hardware profile (requirements FR-11; Contract 2 §3.8):
# 8 performance cores, 32 GB RAM, Apple-Silicon Python 3.12, APFS.
# ``cpu_model`` and ``os_version`` are recorded in the block but not
# constrained: Apple brand strings (M1/M2/M3...) and macOS point releases vary
# within the profile. ``cpu_model`` is matched as a case-insensitive substring
# so Intel Macs can never reach ``reference``.
REFERENCE_PROFILE: dict[str, str | int | None] = {
    "cpu_model": "apple",
    "os": "Darwin",
    "os_version": None,
    "filesystem": "apfs",
    "cpu_cores": 8,
    "ram_gb": 32,
    "python_version": "3.12",
}

_GIBIBYTE = 1024**3


def detect_environment() -> dict[str, object]:
    """Detect the real machine values; unsupported platforms fail explicitly."""
    system = platform.system()
    if system == "Darwin":
        cpu_model = run_command(
            ["sysctl", "-n", "machdep.cpu.brand_string"], "CPU model"
        ).strip()
        ram_bytes = run_int_command(["sysctl", "-n", "hw.memsize"], "total RAM")
        filesystem = darwin_filesystem_type(os.getcwd())
    elif system == "Linux":
        cpu_model = linux_cpu_model()
        ram_bytes = linux_ram_bytes()
        filesystem = run_command(
            ["stat", "-f", "-c", "%T", os.getcwd()], "filesystem type"
        ).strip()
    else:
        raise RuntimeError(
            f"unsupported platform {system!r} for measurement_environment "
            "detection: only darwin and linux are implemented; refusing to "
            "guess machine values"
        )
    cpu_cores = os.cpu_count()
    if cpu_cores is None:
        raise RuntimeError(
            "os.cpu_count() returned None; cannot record cpu_cores honestly"
        )
    return {
        "cpu_model": cpu_model,
        "os": system,
        "os_version": platform.release(),
        "filesystem": filesystem,
        "cpu_cores": cpu_cores,
        "ram_gb": round(ram_bytes / _GIBIBYTE),
        "python_version": platform.python_version(),
    }


def run_command(arguments: list[str], purpose: str) -> str:
    """Run a detection command, failing fast with the purpose named on error."""
    try:
        completed = subprocess.run(
            arguments, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise RuntimeError(
            f"cannot determine {purpose} via {' '.join(arguments)}: {error}"
        ) from error
    return completed.stdout


def run_int_command(arguments: list[str], purpose: str) -> int:
    """Run a detection command whose stdout must be a single integer."""
    output = run_command(arguments, purpose)
    try:
        return int(output.strip())
    except ValueError as error:
        raise RuntimeError(
            f"{arguments[0]} returned a non-integer value for {purpose}: {output!r}"
        ) from error


def darwin_filesystem_type(target_directory: str) -> str:
    """Return the filesystem type of the volume holding ``target_directory``.

    BSD ``stat`` has no filesystem-type field, so the ``mount`` table is parsed
    and the entry whose mount point is the longest prefix of the target wins.
    """
    best_type: str | None = None
    best_prefix_length = -1
    for line in run_command(["mount"], "filesystem type").splitlines():
        mount_point, filesystem_type = parse_darwin_mount_line(line)
        if not directory_is_on_mount_point(target_directory, mount_point):
            continue
        if len(mount_point) > best_prefix_length:
            best_prefix_length = len(mount_point)
            best_type = filesystem_type
    if best_type is None:
        raise RuntimeError(
            f"no mount point covers {target_directory!r}; cannot record "
            "filesystem honestly"
        )
    return best_type


def parse_darwin_mount_line(line: str) -> tuple[str, str]:
    """Parse one ``mount`` output line: ``SOURCE on MOUNT (TYPE, options...)``."""
    source_separator_index = line.find(" on ")
    mount_options_separator_index = line.rfind(" (")
    if (
        source_separator_index < 0
        or mount_options_separator_index < source_separator_index
    ):
        raise RuntimeError(f"unrecognized mount line: {line!r}")
    mount_point = line[source_separator_index + 4 : mount_options_separator_index]
    filesystem_type = (
        line[mount_options_separator_index + 2 :].split(",", 1)[0].strip().lower()
    )
    if not mount_point or not filesystem_type:
        raise RuntimeError(f"unrecognized mount line: {line!r}")
    return mount_point, filesystem_type


def directory_is_on_mount_point(directory: str, mount_point: str) -> bool:
    """Return True when ``directory`` lies on the volume mounted at ``mount_point``."""
    if directory == mount_point:
        return True
    prefix = mount_point.rstrip("/")
    return directory.startswith(prefix + "/") if prefix else directory.startswith("/")


def linux_cpu_model() -> str:
    """Return the first ``model name`` entry from ``/proc/cpuinfo``."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                key, separator, value = line.partition(":")
                if separator and key.strip() == "model name":
                    return value.strip()
    except OSError as error:
        raise RuntimeError(
            f"cannot read /proc/cpuinfo for the CPU model: {error}"
        ) from error
    raise RuntimeError("no 'model name' entry found in /proc/cpuinfo")


def linux_ram_bytes() -> int:
    """Return total RAM in bytes from ``/proc/meminfo`` (``MemTotal`` in KiB)."""
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, separator, value = line.partition(":")
                if separator and key.strip() == "MemTotal":
                    return int(value.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError) as error:
        raise RuntimeError(
            f"cannot read total RAM from /proc/meminfo: {error}"
        ) from error
    raise RuntimeError("no 'MemTotal' entry found in /proc/meminfo")


def matches_reference_profile(
    cpu_model: str, operating_system: str, filesystem: str, python_version: str
) -> bool:
    """Compare the constrained profile constants against validated field values."""
    profile_cpu_model_fragment = str(REFERENCE_PROFILE["cpu_model"]).lower()
    if profile_cpu_model_fragment not in cpu_model.lower():
        return False
    if operating_system != REFERENCE_PROFILE["os"]:
        return False
    if filesystem.lower() != REFERENCE_PROFILE["filesystem"]:
        return False
    python_major_minor = ".".join(python_version.split(".")[:2])
    return python_major_minor == str(REFERENCE_PROFILE["python_version"])
