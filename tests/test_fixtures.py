"""Hand-written fixtures. Expected output for each was captured from Bundler 1.17.2."""

from __future__ import annotations

import json
from pathlib import Path

import oraclelib
import pytest

import gemfile

FIXTURES = Path(__file__).parent / "fixtures"

# The reader returns a complete answer and it equals the oracle's.
STATIC = [
    "basic", "crlf", "custom_git_source", "data_section", "duplicates", "env_install_if",
    "gemspec_calls", "git_sources", "groups", "literals", "path_sources", "platforms",
    "plugin_call", "rails_app", "require_option", "requirements", "ruby_directive",
    "ruby_engine", "sources",
]
# The reader declines: the lines it reports as unsupported (checked by hand).
DYNAMIC = {
    "dynamic_env": [2],
    "dynamic_eval_gemfile": [2],
    "dynamic_if": [2, 6],
    "dynamic_install_if": [1],
    "dynamic_interp": [1, 2, 3],
}
# Bundler itself raises, and so does the reader.
INVALID = {
    "invalid_branch": 1,
    "invalid_duplicate": 2,
    "invalid_group_block": 1,
    "invalid_option": 1,
    "invalid_platform": 1,
    "invalid_requirement": 1,
}


def load(name: str) -> tuple[str, dict[str, object]]:
    text = (FIXTURES / f"{name}.Gemfile").read_bytes().decode()
    expected: dict[str, object] = json.loads((FIXTURES / f"{name}.expected.json").read_text())
    return text, expected


def test_every_fixture_is_classified() -> None:
    on_disk = {p.name.removesuffix(".Gemfile") for p in FIXTURES.glob("*.Gemfile")}
    assert on_disk == set(STATIC) | set(DYNAMIC) | set(INVALID)


@pytest.mark.parametrize("name", STATIC)
def test_static_fixture_equals_oracle(name: str) -> None:
    text, expected = load(name)
    assert expected["ok"] is True
    result = oraclelib.reader_result(text)
    assert result.diagnostics == ()
    assert result.is_static
    assert oraclelib.mismatches(result, expected) == []
    assert len(result.dependencies) == len(expected["dependencies"])  # type: ignore[arg-type]


@pytest.mark.parametrize("name", sorted(DYNAMIC))
def test_dynamic_fixture_is_declined(name: str) -> None:
    text, _ = load(name)
    result = oraclelib.reader_result(text)
    assert [d.line for d in result.diagnostics] == DYNAMIC[name]
    assert {d.kind for d in result.diagnostics} == {"unsupported"}
    assert not result.is_static
    with pytest.raises(gemfile.GemfileError) as info:
        gemfile.parse(text, bundler="1.17")
    assert f"line {DYNAMIC[name][0]}" in str(info.value)
    assert info.value.diagnostics == result.diagnostics


@pytest.mark.parametrize("name", sorted(INVALID))
def test_invalid_fixture_matches_oracle_error(name: str) -> None:
    text, expected = load(name)
    assert expected["ok"] is False
    result = oraclelib.reader_result(text)
    assert [(d.line, d.kind) for d in result.diagnostics] == [(INVALID[name], "invalid")]
    with pytest.raises(gemfile.GemfileError, match="invalid Gemfile at line"):
        gemfile.parse(text, bundler="1.17")


def test_lenient_mode_keeps_the_static_statements_of_a_dynamic_file() -> None:
    text, expected = load("dynamic_if")
    result = oraclelib.reader_result(text)
    assert [d.name for d in result.dependencies] == ["before", "after"]
    oracle_names = [d["name"] for d in expected["dependencies"]]  # type: ignore[attr-defined]
    assert oracle_names == ["before", "inside-if", "after", "modifier"]


def test_mode_2_differs_from_1_17_only_in_the_github_shorthand() -> None:
    text, _ = load("git_sources")
    old = gemfile.parse(text, bundler="1.17")
    new = gemfile.parse(text.replace("gist: '12345'", "github: 'x/5'").replace(
        "bitbucket: 'acme/g6'", "github: 'x/6'").replace("bitbucket: 'solo'", "github: 'x/7'"),
        bundler="2")
    changed = [a.name for a, b in zip(old.dependencies, new.dependencies) if a.source != b.source]
    assert changed == ["g3", "g4", "g5", "g6", "g7", "g11", "n1", "n2"]
    assert new.dependencies[2].source == gemfile.GitSource(
        uri="https://github.com/acme/g3.git", tag="v1.2.3"
    )
    assert old.dependencies[2].source == gemfile.GitSource(
        uri="git://github.com/acme/g3.git", tag="v1.2.3"
    )


def test_comparison_detects_a_wrong_answer() -> None:
    """Negative control: the comparator must fail when the reader is wrong."""
    text, expected = load("basic")
    result = oraclelib.reader_result(text)
    assert oraclelib.mismatches(result, expected) == []
    tampered = json.loads(json.dumps(expected))
    tampered["dependencies"][0]["requirement"] = "~> 7.1"
    tampered["dependencies"][3]["groups"] = ["test"]
    tampered["sources"] = []
    assert oraclelib.mismatches(result, tampered) == ["sources", "dep.requirement", "dep.groups"]
