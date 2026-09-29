"""Deterministic generator of Gemfiles that mix every static construct the reader supports.

A fraction of the output is deliberately invalid for Bundler or dynamic, so the
differential run also checks that the reader never answers where Bundler
raises. The generator is seeded; the same seed yields the same files.
"""

from __future__ import annotations

import random

NAMES = (
    "rails rack rspec pg puma sidekiq redis nokogiri devise pry byebug rubocop "
    "sqlite3 mysql2 bootsnap webpacker sass-rails uglifier coffee-rails jbuilder "
    "capybara selenium-webdriver factory_bot_rails faker kaminari haml-rails "
    "activeadmin cancancan carrierwave figaro foreman guard listen spring tzinfo-data "
    "web-console rb-fsevent thin unicorn whenever zeitwerk "
).split()

REQS = [
    "1.2.3", "~> 2.0", ">= 1.0", "< 3", "!= 1.5", "= 4", "~> 1.0.pre", "1.0-beta", ">=0.9",
    " >= 1 ", ">= 0", "0", "~>1.0.0", "2.0.0.rc1", "~> 1.a", "<= 9.9.9", "> 1.0.a", "1.0", "1.0.0",
    "~> 5.2.0", ">= 2.3.0", "< 2.0.pre", "= 1.0.b2", "3.1.0.beta.1", "~> 0.10", "5", "5.0", "5.0.0",
]
PLATFORMS = [
    "ruby", "mri", "mswin", "mingw", "x64_mingw", "jruby", "rbx", "ruby_25", "mri_24", "mswin64",
    "truffleruby", "jruby_19", "mingw_20", "x64_mingw_23", "mri_18", "ruby_18",
]
GROUPS = ["development", "test", "production", "staging", "ci", "docs", "assets", "default"]
HOSTS = ["github.com", "gitlab.com", "example.org", "git.example.net"]
SOURCES = [
    "https://rubygems.org", "http://rubygems.org", "https://gems.example.com/",
    "https://user:pw@gems.example.com/private", "https://rubygems.org/", "https://gem.fury.io/acme",
    "file:///srv/gems", "http://localhost:9292",
]
PATHS = ["../foo", "./vendor/foo", "vendor/gems/bar/", "gems//baz", "a/../b", "/abs/path", "../foo/",
         ".", "lib/../lib/x", "foo"]
REFS = ["abc123", "v1.2", "main", "master", "0a1b2c3d", "feature-x", "release/2.0"]


