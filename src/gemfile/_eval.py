"""Evaluate parsed DSL calls the way Bundler 1.17's ``Bundler::Dsl`` does."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import Literal

from ._parser import Block, Call, HashLit, Sym, Template
from ._requirement import (
    AmbiguousOrder,
    BadRequirementError,
    format_requirements,
    normalize_requirements,
    parse_requirement,
    requirements_equal,
)
from .model import (
    Dependency,
    Diagnostic,
    Gemspec,
    GitSource,
    PathSource,
    RubyDirective,
    RubygemsSource,
    Source,
)

BundlerMode = Literal["1.17", "2"]

VALID_PLATFORMS = frozenset(
    ["ruby", "mri", "rbx", "truffleruby", "jruby", "jruby_18", "jruby_19", "mswin", "mswin64",
     "mingw", "x64_mingw"]
    + [f"ruby_{v}" for v in (18, 19, 20, 21, 22, 23, 24, 25)]
    + [f"mri_{v}" for v in (18, 19, 20, 21, 22, 23, 24, 25)]
    + [f"mswin_{v}" for v in (18, 19, 20, 21, 22, 23, 24, 25)]
    + [f"mswin64_{v}" for v in (19, 20, 21, 22, 23, 24, 25)]
    + [f"mingw_{v}" for v in (18, 19, 20, 21, 22, 23, 24, 25)]
    + [f"x64_mingw_{v}" for v in (20, 21, 22, 23, 24, 25)]
)
VALID_KEYS = ("group", "groups", "git", "path", "glob", "name", "branch", "ref", "tag", "require",
              "submodules", "platform", "platforms", "type", "source", "install_if", "gemfile")
# Platform names that Bundler 2.x accepts and 1.17 does not. Not verified here.
_NEWER_PLATFORM = re.compile(r"^(windows|(ruby|mri|mswin|mingw|x64_mingw)_(2[6-9]|3[0-9]))$")
_EXACT_VERSION = re.compile(
    r"\A[ \t\r\f\v]*=?[ \t\r\f\v]*(\d[^ \t\r\n\f\v]*)[ \t\r\f\v]*\Z"
)
_URI = re.compile(
    r"^[A-Za-z][A-Za-z0-9+.-]*://([A-Za-z0-9._~%!$&'()*+,;=:-]*@)?"
    r"[A-Za-z0-9._~%!$&'()*+,;=-]*(:[0-9]*)?(/[A-Za-z0-9._~%!$&'()*+,;=:@/-]*)?$"
)


class Invalid(Exception):
    """Bundler itself would raise here."""


class Skip(Exception):
    """This construct cannot be evaluated statically."""


Value = object


def _truthy(v: Value) -> bool:
    return v is not None and v is not False


def _array(v: Value) -> list[Value]:
    """Kernel#Array for the literal values the parser produces."""
    if v is None:
        return []
    if isinstance(v, list):
        return list(v)
    if isinstance(v, HashLit):
        raise Skip("hash where a list of names was expected")
    return [v]


def _name(v: Value, what: str) -> str:
    """A group or platform name (String or Symbol) as text."""
    if isinstance(v, Sym):
        return v.name
    if isinstance(v, str):
        return v
    raise Skip(f"{what} must be a string or symbol")


def _normalize_uri(text: str) -> str:
    uri = text if text.endswith("/") else text + "/"
    if not _URI.match(uri):
        raise Skip(f"cannot validate source URI {text!r} statically")
    scheme, _, rest = uri.partition("://")
    if scheme.lower() in ("http", "https"):
        hostpart = rest.split("/", 1)[0].rpartition("@")[2].split(":")[0]
        if not hostpart:
            raise Skip(f"cannot validate source URI {text!r} statically")
    return uri


