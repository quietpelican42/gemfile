"""Static reader for Ruby Gemfiles that returns what Bundler's DSL would produce."""

from __future__ import annotations

from pathlib import Path

from ._eval import BundlerMode, Evaluator
from ._parser import parse_source
from .model import (
    Dependency,
    Diagnostic,
    Gemfile,
    GemfileError,
    Gemspec,
    GitSource,
    PathSource,
    RubyDirective,
    RubygemsSource,
    Source,
)

__all__ = [
    "Dependency",
    "Diagnostic",
    "Gemfile",
    "GemfileError",
    "Gemspec",
    "GitSource",
    "PathSource",
    "RubyDirective",
    "RubygemsSource",
    "Source",
    "parse",
    "parse_file",
]


def parse(text: str, *, strict: bool = True, bundler: BundlerMode = "2") -> Gemfile:
    """Read the Gemfile in ``text`` without running Ruby.

    Strict mode (the default) raises :class:`GemfileError` when any statement
    cannot be evaluated statically or is rejected by Bundler. Lenient mode skips
    those statements and lists them in ``Gemfile.diagnostics``.

    ``bundler`` selects how the built-in ``github:`` shorthand expands:
    ``"1.17"`` gives ``git://github.com/...`` and keeps the ``gist`` and
    ``bitbucket`` shorthands, ``"2"`` gives ``https://github.com/...``.
    """
    if bundler not in ("1.17", "2"):
        raise ValueError(f"unknown bundler mode {bundler!r}; use '1.17' or '2'")
    too_deep = Diagnostic(1, "unsupported", "nesting is too deep to read")
    dead: set[str] = set()
    try:
        calls, parse_diags, dead = parse_source(text)
    except RecursionError:
        calls, parse_diags = [], [too_deep]
    ev = Evaluator(bundler, dead)
    try:
        ev.run(calls)
    except RecursionError:
        ev = Evaluator(bundler, dead)
        parse_diags = [*parse_diags, too_deep]
    diags = sorted([*parse_diags, *ev.diags], key=lambda d: d.line)
    if strict and diags:
        raise GemfileError(tuple(diags))
    return Gemfile(
        sources=tuple(ev.sources),
        ruby=ev.ruby,
        gemspecs=tuple(ev.gemspecs),
        plugins=tuple(ev.plugins),
        optional_groups=tuple(
            g if isinstance(g, str) else getattr(g, "name", str(g)) for g in ev.optional_groups
        ),
        dependencies=tuple(ev.dependencies),
        diagnostics=tuple(diags),
    )


def parse_file(path: str | Path, *, strict: bool = True, bundler: BundlerMode = "2") -> Gemfile:
    """Read a Gemfile from disk. The file must be UTF-8."""
    text = Path(path).read_bytes().decode("utf-8")
    return parse(text, strict=strict, bundler=bundler)