class Gen:
    def __init__(self, seed: str, invalid: bool = False, dynamic: bool = False) -> None:
        self.r = random.Random(seed)
        self.invalid = invalid
        self.dynamic = dynamic
        self.lines: list[str] = []
        self.custom_sources: list[str] = []
        self.used: list[str] = []
        pool = list(NAMES) + [f"gem-{i}" for i in range(40)]
        self.r.shuffle(pool)
        self.names_pool = pool
        self.reuse = self.r.random() < 0.15
        self.emitted: list[str] = []
        self.force_paren = False

    # -- literals --------------------------------------------------------
    def q(self, s: str) -> str:
        r = self.r.random()
        if r < 0.55:
            return f"'{s}'"
        if r < 0.85:
            return f'"{s}"'
        if r < 0.90:
            return f"%q({s})"
        if r < 0.94:
            return f"%Q[{s}]"
        return f"%({s})"

    def sym(self, s: str) -> str:
        r = self.r.random()
        if r < 0.80:
            return f":{s}"
        if r < 0.90:
            return f':"{s}"'
        if r < 0.95:
            return f":'{s}'"
        return self.q(s)

    def name_list(self, items: list[str], allow_words: bool = True) -> str:
        """A list of names as symbols or strings, or a single scalar."""
        r = self.r.random()
        if len(items) == 1 and r < 0.4:
            return self.sym(items[0]) if self.r.random() < 0.8 else self.q(items[0])
        if r < 0.6:
            return "[" + ", ".join(self.sym(i) for i in items) + "]"
        if r < 0.75 and allow_words:
            return "%i[" + " ".join(items) + "]"
        if r < 0.85 and allow_words:
            return "%w[" + " ".join(items) + "]"
        if r < 0.92:
            return "[" + ", ".join(self.q(i) for i in items) + "]"
        return "[\n    " + ",\n    ".join(self.sym(i) for i in items) + ",\n  ]"

    def key(self, k: str, v: str) -> str:
        r = self.r.random()
        if r < 0.62:
            return f"{k}: {v}"
        if r < 0.85:
            return f":{k} => {v}"
        if r < 0.93:
            return f"'{k}' => {v}"
        return f'"{k}" => {v}'

    def hash_args(self, pairs: list[str]) -> str:
        self.r.shuffle(pairs)
        if self.r.random() < 0.08:
            return "{ " + ", ".join(pairs) + " }"
        return ", ".join(pairs)

    # -- pieces ----------------------------------------------------------
    def requirement_args(self) -> list[str]:
        n = self.r.choices([0, 1, 2, 3], [4, 8, 3, 1])[0]
        reqs = [self.r.choice(REQS) for _ in range(n)]
        if n and self.r.random() < 0.12:
            return ["[" + ", ".join(self.q(x) for x in reqs) + "]"]
        return [self.q(x) for x in reqs]

    def git_uri(self) -> str:
        h = self.r.choice(HOSTS)
        u = self.r.choice(["a", "acme", "rails", "user-1"])
        n = self.r.choice(["foo", "bar", "baz.rb", "x"])
        return self.r.choice([f"https://{h}/{u}/{n}.git", f"git@{h}:{u}/{n}.git", f"git://{h}/{u}/{n}"])

    def repo(self) -> str:
        return self.r.choice(["acme/foo", "rails/rails", "user-1/bar.rb", "solo", "a/b/c"])

    def gem_options(self, valid: bool = True) -> list[str]:
        r = self.r
        pairs: list[str] = []
        if r.random() < 0.25:
            gs = r.sample(GROUPS, r.randint(1, 3))
            k = r.choice(["group", "groups"])
            pairs.append(self.key(k, self.name_list(gs)))
        if r.random() < 0.2:
            ps = r.sample(PLATFORMS, r.randint(1, 3))
            pairs.append(self.key(r.choice(["platform", "platforms"]), self.name_list(ps)))
        if r.random() < 0.22:
            v = r.choice(["false", "true", "nil", self.q("x/y"), "[" + self.q("a") + ", " + self.q("b") + "]",
                          "[false]", self.sym("sym")])
            pairs.append(self.key("require", v))
        if r.random() < 0.12:
            pairs.append(self.key("source", self.q(r.choice(SOURCES))))
        if r.random() < 0.06:
            pairs.append(self.key("type", r.choice([":development", ":runtime"])))
        if r.random() < 0.06:
            pairs.append(self.key("install_if", r.choice(["true", "false", "nil", "true"])))
        kind = r.random()
        if kind < 0.18:
            pairs.append(self.key("git", self.q(self.git_uri())))
            self.git_extras(pairs)
        elif kind < 0.30:
            pairs.append(self.key("github", self.q(self.repo())))
            self.git_extras(pairs)
        elif kind < 0.34:
            pairs.append(self.key(r.choice(["gist", "bitbucket"]), self.q(self.repo())))
        elif kind < 0.40 and self.custom_sources:
            pairs.append(self.key(r.choice(self.custom_sources), self.q(self.repo())))
            self.git_extras(pairs)
        elif kind < 0.50:
            pairs.append(self.key("path", self.q(r.choice(PATHS))))
            if r.random() < 0.15:
                pairs.append(self.key("glob", self.q("*.gemspec")))
            if r.random() < 0.1:
                pairs.append(self.key("name", self.q("other")))
        return pairs

    def git_extras(self, pairs: list[str]) -> None:
        r = self.r
        if r.random() < 0.3:
            pairs.append(self.key("branch", self.q(r.choice(REFS)) if r.random() < 0.8 else self.sym("main")))
        if r.random() < 0.2:
            pairs.append(self.key("ref", self.q(r.choice(REFS))))
        if r.random() < 0.15:
            pairs.append(self.key("tag", self.q(r.choice(REFS))))
        if r.random() < 0.1:
            pairs.append(self.key("submodules", r.choice(["true", "false"])))
        if r.random() < 0.05:
            pairs.append(self.key("glob", self.q("{,*}.gemspec")))

    def call(self, name: str, args: list[str], paren: bool = False) -> str:
        """Format a method call, with or without parentheses, on one or several lines."""
        r = self.r
        joiner = ", "
        if len(args) > 2 and r.random() < 0.2:
            joiner = ",\n    "
        body = joiner.join(args)
        if paren or self.force_paren or r.random() < 0.25:
            text = f"{name}({body})"
        else:
            text = f"{name} {body}" if args else name
        if r.random() < 0.03 and args and joiner == ", ":
            text = text.replace(", ", " , ", 1)
        return text

    def comment(self) -> str:
        return self.r.choice(["  # note", " # TODO: pin", "\t# tab comment", "  #"])

    # -- statements ------------------------------------------------------
    def gem_stmt(self, indent: str) -> str:
        r = self.r
        if self.reuse and self.emitted and r.random() < 0.3:
            return indent + r.choice(self.emitted)
        name = self.names_pool.pop()
        self.used.append(name)
        args = [self.q(name)] + self.requirement_args()
        opts = self.gem_options()
        if opts:
            args.append(self.hash_args(opts))
        text = self.call("gem", args)
        if r.random() < 0.1:
            text += self.comment()
        self.emitted.append(text)
        return "\n".join(indent + ln for ln in text.split("\n"))

    def block_stmt(self, indent: str, depth: int) -> list[str]:
        r = self.r
        kind = r.choice(["group", "group", "group", "platforms", "platforms", "source", "git", "github",
                         "path", "env", "install_if", "group_opt"])
        brace = r.random() < 0.15
        self.force_paren = brace
        if kind == "group":
            head = self.call("group", [self.sym(g) if r.random() < 0.85 else self.q(g)
                                       for g in r.sample(GROUPS, r.randint(1, 3))])
        elif kind == "group_opt":
            head = self.call("group", [self.sym(r.choice(GROUPS)),
                                       self.hash_args([self.key("optional", r.choice(["true", "false"]))])])
        elif kind == "platforms":
            head = self.call(r.choice(["platforms", "platform"]),
                             [self.sym(p) for p in r.sample(PLATFORMS, r.randint(1, 3))])
        elif kind == "source":
            head = self.call("source", [self.q(r.choice(SOURCES))])
        elif kind == "git":
            pairs: list[str] = []
            self.git_extras(pairs)
            head = self.call("git", [self.q(self.git_uri())] + ([self.hash_args(pairs)] if pairs else []))
        elif kind == "github":
            pairs = []
            self.git_extras(pairs)
            head = self.call("github", [self.q(self.repo())] + ([self.hash_args(pairs)] if pairs else []))
        elif kind == "path":
            pairs = []
            if r.random() < 0.2:
                pairs.append(self.key("glob", self.q("*.gemspec")))
            head = self.call("path", [self.q(r.choice(PATHS))] + ([self.hash_args(pairs)] if pairs else []))
        elif kind == "env":
            head = self.call("env", [self.q(r.choice(["CI", "STAGING", "FOO"]))])
        else:
            head = self.call("install_if", [r.choice(["true", "false", "nil"])])
        self.force_paren = False
        out = [indent + head + (" {" if brace else " do")]
        out += self.statements(indent + "  ", depth + 1, r.randint(0, 3))
        out.append(indent + ("}" if brace else "end"))
        return out

    def statements(self, indent: str, depth: int, count: int) -> list[str]:
        r = self.r
        out: list[str] = []
        for _ in range(count):
            x = r.random()
            if x < 0.12:
                out.append("")
            elif x < 0.2:
                out.append(indent + "# " + r.choice(["dependencies", "test tools", "TODO", "pinned for CI"]))
            elif x < 0.32 and depth < 3:
                out.extend(self.block_stmt(indent, depth))
            else:
                out.append(self.gem_stmt(indent))
        return out

    def git_source_def(self) -> list[str]:
        r = self.r
        name = r.choice(["github", "gitlab", "codeberg", "acme", "bb"])
        host = r.choice(["github.com", "gitlab.com", "codeberg.org"])
        style = r.choice(["plain", "idiom", "do", "brace_multi", "ssh"])
        var = r.choice(["repo", "repo_name", "name"])
        if style == "plain":
            out = [f'git_source(:{name}) {{ |{var}| "https://{host}/#{{{var}}}.git" }}']
        elif style == "ssh":
            out = [f'git_source(:{name}) {{|{var}| "git@{host}:#{{{var}}}.git"}}']
        elif style == "idiom":
            out = [
                f"git_source(:{name}) do |{var}|",
                f'  {var} = "#{{{var}}}/#{{{var}}}" unless {var}.include?("/")',
                f'  "https://{host}/#{{{var}}}.git"',
                "end",
            ]
        elif style == "do":
            out = [f"git_source(:{name}) do |{var}|", f'  "https://{host}/rails/#{{{var}}}"', "end"]
        else:
            out = [
                f"git_source({self.sym(name)}) {{ |{var}|",
                f'  {var} = "#{{{var}}}/#{{{var}}}" unless {var}.include?("/")',
                f'  "https://{host}/#{{{var}}}.git"',
                "}",
            ]
        if name not in self.custom_sources:
            self.custom_sources.append(name)
        return out

    def header(self) -> None:
        r = self.r
        if r.random() < 0.15:
            self.lines.append("# frozen_string_literal: true")
        if r.random() < 0.05:
            self.lines += ["=begin", "block comment source 'x'", "=end"]
        for _ in range(r.choices([0, 1, 2], [1, 12, 1])[0]):
            self.lines.append(self.call("source", [self.q(r.choice(SOURCES))]))
        if r.random() < 0.3:
            self.lines.extend(self.git_source_def())
        if r.random() < 0.15:
            self.lines.extend(self.git_source_def())
        if r.random() < 0.25:
            v = r.choice(["2.5.1", "2.7", ">= 2.3", "3.0.0", "2.6.0-rc1", "~> 2.5"])
            extra = r.choice([
                [], [], [],
                [self.key("patchlevel", "'100'")],
                [self.key("engine", "'jruby'"), self.key("engine_version", "'9.2.0.0'")],
                [self.key("engine", "'ruby'"), self.key("engine_version", "'" + v + "'")],
                [self.key("patchlevel", "42")],
            ])
            self.lines.append(self.call("ruby", [self.q(v)] + ([self.hash_args(extra)] if extra else [])))
        if r.random() < 0.1:
            self.lines.append(
                r.choice(["gemspec", "gemspec path: '..'", "gemspec(name: 'x', development_group: :dev)",
                          "gemspec path: 'sub', glob: '*.gemspec'"])
            )
        if r.random() < 0.04:
            self.lines.append("plugin 'bundler-graph'")

    def build(self) -> str:
        r = self.r
        self.header()
        self.lines.extend(self.statements("", 0, r.randint(1, 25)))
        if self.invalid:
            self.lines.insert(self.top_level_index(), self.invalid_stmt())
        if self.dynamic:
            self.lines.insert(self.top_level_index(), self.dynamic_stmt())
        if r.random() < 0.03:
            self.lines += ["__END__", "gem 'ignored'"]
        text = "\n".join(self.lines) + ("\n" if r.random() < 0.95 else "")
        if r.random() < 0.05:
            text = text.replace("\n", "\r\n")
        return text

    def top_level_index(self) -> int:
        """A random line index that is between top-level statements."""
        ok: list[int] = []
        depth = 0
        for i in range(len(self.lines) + 1):
            if depth == 0:
                nxt = self.lines[i] if i < len(self.lines) else ""
                prev = self.lines[i - 1].rstrip() if i else ""
                if not nxt.startswith((" ", "\t", "}")) and not prev.endswith((",", "[", "=begin")):
                    ok.append(i)
            if i < len(self.lines):
                st = self.lines[i].strip()
                if st.endswith((" do", " {")) or (st.startswith("git_source") and st.endswith("|")):
                    depth += 1
                elif st in ("end", "}"):
                    depth -= 1
        return self.r.choice(ok) if ok else 0

    def invalid_stmt(self) -> str:
        r = self.r
        return r.choice([
            "gem 'a', platforms: :nope",
            "gem 'a', bogus: true",
            "gem :sym",
            "gem 'has space'",
            "gem ''",
            "gem 'a', branch: 'x'",
            "gem 'a', '>> 1'",
            "gem 'a', '1.x'",
            "gem 'dup', '1.0'\ngem 'dup', '2.0'",
            "gem 'dup2', git: 'https://x/y.git'\ngem 'dup2', path: '../y'",
            "gem 'dup3'\ngem 'dup3', git: 'https://x/y.git'",
            "gem 'dup4', '~> 1.0'\ngem 'dup4', '~> 1.0.0'",
            "group :a",
            "platforms :ruby",
            "git 'https://x/y.git'",
            "github 'a/b'",
            "gem 'a', path: '../x', branch: 'y'",
            "source :nothing",
            "git_source(:group) { |r| \"x\" }",
            "git_source(:foo)",
            "group :a, bogus: 1 do\nend",
            "ruby '2.5', engine: 'jruby'",
            "ruby '2.5', engine_version: '9.0'",
            "ruby '2.5', engine: 'ruby', engine_version: '2.6'",
            "ruby 'abc'",
            "gem 'a', type: :other",
            "gem",
            "gem 'a', require: false, platform: :windows",
        ])

    def dynamic_stmt(self) -> str:
        r = self.r
        return r.choice([
            "gem 'a' if ENV['X']",
            "gem 'a', ENV['V']",
            "gem \"a-#{ENV['SUFFIX']}\"",
            "if RUBY_VERSION >= '2.5'\n  gem 'a'\nend",
            "unless ENV['CI']\n  gem 'b'\nend",
            "eval_gemfile 'Gemfile.local'",
            "eval_gemfile File.expand_path('x', __dir__)",
            "rails_version = '~> 6.0'\ngem 'rails', rails_version",
            "gem 'a', File.read('v').strip",
            "install_if -> { RUBY_PLATFORM =~ /darwin/ } do\n  gem 'rb-fsevent'\nend",
            "gem 'a', <<~V\n  1.0\nV",
            "case RUBY_PLATFORM\nwhen /darwin/\n  gem 'a'\nend",
            "def helper\n  gem 'x'\nend",
            "%w[a b].each { |g| gem g }",
            "gem 'a', github: \"#{ENV['ORG']}/a\"",
            "gem 'a', require: !!ENV['R']",
            "puts 'hi'",
            "gem 'a', path: File.expand_path('..', __FILE__)",
            "gem 'a' unless RUBY_PLATFORM.include?('java')",
            "gem 'x', '~> 1.0' + '.1'",
            "gem 'a', *%w[1.0]",
            "gem 'a', **{}",
            "ENV['FOO'] ||= 'bar'\ngem 'b'",
            "instance_eval File.read('x')",
            "gem 'a'; gem 'b' if true",
            "group ENV['G'].to_sym do\n  gem 'a'\nend",
            "gem 'a', platforms: RUBY_PLATFORM",
        ])


def generate(seed: int, count: int) -> list[str]:
    """Return `count` Gemfile texts. About 8% are invalid for Bundler, 10% contain a dynamic construct."""
    out: list[str] = []
    for i in range(count):
        r = random.Random(f"kind-{seed}-{i}")
        g = Gen(f"{seed}-{i}", invalid=r.random() < 0.08, dynamic=r.random() < 0.10)
        out.append(g.build())
    return out