def _credless(remotes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(re.sub(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/@]*@", r"\1", r) for r in remotes)


@dataclass
class _Src:
    """A source plus the data Bundler compares when checking duplicate gems."""

    model: Source
    key: tuple[object, ...]

    def same(self, other: _Src | None) -> bool:
        """Bundler's `==` for two sources."""
        if other is None:
            return False
        a, b = self.model, other.model
        if isinstance(a, RubygemsSource) and isinstance(b, RubygemsSource):
            if a.remotes == b.remotes:
                return True
            if _credless(a.remotes) == _credless(b.remotes):
                # Bundler drops credentials only when `bundle config` holds the same ones.
                raise Skip("comparing gem servers that differ only in credentials depends on bundle config")
            return False
        return self.key == other.key


class _Template:
    def __init__(self, t: Template | None, builtin: str | None, mode: BundlerMode) -> None:
        self.t = t
        self.builtin = builtin
        self.mode = mode

    def call(self, arg: str) -> str:
        if self.t is None:
            return self.call_builtin(arg)
        env = {self.t.param: arg}
        result = ""
        for step in self.t.steps:
            if step.cond is not None:
                has = step.cond_needle in env[step.cond_var]
                run = (not has) if step.cond == "unless" else has
                if not run:
                    continue
            text = "".join(p if isinstance(p, str) else env[p.text.strip()] for p in step.parts)
            if step.target is not None:
                env[step.target] = text
            else:
                result = text
        return result

    def call_builtin(self, repo: str) -> str:
        if self.builtin == "github":
            if "/" not in repo:
                repo = f"{repo}/{repo}"
            scheme = "git" if self.mode == "1.17" else "https"
            return f"{scheme}://github.com/{repo}.git"
        if self.builtin in ("gist", "bitbucket") and self.mode == "2":
            raise Skip(f"the {self.builtin}: shorthand has not been checked against Bundler 2")
        if self.builtin == "gist":
            return f"https://gist.github.com/{repo}.git"
        if self.builtin == "bitbucket":
            parts = repo.split("/")
            while parts and parts[-1] == "":
                parts.pop()
            if not parts:
                raise Skip("bitbucket shorthand with an empty repository name")
            user = parts[0]
            name = parts[1] if len(parts) > 1 else user
            return f"https://{user}@bitbucket.org/{user}/{name}.git"
        raise AssertionError(self.builtin)


class Evaluator:
    def __init__(self, mode: BundlerMode, dead_sources: set[str] | None = None) -> None:
        self.mode = mode
        # git_source names whose definition was skipped; using them cannot be judged
        self.dead_sources: set[str] = set(dead_sources or ())
        self.dependencies: list[Dependency] = []
        self.dep_sources: list[_Src | None] = []
        self.dep_reqs: list[list[tuple[str, str]]] = []
        self.sources: list[str] = []
        self.ruby: RubyDirective | None = None
        self.gemspecs: list[Gemspec] = []
        self.plugins: list[str] = []
        self.optional_groups: list[Value] = []
        self.diags: list[Diagnostic] = []
        self.groups: list[Value] = []
        self.platforms: list[Value] = []
        self.install_conditionals: list[Value] = []
        self.env: str | None = None
        self.source: _Src | None = None
        self.git_sources: dict[str, _Template] = {
            "github": _Template(None, "github", mode),
            "gist": _Template(None, "gist", mode),
            "bitbucket": _Template(None, "bitbucket", mode),
        }

    def valid_keys(self) -> list[str]:
        return list(VALID_KEYS) + (["force_ruby_platform"] if self.mode == "2" else [])

    # -- driver ----------------------------------------------------------
    def run(self, calls: list[Call]) -> None:
        for call in calls:
            self.execute(call)

    def execute(self, call: Call) -> None:
        try:
            getattr(self, "m_" + call.name)(call)
        except Invalid as e:
            self.diags.append(Diagnostic(call.line, "invalid", str(e), call.text))
        except Skip as e:
            self.diags.append(Diagnostic(call.line, "unsupported", str(e), call.text))

    def with_block(self, call: Call) -> Block:
        if call.block is None:
            raise Invalid(f"`{call.name}` needs a block (no block given (yield))")
        return call.block

    # -- argument helpers -------------------------------------------------
    @staticmethod
    def split_options(args: list[Value]) -> tuple[list[Value], HashLit | None]:
        if args and isinstance(args[-1], HashLit):
            return args[:-1], args[-1]
        return list(args), None

    @staticmethod
    def normalize_hash(h: HashLit | None) -> dict[str, Value]:
        """Bundler's normalize_hash: symbol keys become strings and win over string keys."""
        d: dict[object, Value] = {}
        for k, v in (h.items if h else []):
            d[k] = v
        for k in list(d):
            if isinstance(k, str):
                continue
            if not isinstance(k, Sym):
                raise Skip("hash key that is neither a string nor a symbol")
            d[k.name] = d.pop(k)
        return {str(k): v for k, v in d.items()}

    # -- DSL methods -----------------------------------------------------
    def m_plugin(self, call: Call) -> None:
        if call.args and isinstance(call.args[0], str):
            self.plugins.append(call.args[0])

    def m_gemspec(self, call: Call) -> None:
        pos, opts = self.split_options(call.args)
        if pos:
            raise Skip("gemspec with positional arguments")
        raw: dict[object, Value] = {}
        for k, v in (opts.items if opts else []):
            raw[k] = v

        def opt(name: str) -> Value:
            return raw.get(Sym(name))

        for k in raw:
            if not isinstance(k, (Sym, str)):
                raise Skip("hash key that is neither a string nor a symbol")
        path = opt("path")
        glob = opt("glob")
        name = opt("name")
        dev = opt("development_group")
        for label, val in (("path", path), ("glob", glob), ("name", name)):
            if val is not None and not isinstance(val, str):
                raise Skip(f"gemspec {label}: must be a string")
        if dev is not None and not isinstance(dev, (str, Sym)):
            raise Skip("gemspec development_group: must be a string or symbol")
        self.gemspecs.append(
            Gemspec(
                line=call.line,
                path=path if isinstance(path, str) and _truthy(path) else ".",
                glob=glob if isinstance(glob, str) else None,
                name=name if isinstance(name, str) else None,
                development_group=_name(dev, "development_group") if _truthy(dev) else "development",
            )
        )

    def m_ruby(self, call: Call) -> None:
        pos, opts = self.split_options(call.args)
        raw: dict[object, Value] = {}
        for k, v in (opts.items if opts else []):
            raw[k] = v
        versions: list[str] = []

        def flatten(v: Value) -> None:
            if isinstance(v, list):
                for x in v:
                    flatten(x)
            elif isinstance(v, str):
                versions.append(v)
            else:
                raise Skip("ruby version must be a string")

        for a in pos:
            flatten(a)
        if not versions:
            raise Skip("ruby directive without a version (for example one read from a file)")

        def opt(name: str) -> Value:
            return raw.get(Sym(name))

        engine, engine_version, patchlevel = opt("engine"), opt("engine_version"), opt("patchlevel")
        if engine is not None and not isinstance(engine, str):
            raise Skip("ruby engine must be a string")
        ev_list: list[str] | None = None
        if engine_version is False:
            raise Skip("ruby engine_version: false")
        if engine_version is not None:
            if isinstance(engine_version, str):
                ev_list = [engine_version]
            elif isinstance(engine_version, list) and all(isinstance(x, str) for x in engine_version):
                ev_list = [str(x) for x in engine_version]
            else:
                raise Skip("ruby engine_version must be a string or list of strings")
            if not ev_list:
                raise Skip("ruby engine_version is an empty list")
        if _truthy(engine) and ev_list is None:
            raise Invalid("Please define :engine_version")
        if ev_list is not None and not _truthy(engine):
            raise Invalid("Please define :engine")
        if engine == "ruby" and ev_list is not None and versions != ev_list:
            raise Invalid("ruby_version must match the :engine_version for MRI")
        if patchlevel is not None and (
            not isinstance(patchlevel, (str, int)) or isinstance(patchlevel, bool)
        ):
            raise Skip("ruby patchlevel must be a string or integer")

        def norm(v: str) -> str:
            try:
                op, ver = parse_requirement(v)
            except BadRequirementError as e:
                raise Invalid(str(e)) from None
            return ver if op == "=" else f"{op} {ver}"

        normalized = [norm(v) for v in versions]
        engine_versions = normalized
        if ev_list is not None:
            engine_versions = list(ev_list)
            try:
                normalize_requirements([ev_list[0]])
            except BadRequirementError as e:
                raise Invalid(str(e)) from None
        self.ruby = RubyDirective(
            line=call.line,
            versions=tuple(normalized),
            engine=engine if isinstance(engine, str) else "ruby",
            engine_versions=tuple(engine_versions),
            patchlevel=patchlevel if isinstance(patchlevel, (str, int)) else None,
        )

    def m_source(self, call: Call) -> None:
        pos, opts = self.split_options(call.args)
        if not pos:
            raise Invalid("wrong number of arguments (given 0, expected 1+)")
        if len(pos) > 1:
            raise Skip("source with extra positional arguments")
        options = self.normalize_hash(opts)
        if "type" in options:
            raise Skip("source with a :type option uses a Bundler plugin")
        remote = self.normalize_source(pos[0])
        if call.block is not None:
            uri = _normalize_uri(remote)
            self.run_in_source(_Src(RubygemsSource((uri,)), ("rubygems",)), call.block)
        else:
            uri = _normalize_uri(remote)
            if uri not in self.sources:
                self.sources.append(uri)

    def normalize_source(self, source: Value) -> str:
        if isinstance(source, str):
            return source
        if isinstance(source, Sym) and source.name in ("gemcutter", "rubygems", "rubyforge"):
            if self.mode == "1.17":
                return "http://rubygems.org"
            raise Skip(f"deprecated source symbol :{source.name}")
        raise Invalid(f"Unknown source '{_show(source)}'")

    def run_in_source(self, src: _Src | None, block: Block) -> None:
        old = self.source
        self.source = src
        try:
            self.run(block.body)
        finally:
            self.source = old

    def m_git_source(self, call: Call) -> None:
        if call.block is None:
            raise Invalid("You need to pass a block to #git_source")
        pos, opts = self.split_options(call.args)
        if len(pos) != 1 or opts is not None or not isinstance(pos[0], (Sym, str)):
            self.dead_sources.add("*")
            raise Skip("git_source with an unsupported name argument")
        name = _name(pos[0], "git_source name")
        valid = self.valid_keys()
        if name in valid:
            raise Invalid(
                f"You cannot use {name} as a git source. It is a reserved key. "
                f"Reserved keys are: {', '.join(valid)}"
            )
        if call.block.template is None:
            self.dead_sources.add(name)
            raise Skip("git_source block could not be read")
        self.git_sources[name] = _Template(call.block.template, None, self.mode)

    def m_group(self, call: Call) -> None:
        block = self.with_block(call)
        pos, opts = self.split_options(call.args)
        options = self.normalize_hash(opts)
        if _truthy(options.get("branch")):
            raise Invalid("The `branch` option for `group` is not allowed.")
        extra = [k for k in options if k != "optional"]
        if extra:
            groups = ", ".join(f":{_show(g)}" for g in pos)
            raise Invalid(
                f"You passed {', '.join(':' + k for k in extra)} as "
                f"{'options' if len(extra) > 1 else 'an option'} for group {groups}, but "
                f"{'they are' if len(extra) > 1 else 'it is'} invalid. Valid options are: optional."
            )
        for g in pos:
            _name(g, "group name")
        self.groups.extend(pos)
        if _truthy(options.get("optional", False)):
            for g in [g for g in pos if g not in self.optional_groups]:
                self.optional_groups.append(g)
        try:
            self.run(block.body)
        finally:
            for _ in pos:
                self.groups.pop()

    def m_install_if(self, call: Call) -> None:
        block = self.with_block(call)
        self.install_conditionals.extend(call.args)
        try:
            self.run(block.body)
        finally:
            for _ in call.args:
                self.install_conditionals.pop()

    def m_platforms(self, call: Call) -> None:
        block = self.with_block(call)
        for p in call.args:
            _name(p, "platform name")
        self.platforms.extend(call.args)
        try:
            self.run(block.body)
        finally:
            for _ in call.args:
                self.platforms.pop()

    m_platform = m_platforms

    def m_env(self, call: Call) -> None:
        block = self.with_block(call)
        if len(call.args) != 1 or not isinstance(call.args[0], str):
            raise Skip("env block with a non-string name")
        old = self.env
        self.env = call.args[0]
        try:
            self.run(block.body)
        finally:
            self.env = old

    def m_git(self, call: Call) -> None:
        if call.block is None:
            raise Invalid("You can no longer specify a git source by itself.")
        pos, opts = self.split_options(call.args)
        if len(pos) != 1 or not isinstance(pos[0], str):
            raise Skip("git block with a non-string URI")
        options = self.normalize_hash(opts)
        if "version" in options:
            raise Skip("git block with a version: option")
        src = self.make_git(pos[0], options, None)
        self.run_in_source(src, call.block)

    def m_github(self, call: Call) -> None:
        if call.block is None:
            raise Invalid("GitHub sources require a block")
        pos, opts = self.split_options(call.args)
        if len(pos) != 1 or not isinstance(pos[0], str):
            raise Skip("github block with a non-string repository")
        options = self.normalize_hash(opts)
        if "version" in options:
            raise Skip("github block with a version: option")
        if "github" in self.dead_sources:
            raise Skip("github refers to a git_source that could not be read")
        uri = self.git_sources["github"].call(pos[0])
        self.run_in_source(self.make_git(uri, options, None), call.block)

    def m_path(self, call: Call) -> None:
        pos, opts = self.split_options(call.args)
        if len(pos) != 1 or not isinstance(pos[0], str):
            raise Skip("path with a non-string argument")
        options = self.normalize_hash(opts)
        if "version" in options:
            raise Skip("path block with a version: option")
        if call.block is None:
            if self.mode == "2":
                raise Skip("path without a block behaves differently across Bundler versions")
            self.make_path(pos[0], options, None)
            return
        self.run_in_source(self.make_path(pos[0], options, None), call.block)

    # -- sources ----------------------------------------------------------
    @staticmethod
    def _opt_str(options: dict[str, Value], key: str) -> str | None:
        v = options.get(key)
        if v is None:
            return None
        if isinstance(v, (str, Sym)):
            return _name(v, key)
        raise Skip(f"`{key}:` must be a string or symbol")

    def make_git(self, uri: str, options: dict[str, Value], version: str | None) -> _Src:
        branch = self._opt_str(options, "branch")
        tag = self._opt_str(options, "tag")
        ref = self._opt_str(options, "ref")
        sub = options.get("submodules")
        if sub is not None and not isinstance(sub, bool):
            raise Skip("`submodules:` must be true, false or nil")
        glob = options.get("glob")
        if glob is not None and not isinstance(glob, str):
            raise Skip("`glob:` must be a string")
        eff_ref = ref or branch or tag or "master"
        ver = (version or "").strip().replace("-", ".pre.")
        model = GitSource(uri, branch, tag, ref, sub, glob)
        return _Src(model, ("git", uri, eff_ref, branch, ver, sub))

    def make_path(self, path: str, options: dict[str, Value], version: str | None) -> _Src:
        if path.startswith("~") or path.startswith("//") or path == "":
            raise Skip("path that depends on the home directory or is empty")
        glob = options.get("glob")
        if glob is not None and not isinstance(glob, str):
            raise Skip("`glob:` must be a string")
        model = PathSource(path, glob)
        norm = posixpath.normpath(posixpath.join("/root", path))
        return _Src(model, ("path", norm, version))

    # -- gem ---------------------------------------------------------------
    def m_gem(self, call: Call) -> None:
        args = list(call.args)
        pos, opts = self.split_options(args)
        if not pos:
            raise Invalid("wrong number of arguments (given 0, expected 1+)")
        name_v, *version_args = pos
        if isinstance(name_v, Sym):
            raise Invalid(f"You need to specify gem names as Strings. Use 'gem \"{name_v.name}\"' instead")
        if not isinstance(name_v, str):
            raise Skip("gem name is not a string literal")
        name = name_v
        if re.search(r"[ \t\r\n\f\v]", name):
            raise Invalid(f"'{name}' is not a valid gem name because it contains whitespace")
        if name == "":
            raise Invalid("an empty gem name is not valid")
        options = self.normalize_hash(opts)
        options["gemfile"] = True
        git_names = list(self.git_sources)
        # validate_keys
        if _truthy(options.get("branch")) and not (
            _truthy(options.get("git")) or _truthy(options.get("github"))
            or any(k in self.git_sources for k in options)
        ):
            raise Invalid(
                f"The `branch` option for `gem '{name}'` is not allowed. "
                "Only gems with a git source can specify a branch"
            )
        dead = [k for k in options if k in self.dead_sources]
        if dead:
            raise Skip(f"`{dead[0]}:` refers to a git_source that could not be read")
        invalid = [k for k in options if k not in self.valid_keys() and k not in git_names]
        if invalid and "*" in self.dead_sources:
            raise Skip("gem option that may belong to a git_source that could not be read")
        if invalid and self.mode == "2":
            raise Skip(
                f"gem option {', '.join(invalid)}: not known to this reader; "
                "newer Bundler versions may define it"
            )
        if invalid:
            raise Invalid(
                f"You passed {', '.join(':' + k for k in invalid)} as "
                f"{'options' if len(invalid) > 1 else 'an option'} for gem '{name}', but "
                f"{'they are' if len(invalid) > 1 else 'it is'} invalid."
            )
        # requirements
        flat: list[str] = []

        def flatten(v: Value) -> None:
            if isinstance(v, list):
                for x in v:
                    flatten(x)
            elif isinstance(v, str):
                flat.append(v)
            else:
                raise Skip("version requirement is not a string")

        for v in version_args:
            flatten(v)

        # groups
        gv = options.pop("groups", None)
        gsel = gv if _truthy(gv) else options.get("group")
        groups = list(self.groups)
        options.pop("group", None)
        for g in _array(gsel):
            groups.append(g)
        group_names = [_name(g, "group name") for g in groups] or ["default"]

        # install_if
        conds = list(self.install_conditionals)
        conds.extend(_array(options.pop("install_if", None)))
        install = True
        for c in conds:
            if not _truthy(c):
                install = False
                break

        # platforms
        pv = options.get("platform")
        psel = pv if _truthy(pv) else options.get("platforms")
        options.pop("platforms", None)
        plats = list(self.platforms) + _array(psel)
        plat_names = [_name(p, "platform name") for p in plats]
        for p in plat_names:
            if p in VALID_PLATFORMS:
                continue
            if self.mode == "2":
                if _NEWER_PLATFORM.match(p):
                    continue
                raise Skip(f"platform `{p}` is not a platform name this reader knows")
            raise Invalid(
                f"`{p}` is not a valid platform. The available options are: "
                "the platforms listed in Bundler::Dependency::PLATFORM_MAP"
            )

        # source option
        src: _Src | None = None
        if "source" in options:
            uri = _normalize_uri(self.normalize_source(options["source"]))
            src = _Src(RubygemsSource((uri,)), ("rubygems",))

        # git shorthands
        present = [k for k in git_names if k in options]
        if present:
            key = present[-1]
            arg = options[key]
            if not isinstance(arg, str):
                raise Skip(f"`{key}:` shorthand with a non-string value")
            options["git"] = self.git_sources[key].call(arg)

        exact = None
        if version_args and isinstance(version_args[0], str):
            m = _EXACT_VERSION.match(version_args[0])
            exact = m.group(1) if m else None
        for kind in ("git", "path"):
            param = options.get(kind)
            if not _truthy(param):
                continue
            if not isinstance(param, str):
                raise Skip(f"`{kind}:` must be a string")
            if kind == "git":
                src = self.make_git(param, options, exact)
            else:
                src = self.make_path(param, options, exact)
        if src is None:
            src = self.source

        # require
        autorequire: tuple[str | bool, ...] | None = None
        if "require" in options:
            req_v = options["require"]
            items = _array(req_v if _truthy(req_v) else None)
            out: list[str | bool] = []
            for it in items:
                if isinstance(it, Sym):
                    out.append(it.name)
                elif isinstance(it, (str, bool)):
                    out.append(it)
                else:
                    raise Skip("require: value must be strings")
            autorequire = tuple(out)

        # type
        dtype = "runtime"
        if "type" in options:
            tv = options["type"]
            if _truthy(tv):
                if not isinstance(tv, Sym):
                    raise Skip("`type:` must be a symbol")
                if tv.name not in ("runtime", "development"):
                    raise Invalid(f"Valid types are [:development, :runtime], not :{tv.name}")
                dtype = tv.name

        try:
            reqs = normalize_requirements(flat)
        except BadRequirementError as e:
            raise Invalid(str(e)) from None
        except AmbiguousOrder:
            raise Skip("requirements that compare equal but are spelled differently") from None

        frp = options.get("force_ruby_platform")
        if frp is not None and not isinstance(frp, bool):
            raise Skip("`force_ruby_platform:` must be true, false or nil")
        dep = Dependency(
            name=name,
            requirements=format_requirements(reqs),
            groups=tuple(group_names),
            platforms=tuple(plat_names),
            source=src.model if src else None,
            autorequire=autorequire,
            type=dtype,
            env=self.env,
            install_if=install,
            force_ruby_platform=frp,
            line=call.line,
        )
        self.add_dependency(dep, reqs, src)

    def add_dependency(self, dep: Dependency, reqs: list[tuple[str, str]], src: _Src | None) -> None:
        idx = next((i for i, d in enumerate(self.dependencies) if d.name == dep.name), None)
        if idx is not None:
            current = self.dependencies[idx]
            cur_reqs = self.dep_reqs[idx]
            cur_src = self.dep_sources[idx]
            deleted = False
            if current.type == "development":
                del self.dependencies[idx], self.dep_reqs[idx], self.dep_sources[idx]
                deleted = True
            if not requirements_equal(cur_reqs, reqs):
                if not deleted:
                    if dep.type == "development":
                        return
                    raise Invalid(
                        "You cannot specify the same gem twice with different version requirements.\n"
                        f"You specified: {current.name} ({current.requirement}) and "
                        f"{dep.name} ({dep.requirement})"
                    )
            same_src = (cur_src is None and src is None) or (
                cur_src is not None and cur_src.same(src)
            )
            if not same_src and not deleted:
                if dep.type == "development":
                    return
                raise Invalid(
                    "You cannot specify the same gem twice coming from different sources."
                )
        self.dependencies.append(dep)
        self.dep_reqs.append(reqs)
        self.dep_sources.append(src)


def _show(v: Value) -> str:
    if isinstance(v, Sym):
        return v.name
    return str(v)
