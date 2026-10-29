"""Connection-config redaction seam (Contract ir-boundary §6, owner: security).

Phase-1 minimal skeleton. Three active redaction classes, all driven by the
single module-level pattern table ``REDACTION_PATTERNS``:

- ``secret_key_value``  — values under secret-bearing key names (case-
  insensitive) become ``REDACTION_PLACEHOLDER``, recursively through nested
  mappings and lists.
- ``uri_userinfo``      — ``user:password`` credentials in a Redis URI
  authority (``scheme://user:password@host``) become the placeholder while
  the rest of the URI is preserved.
- ``uri_query_secret``  — secret-bearing query parameters
  (``?password=...&keep=1``) have only their value replaced.

Properties: pure (never mutates its input), idempotent (placeholders never
re-match into different output), never raises on mapping *content*, and
raises ``TypeError`` on a non-mapping argument (fail fast on contract
misuse). Unknown value types (bytes, tuples, custom objects) are preserved
as-is and counted in the stats of ``redact_conn_config_with_stats``.
"""

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote

REDACTION_PLACEHOLDER = "<REDACTED>"

# Case-insensitive secret-bearing key names (exact match after lowercasing).
SECRET_KEY_NAMES = frozenset({
    "password",
    "pass",
    "pwd",
    "auth",
    "auth_pass",
    "secret",
    "token",
    "credential",
    "api_key",
    "secret_key",
})

# Authority credentials: scheme://user:password@ — only the password is
# replaced, so a second pass (password already the placeholder) is a no-op.
_URI_USERINFO_PATTERN = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)"
    r"(?P<user>[^:/?#]*):"
    r"(?P<password>[^@/?#]*)@"
)

# One key=value pair inside a URI query string; the callback decides per pair.
_URI_QUERY_PAIR_PATTERN = re.compile(
    r"(?P<separator>[?&])(?P<name>[^&=]+)=(?P<value>[^&]*)"
)

# Single pattern table driving every redaction class. The stats key set is
# derived from it, so adding a class here extends the surface in one place.
REDACTION_PATTERNS: dict[str, Any] = {
    "secret_key_value": SECRET_KEY_NAMES,
    "uri_userinfo": _URI_USERINFO_PATTERN,
    "uri_query_secret": _URI_QUERY_PAIR_PATTERN,
}

# Values that are JSON-native scalars: preserved without counting as unknown.
_JSON_SCALAR_TYPES = (str, bool, int, float, type(None))


def redact_conn_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a redacted copy of ``config`` (see module docstring)."""
    redacted_config, _redaction_stats = redact_conn_config_with_stats(config)
    return redacted_config


def redact_conn_config_with_stats(
    config: Mapping[str, Any],
) -> tuple[Mapping[str, Any], dict[str, Any]]:
    """Redact ``config`` and return ``(redacted_copy, stats)``.

    ``stats`` is JSON-serializable:
    ``{"classes_applied": {<class name>: count, ...},
    "unknown_value_types_preserved": count}``.
    """
    if not isinstance(config, Mapping):
        raise TypeError(
            f"redact_conn_config expects a Mapping, got {type(config).__name__}"
        )
    stats: dict[str, Any] = {
        "classes_applied": dict.fromkeys(REDACTION_PATTERNS, 0),
        "unknown_value_types_preserved": 0,
    }
    return _redact_mapping(config, stats), stats


def _redact_mapping(
    mapping: Mapping[Any, Any], stats: dict[str, Any]
) -> dict[Any, Any]:
    return {key: _redact_value(key, value, stats) for key, value in mapping.items()}


def _secret_key_name(key: Any) -> str:
    return key.lower() if isinstance(key, str) else ""


def _redact_value(key: Any, value: Any, stats: dict[str, Any]) -> Any:
    if isinstance(value, Mapping):
        return _redact_mapping(value, stats)
    if isinstance(value, list):
        return [_redact_value(key, item, stats) for item in value]
    if _secret_key_name(key) in REDACTION_PATTERNS["secret_key_value"]:
        stats["classes_applied"]["secret_key_value"] += 1
        return REDACTION_PLACEHOLDER
    if isinstance(value, str):
        redacted_value = _redact_uri_userinfo(value, stats)
        return _redact_uri_query(redacted_value, stats)
    if not isinstance(value, _JSON_SCALAR_TYPES):
        stats["unknown_value_types_preserved"] += 1
    return value


def _redact_uri_userinfo(value: str, stats: dict[str, Any]) -> str:
    pattern = REDACTION_PATTERNS["uri_userinfo"]

    def _replace(match: re.Match[str]) -> str:
        stats["classes_applied"]["uri_userinfo"] += 1
        return f"{match.group('scheme')}{match.group('user')}:{REDACTION_PLACEHOLDER}@"

    return pattern.sub(_replace, value)


def _redact_uri_query(value: str, stats: dict[str, Any]) -> str:
    scheme_index = value.find("://")
    query_index = value.find("?")
    if scheme_index == -1 or query_index == -1 or query_index < scheme_index:
        return value
    uri_without_query = value[:query_index]
    query = value[query_index:]
    secret_key_names = REDACTION_PATTERNS["secret_key_value"]

    def _replace(match: re.Match[str]) -> str:
        parameter_name = unquote(match.group("name")).lower()
        if parameter_name not in secret_key_names:
            return match.group(0)
        stats["classes_applied"]["uri_query_secret"] += 1
        return (
            f"{match.group('separator')}{match.group('name')}={REDACTION_PLACEHOLDER}"
        )

    return uri_without_query + REDACTION_PATTERNS["uri_query_secret"].sub(
        _replace, query
    )
