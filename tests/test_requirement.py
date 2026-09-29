"""Requirement normalisation. Expected strings were captured from Bundler 1.17.2 (RubyGems 3.0.3)."""

from __future__ import annotations

import pytest

import gemfile
from gemfile._requirement import (
    AmbiguousOrder,
    BadRequirementError,
    format_requirements,
    normalize_requirements,
)


def norm(*items: str) -> str:
    return ", ".join(format_requirements(normalize_requirements(list(items))))


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ((), ">= 0"),
        (("1.0",), "= 1.0"),
        (("< 2", "1.0-beta", ">= 0.5"), ">= 0.5, = 1.0.pre.beta, < 2"),
        (("~>1.0.0", " >=  2  "), "~> 1.0.0, >= 2"),
        (("1.0", "1.0"), "= 1.0"),
        (("1.0", "= 1.0"), "= 1.0, = 1.0"),
        ((">= 0",), ">= 0"),
        (("~> 2.0", ">= 2.0.3"), "~> 2.0, >= 2.0.3"),
        (("> 1.0.a", "< 2.0.pre"), "> 1.0.a, < 2.0.pre"),
        (("!= 1.5",), "!= 1.5"),
    ],
)
def test_normalisation_matches_rubygems(given: tuple[str, ...], expected: str) -> None:
    assert norm(*given) == expected


def test_sorting_orders_by_version_then_operator() -> None:
    assert norm("< 3", ">= 1", "= 2") == ">= 1, = 2, < 3"
    assert norm("> 1", ">= 1", "< 1") == "< 1, > 1, >= 1"


@pytest.mark.parametrize("bad", ["", ">> 1", "~> ", "v1.0", "1..0", "1.0 2"])
def test_malformed_requirements_raise(bad: str) -> None:
    with pytest.raises(BadRequirementError):
        normalize_requirements([bad])


def test_ties_between_differently_spelled_versions_are_refused() -> None:
    # RubyGems' sort order for these is not defined, so the reader declines them.
    with pytest.raises(AmbiguousOrder):
        normalize_requirements(["5", "5.0", "5.0.0"])
    assert norm("5", "5.0") == "= 5, = 5.0"


def test_reader_reports_a_declined_tie_as_unsupported() -> None:
    result = gemfile.parse("gem 'a', '5', '5.0', '5.0.0'\n", strict=False)
    assert [d.kind for d in result.diagnostics] == ["unsupported"]
    assert result.dependencies == ()
