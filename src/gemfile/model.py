"""Result types returned by :func:`gemfile.parse`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RubygemsSource:
    """A gem server, from a ``source`` block or a ``source:`` option."""

    remotes: tuple[str, ...]
    kind: str = field(default="rubygems", init=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "rubygems", "remotes": list(self.remotes)}


@dataclass(frozen=True)
class GitSource:
    """A git repository, from ``git:``, a ``git_source`` shorthand or a ``git`` block.

    ``branch``, ``tag``, ``ref``, ``submodules`` and ``glob`` are reported
    as written in the Gemfile; ``None`` means the option was absent.
    """

    uri: str
    branch: str | None = None
    tag: str | None = None
    ref: str | None = None
    submodules: bool | None = None
    glob: str | None = None
    kind: str = field(default="git", init=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "git",
            "uri": self.uri,
            "branch": self.branch,
            "tag": self.tag,
            "ref": self.ref,
            "submodules": self.submodules,
            "glob": self.glob,
        }


@dataclass(frozen=True)
class PathSource:
    """A local directory, from ``path:`` or a ``path`` block."""

    path: str
    glob: str | None = None
    kind: str = field(default="path", init=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "path", "path": self.path, "glob": self.glob}


Source = RubygemsSource | GitSource | PathSource


@dataclass(frozen=True)
class Dependency:
    """One ``gem`` call, after Bundler's option handling."""

    name: str
    requirements: tuple[str, ...]
    groups: tuple[str, ...]
    platforms: tuple[str, ...]
    source: Source | None
    autorequire: tuple[str | bool, ...] | None
    type: str = "runtime"
    env: str | None = None
    install_if: bool = True
    force_ruby_platform: bool | None = None
    line: int = 0

    @property
    def requirement(self) -> str:
        """Bundler's normalised requirement string, e.g. ``"~> 7.0, >= 7.0.1"``."""
        return ", ".join(self.requirements)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "requirement": self.requirement,
            "requirements": list(self.requirements),
            "groups": list(self.groups),
            "platforms": list(self.platforms),
            "source": self.source.to_dict() if self.source else None,
            "autorequire": None if self.autorequire is None else list(self.autorequire),
            "type": self.type,
            "env": self.env,
            "install_if": self.install_if,
            "force_ruby_platform": self.force_ruby_platform,
            "line": self.line,
        }


@dataclass(frozen=True)
class Gemspec:
    """A ``gemspec`` call. Reported, never evaluated."""

    line: int
    path: str = "."
    glob: str | None = None
    name: str | None = None
    development_group: str = "development"

    def to_dict(self) -> dict[str, Any]:
        return {
            "line": self.line,
            "path": self.path,
            "glob": self.glob,
            "name": self.name,
            "development_group": self.development_group,
        }


@dataclass(frozen=True)
class RubyDirective:
    """The ``ruby`` directive."""

    line: int
    versions: tuple[str, ...]
    engine: str
    engine_versions: tuple[str, ...]
    patchlevel: str | int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "line": self.line,
            "versions": list(self.versions),
            "engine": self.engine,
            "engine_versions": list(self.engine_versions),
            "patchlevel": self.patchlevel,
        }


@dataclass(frozen=True)
class Diagnostic:
    """A construct that was not evaluated (``unsupported``) or that Bundler rejects (``invalid``)."""

    line: int
    kind: str
    message: str
    text: str = ""

    def __str__(self) -> str:
        if self.kind == "invalid":
            head = f"invalid Gemfile at line {self.line}"
        else:
            head = f"unsupported construct at line {self.line}"
        return f"{head}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {"line": self.line, "kind": self.kind, "message": self.message, "text": self.text}


@dataclass(frozen=True)
class Gemfile:
    """Everything the reader could determine about a Gemfile."""

    sources: tuple[str, ...] = ()
    ruby: RubyDirective | None = None
    gemspecs: tuple[Gemspec, ...] = ()
    plugins: tuple[str, ...] = ()
    optional_groups: tuple[str, ...] = ()
    dependencies: tuple[Dependency, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def is_static(self) -> bool:
        """True when nothing was skipped, so the result is complete."""
        return not self.diagnostics

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": list(self.sources),
            "ruby": self.ruby.to_dict() if self.ruby else None,
            "gemspecs": [g.to_dict() for g in self.gemspecs],
            "plugins": list(self.plugins),
            "optional_groups": list(self.optional_groups),
            "dependencies": [d.to_dict() for d in self.dependencies],
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


class GemfileError(ValueError):
    """Raised in strict mode when a Gemfile has any diagnostic."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        extra = f" (and {len(diagnostics) - 1} more)" if len(diagnostics) > 1 else ""
        super().__init__(f"{diagnostics[0]}{extra}")
