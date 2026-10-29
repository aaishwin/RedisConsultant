"""AC-18 (FR-13, NFR-3): exact parser pins, no language pack, no runtime downloads."""

import socket
import tomllib

import pytest
from qa_support import REPO_ROOT

from redis_intel.frontend import LanguageFrontend
from redis_intel.frontend.grammar_registry import resolved_core_grammar_version

PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
UV_LOCK_PATH = REPO_ROOT / "uv.lock"
EXPECTED_PINS = {
    "tree-sitter": "0.23.2",
    "tree-sitter-typescript": "0.23.2",
    "tree-sitter-javascript": "0.23.1",
}
FORBIDDEN_PACKAGE = "tree-sitter-language-pack"


def test_pyproject_declares_exactly_the_three_parser_pins() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    parser_dependencies = [dep for dep in dependencies if dep.startswith("tree-sitter")]
    assert len(parser_dependencies) == 3, parser_dependencies
    for package_name, version in EXPECTED_PINS.items():
        assert f"{package_name}=={version}" in dependencies, (
            f"missing exact pin {package_name}=={version}"
        )
    assert not any(FORBIDDEN_PACKAGE in dep for dep in dependencies)


def test_uv_lock_resolves_the_pinned_versions_without_the_language_pack() -> None:
    lock_text = UV_LOCK_PATH.read_text(encoding="utf-8")
    assert FORBIDDEN_PACKAGE not in lock_text, (
        "tree-sitter-language-pack must not appear anywhere in the dependency tree"
    )
    for package_name, version in EXPECTED_PINS.items():
        package_block = f'name = "{package_name}"\nversion = "{version}"'
        assert package_block in lock_text, (
            f"uv.lock does not pin {package_name} at {version}"
        )


@pytest.fixture()
def no_network_socket_guard(monkeypatch: pytest.MonkeyPatch) -> bool:
    """Fail the test if any code path tries to open a socket (AC-18)."""

    def forbidden_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted during pinned-grammar parse")

    monkeypatch.setattr(socket, "socket", forbidden_socket)
    monkeypatch.setattr(socket, "create_connection", forbidden_socket)
    return True


def test_parsing_each_grammar_requires_no_network(
    no_network_socket_guard: bool,
) -> None:
    frontend = LanguageFrontend()
    sources = {
        "pins.ts": b"const pinned: number = 1;\n",
        "pins.tsx": b'export const node = <div className="k" />;\n',
        "pins.js": b"const pinned = 1;\n",
    }
    for path, source in sources.items():
        parse_result = frontend.parse(path, source)
        assert parse_result.tree is not None
        assert parse_result.grammar_version == resolved_core_grammar_version()
        assert not parse_result.unresolved
