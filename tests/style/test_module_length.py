"""Fixture tests for rule 8: the 250-code-line module limit.

Both directions are exercised — a module at the limit passes, one over the
limit fails — plus the exclusion of blank lines and comment-only lines and the
CLI exit code that makes the rule enforceable.
"""

from pathlib import Path

import pytest

from tools.check_module_length import (
    MAX_MODULE_CODE_LINES,
    check_file,
    check_text,
    count_code_lines,
    iter_python_files,
    main,
    run,
)


def code_block(count: int) -> str:
    """Return ``count`` lines of Python code, with no blanks or comments."""
    return "\n".join(f"value_{index} = {index}" for index in range(count)) + "\n"


def test_module_at_the_limit_is_allowed(tmp_path: Path) -> None:
    text = code_block(MAX_MODULE_CODE_LINES)
    assert count_code_lines(text) == MAX_MODULE_CODE_LINES
    target = tmp_path / "module.py"
    target.write_text(text, encoding="utf-8")
    assert check_file(target) is None


def test_module_over_the_limit_is_reported(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_text(code_block(MAX_MODULE_CODE_LINES + 1), encoding="utf-8")
    message = check_file(target)
    assert message is not None
    assert "[rule-8-max-module-lines]" in message
    assert f"{MAX_MODULE_CODE_LINES + 1} code lines > {MAX_MODULE_CODE_LINES}" in (
        message
    )


def test_comments_and_blank_lines_are_not_counted() -> None:
    text = code_block(MAX_MODULE_CODE_LINES) + "\n# a comment\n\t# indented comment\n"
    assert count_code_lines(text) == MAX_MODULE_CODE_LINES
    assert check_text(text, Path("module.py")) is None


def test_docstring_and_multiline_string_lines_are_code() -> None:
    text = '"""One\n\nTwo\n"""\nx = 1\n'
    # Five physical lines; the blank line inside the docstring is not a blank
    # line of code, so only the truly empty line is excluded.
    assert count_code_lines(text) == 4


def test_cli_exits_zero_on_a_compliant_module(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "good.py"
    target.write_text(code_block(3), encoding="utf-8")
    assert main([str(target)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""


def test_cli_exits_non_zero_on_a_violating_module(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "bad.py"
    target.write_text(code_block(MAX_MODULE_CODE_LINES + 1), encoding="utf-8")
    assert main([str(target)]) == 1
    assert "rule-8-max-module-lines" in capsys.readouterr().out


def test_generated_trees_are_skipped(tmp_path: Path) -> None:
    generated = tmp_path / "corpora" / "bad.py"
    generated.parent.mkdir()
    generated.write_text(code_block(MAX_MODULE_CODE_LINES + 1), encoding="utf-8")
    kept = tmp_path / "kept.py"
    kept.write_text(code_block(2), encoding="utf-8")
    assert list(iter_python_files([tmp_path])) == [kept]
    assert run([tmp_path]) == []
